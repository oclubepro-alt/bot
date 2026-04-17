"""
product_extractor_v2.py — Extrator de produtos em camadas.

Ordem de prioridade:
  Camada 1 — Playwright (renderização real de JS)
  Camada 2 — requests + BeautifulSoup (fallback HTML)
  Camada 3 — Retorno seguro mínimo (nunca quebra o fluxo)

Logs obrigatórios em cada etapa.
"""
import json
import logging
import os
import re
import asyncio

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

_TIMEOUT_HTTP = 15
_TIMEOUT_PLAYWRIGHT = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_price(raw: str) -> str | None:
    if not raw:
        return None
    raw = str(raw).replace("\xa0", " ").strip()
    # Remove tudo que não é dígito, vírgula ou ponto
    cleaned = re.sub(r"[^\d,.]", "", raw)
    if not cleaned:
        return None
    # Normaliza para formato BR
    if "," not in cleaned:
        if "." in cleaned and len(cleaned.split(".")[-1]) == 2:
            cleaned = cleaned.replace(".", ",")
        else:
            cleaned = cleaned.replace(".", "") + ",00"
    return f"R$ {cleaned}"


def _extract_from_soup(soup: BeautifulSoup, base_url: str) -> dict:
    """Extrai dados de uma página já parseada."""
    data = {"titulo": None, "preco": None, "preco_original": None, "imagem": None}

    # ── TÍTULO ──────────────────────────────────────────────────────────────
    title_selectors = [
        "#productTitle",             # Amazon
        ".ui-pdp-title",             # Mercado Livre
        "h1[itemprop='name']",       # Magalu / genérico
        ".header-product__title",    # Netshoes
        "h1.product-name",
        "h1",
    ]
    for sel in title_selectors:
        tag = soup.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if len(text) > 10:
                data["titulo"] = text
                logger.info(f"[EXTRACTOR_V2] Título via '{sel}': {text[:60]}")
                break

    if not data["titulo"]:
        for attr in [("property", "og:title"), ("name", "twitter:title")]:
            meta = soup.find("meta", attrs={attr[0]: attr[1]})
            if meta and meta.get("content"):
                raw = meta["content"]
                # Remove sufixos de loja
                raw = re.sub(r"\s*[|–\-]\s*(Amazon|Mercado Livre|Magalu|Shopee).*", "", raw, flags=re.I)
                data["titulo"] = raw.strip()
                break

    # ── PREÇO ───────────────────────────────────────────────────────────────
    # 1. Open Graph
    for prop in ["product:price:amount", "og:price:amount"]:
        meta = soup.find("meta", attrs={"property": prop})
        if meta and meta.get("content"):
            data["preco"] = _clean_price(meta["content"])
            if data["preco"]:
                logger.info(f"[EXTRACTOR_V2] Preço via meta '{prop}': {data['preco']}")
                break

    # 2. JSON-LD / Schema.org
    if not data["preco"]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                js = json.loads(script.string or "")
                items = js if isinstance(js, list) else [js]
                for item in items:
                    product = item if item.get("@type") == "Product" else item.get("mainEntity")
                    if isinstance(product, dict) and product.get("@type") == "Product":
                        offers = product.get("offers", {})
                        price = (
                            offers.get("price") if isinstance(offers, dict)
                            else offers[0].get("price") if isinstance(offers, list) and offers
                            else None
                        )
                        if price:
                            data["preco"] = _clean_price(str(price))
                            logger.info(f"[EXTRACTOR_V2] Preço via JSON-LD: {data['preco']}")
                            break
            except Exception:
                continue
            if data["preco"]:
                break

    # 3. Seletores CSS específicos de loja
    if not data["preco"]:
        price_selectors = [
            ".ui-pdp-price__second-line .andes-money-amount__fraction",  # ML
            ".andes-money-amount--main .andes-money-amount__fraction",    # ML
            "#priceblock_ourprice", "#priceblock_dealprice",              # Amazon legacy
            ".a-price .a-offscreen",                                      # Amazon
            "[data-cy='price-tag'] .price-tag-fraction",                  # ML novo
            "[itemprop='price']",
            ".price-box .price",
        ]
        for sel in price_selectors:
            tag = soup.select_one(sel)
            if tag:
                val = tag.get_text(strip=True)
                # Tenta pegar centavos no irmão seguinte
                parent = tag.parent
                cents = parent.select_one(".andes-money-amount__cents, .price-tag-cents") if parent else None
                if cents:
                    val += f",{cents.get_text(strip=True)}"
                price_clean = _clean_price(val)
                if price_clean:
                    data["preco"] = price_clean
                    logger.info(f"[EXTRACTOR_V2] Preço via seletor '{sel}': {data['preco']}")
                    break

    # 4. Regex bruto no HTML
    if not data["preco"]:
        match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", str(soup))
        if match:
            data["preco"] = f"R$ {match.group(1)}"
            logger.info(f"[EXTRACTOR_V2] Preço via regex bruto: {data['preco']}")

    # ── IMAGEM ──────────────────────────────────────────────────────────────
    for og_prop in ["og:image", "twitter:image"]:
        meta = soup.find("meta", attrs={"property": og_prop}) or soup.find("meta", attrs={"name": og_prop})
        if meta and meta.get("content"):
            img = meta["content"]
            if not img.startswith("http"):
                img = urljoin(base_url, img)
            data["imagem"] = img
            break

    if not data["imagem"]:
        img_sel = soup.select_one(".ui-pdp-gallery__figure__image, #imgBlkFront, #landingImage")
        if img_sel:
            src = img_sel.get("src") or img_sel.get("data-src")
            if src:
                data["imagem"] = src if src.startswith("http") else urljoin(base_url, src)

    return data


# ---------------------------------------------------------------------------
# Camada 1 — Playwright
# ---------------------------------------------------------------------------

async def _extract_with_playwright(url: str) -> dict | None:
    """Renderiza a página com Playwright e extrai dados via HTML completo."""
    try:
        from playwright.async_api import async_playwright

        logger.info(f"[EXTRACTOR_V2] PLAYWRIGHT iniciando para: {url[:80]}")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
            )
            page = await browser.new_page(
                user_agent=_HEADERS["User-Agent"],
                locale="pt-BR",
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT_PLAYWRIGHT * 1000)
            # Aguarda conteúdo crítico
            await page.wait_for_timeout(2500)
            html = await page.content()
            final_url = page.url
            await browser.close()

        soup = BeautifulSoup(html, "lxml")
        data = _extract_from_soup(soup, final_url)
        data["source_method"] = "PLAYWRIGHT"
        data["final_url"] = final_url
        logger.info(f"[EXTRACTOR_V2] PLAYWRIGHT concluído → título={data.get('titulo', '')[:50]}, preço={data.get('preco')}")
        return data

    except ImportError:
        logger.warning("[EXTRACTOR_V2] Playwright não instalado. Pulando para fallback HTML.")
        return None
    except Exception as e:
        logger.warning(f"[EXTRACTOR_V2] PLAYWRIGHT falhou: {e}")
        return None


# ---------------------------------------------------------------------------
# Camada 2 — HTML requests + BeautifulSoup
# ---------------------------------------------------------------------------

def _extract_with_requests(url: str) -> dict | None:
    """Tenta extração HTTP simples com BeautifulSoup."""
    try:
        logger.info(f"[EXTRACTOR_V2] HTML_FALLBACK iniciando para: {url[:80]}")
        session = requests.Session()
        resp = session.get(url, headers=_HEADERS, timeout=_TIMEOUT_HTTP, allow_redirects=True)
        resp.raise_for_status()
        final_url = resp.url
        soup = BeautifulSoup(resp.text, "lxml")
        data = _extract_from_soup(soup, final_url)
        data["source_method"] = "HTML_FALLBACK"
        data["final_url"] = final_url
        logger.info(f"[EXTRACTOR_V2] HTML_FALLBACK concluído → título={data.get('titulo', '')[:50]}, preço={data.get('preco')}")
        return data
    except Exception as e:
        logger.warning(f"[EXTRACTOR_V2] HTML_FALLBACK falhou: {e}")
        return None


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------

async def extract_product_data_v2(url: str) -> dict:
    """
    Pipeline de extração em camadas.
    Tenta Playwright primeiro, depois HTML, depois retorno mínimo seguro.
    
    Retorna dict com:
      store, final_url, titulo, imagem, preco, preco_original, source_method, erro
    """
    from bot.utils.detect_store import detect_store
    from bot.utils.url_resolver import resolve_url

    logger.info(f"[EXTRACTOR_V2] ── INÍCIO PIPELINE ─────────────────────────────")
    logger.info(f"[EXTRACTOR_V2] URL recebida: {url[:100]}")

    # Base de retorno seguro
    result = {
        "store": "desconhecida",
        "store_key": "other",
        "final_url": url,
        "affiliate_url": url,
        "titulo": "Produto",
        "imagem": None,
        "preco": "Preço não disponível",
        "preco_original": None,
        "source_method": "FALLBACK_SEM_PRECO",
        "erro": None,
    }

    # ── Resolução da URL final ───────────────────────────────────────────────
    try:
        final_url = await asyncio.to_thread(resolve_url, url)
        result["final_url"] = final_url
        logger.info(f"[EXTRACTOR_V2] URL_RESOLVIDA: {final_url[:100]}")
    except Exception as e:
        final_url = url
        logger.warning(f"[EXTRACTOR_V2] Falha ao resolver URL: {e}. Usando original.")

    # ── Detecção da loja ────────────────────────────────────────────────────
    store_display, store_key = detect_store(final_url)
    result["store"] = store_display
    result["store_key"] = store_key
    logger.info(f"[EXTRACTOR_V2] LOJA_DETECTADA: {store_display} (key={store_key})")

    # ── Camada 1: Playwright ────────────────────────────────────────────────
    data = await _extract_with_playwright(final_url)

    # ── Camada 2: HTML Fallback ─────────────────────────────────────────────
    if not data or not data.get("titulo"):
        logger.info("[EXTRACTOR_V2] Playwright insuficiente. Tentando HTML_FALLBACK...")
        data = await asyncio.to_thread(_extract_with_requests, final_url)

    # ── Camada 3: Retorno mínimo seguro ────────────────────────────────────
    if not data:
        logger.error("[EXTRACTOR_V2] Todas as camadas falharam. Retornando mínimo seguro.")
        result["erro"] = "Todas as camadas de extração falharam."
        return result

    # ── Merge dos dados ─────────────────────────────────────────────────────
    if data.get("titulo"):
        result["titulo"] = data["titulo"]
    if data.get("preco"):
        result["preco"] = data["preco"]
    if data.get("preco_original"):
        result["preco_original"] = data["preco_original"]
    if data.get("imagem"):
        result["imagem"] = data["imagem"]

    result["source_method"] = data.get("source_method", "HTML_FALLBACK")
    result["final_url"] = data.get("final_url", final_url)

    if not result.get("preco") or result["preco"] == "Preço não disponível":
        result["source_method"] = "FALLBACK_SEM_PRECO"
        logger.warning(f"[EXTRACTOR_V2] ERRO_EXTRAINDO_PRECO para {final_url[:60]}")

    logger.info(
        f"[EXTRACTOR_V2] EXTRACAO_SUCESSO | método={result['source_method']} | "
        f"título={result['titulo'][:40]} | preço={result['preco']}"
    )
    return result
