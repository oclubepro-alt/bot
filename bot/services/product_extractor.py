"""
product_extractor.py - Extração robusta de dados do produto via scraping.

Suporta:
  - Amazon        (CSS seletores avançados + JSON-LD + meta OG)
  - Mercado Livre (seletores andes + JSON-LD + meta OG)
  - Magalu        (CSS seletores + JSON-LD + meta OG)
  - Netshoes      (CSS seletores + JSON-LD + meta OG)
  - Genérico      (JSON-LD + meta OG como fallback universal)

A URL recebida deve ser a URL JÁ RESOLVIDA (sem encurtadores).
A detecção de loja é feita pelo módulo detect_store.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Headers por loja
# ---------------------------------------------------------------------------

_HEADERS_AMAZON = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

_HEADERS_GENERIC = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Utilidades gerais
# ---------------------------------------------------------------------------

def clean_price(text: str) -> str | None:
    """Extrai e limpa o formato de preço do texto bruto."""
    if not text:
        return None
    text = text.replace("\xa0", " ").strip()
    # Formato PT-BR: 1.299,99 ou 89,90
    match = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))", text)
    if match:
        val = match.group(1)
        if "." in val and "," not in val and val.count(".") == 1:
            val = val.replace(".", ",")
        return f"R$ {val}"
    # Inteiro: R$ 89
    match_int = re.search(r"R\$\s*(\d+)", text, re.IGNORECASE)
    if match_int:
        return f"R$ {match_int.group(1)},00"
    return None


def extract_json_ld(soup: BeautifulSoup) -> dict:
    """Busca dados estruturados JSON-LD do tipo Product."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "Product":
                        return item
            elif data.get("@type") == "Product":
                return data
            elif "@graph" in data and isinstance(data["@graph"], list):
                for item in data["@graph"]:
                    if item.get("@type") == "Product":
                        return item
        except Exception:
            continue
    return {}


def _meta(soup: BeautifulSoup, *props: str) -> str | None:
    """Retorna o conteúdo da primeira meta tag encontrada."""
    for prop in props:
        tag = soup.find("meta", property=prop) or soup.find("meta", {"name": prop})
        if tag and tag.get("content"):
            return tag["content"]
    return None


def _extract_generic_name(soup: BeautifulSoup) -> str | None:
    """Tenta extrair nome do JSON-LD, og:title ou <title>."""
    jld = extract_json_ld(soup)
    if jld.get("name"):
        return jld["name"]
    og = _meta(soup, "og:title", "twitter:title")
    if og:
        return og
    title = soup.find("title")
    return title.text.strip() if title else None


def _extract_generic_image(soup: BeautifulSoup, final_url: str) -> str | None:
    """Tenta extrair imagem do JSON-LD, og:image ou twitter:image."""
    jld = extract_json_ld(soup)
    jld_img = jld.get("image")
    if isinstance(jld_img, list) and jld_img:
        jld_img = jld_img[0]
    elif isinstance(jld_img, dict):
        jld_img = jld_img.get("url")
    if jld_img:
        return urljoin(final_url, jld_img)

    og = _meta(soup, "og:image", "twitter:image")
    if og:
        return urljoin(final_url, og)
    return None


def _extract_generic_price(soup: BeautifulSoup) -> str | None:
    """Tenta extrair preço do JSON-LD ou de meta tags OG."""
    jld = extract_json_ld(soup)
    offers = jld.get("offers", {})
    if isinstance(offers, dict):
        if offers.get("price"):
            return clean_price(str(offers["price"]))
        if offers.get("lowPrice"):
            return clean_price(str(offers["lowPrice"]))
    if isinstance(offers, list) and offers:
        o = offers[0]
        if o.get("price"):
            return clean_price(str(o["price"]))
        if o.get("lowPrice"):
            return clean_price(str(o["lowPrice"]))
    og_price = _meta(soup, "product:price:amount", "og:price:amount")
    if og_price:
        return clean_price(og_price)
    return None


def _extract_generic_desc(soup: BeautifulSoup) -> str | None:
    """Tenta extrair descrição do JSON-LD ou meta description."""
    jld = extract_json_ld(soup)
    if jld.get("description"):
        return jld["description"]
    return _meta(soup, "og:description", "description")


# ---------------------------------------------------------------------------
# Extratores específicos por loja
# ---------------------------------------------------------------------------

def _extract_amazon(soup: BeautifulSoup, final_url: str) -> dict:
    data: dict = {}

    # --- PREÇO (Atual/Promoção) ---
    PRICE_SELECTORS = [
        "span.a-price > span.a-offscreen",
        ".a-price .a-offscreen",
        "#corePrice_feature_div .a-offscreen",
        "#apex_desktop .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#price_inside_buybox",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        ".reinventPricePriceToPayMargin .a-offscreen",
        "#tp_price_block_total_price_ww .a-offscreen",
    ]
    for sel in PRICE_SELECTORS:
        tag = soup.select_one(sel)
        if tag and tag.get_text(strip=True):
            raw = tag.get_text(strip=True)
            if "," in raw or "." in raw:
                data["preco"] = raw
                logger.info(f"[EXTRACTOR][Amazon] Preço via '{sel}' → {raw}")
                break

    # --- PREÇO ORIGINAL (Riscado) ---
    ORIG_PRICE_SELECTORS = [
        ".basisPrice .a-offscreen",
        "#corePriceDisplay_desktop_feature_div span.a-text-price > span.a-offscreen",
        "span.a-price.a-text-price > span.a-offscreen",
    ]
    for sel in ORIG_PRICE_SELECTORS:
        tag = soup.select_one(sel)
        if tag:
            raw = tag.get_text(strip=True)
            # Evita capturar preco por unidade ex: "R$ 0,02 / Gramas"
            if "/" in raw or "unidade" in raw.lower() or "gramas" in raw.lower():
                continue
            if raw and raw != data.get("preco"):
                data["preco_original"] = raw
                logger.info(f"[EXTRACTOR][Amazon] Preço original via '{sel}' → {raw}")
                break

    # Fallback regex no texto completo para preco se falhou
    if not data.get("preco"):
        match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", soup.get_text())
        if match:
            data["preco"] = f"R$ {match.group(1)}"
            logger.info(f"[EXTRACTOR][Amazon] Preço via regex → {data['preco']}")

    # --- IMAGEM ---
    og_img = _meta(soup, "og:image", "twitter:image")
    if og_img:
        data["imagem"] = og_img
        logger.info("[EXTRACTOR][Amazon] Imagem via og:image")

    if not data.get("imagem"):
        jld = extract_json_ld(soup)
        jld_img = jld.get("image")
        if isinstance(jld_img, list) and jld_img:
            jld_img = jld_img[0]
        elif isinstance(jld_img, dict):
            jld_img = jld_img.get("url")
        if jld_img:
            data["imagem"] = jld_img
            logger.info("[EXTRACTOR][Amazon] Imagem via JSON-LD")

    if not data.get("imagem"):
        landing = soup.select_one("#landingImage")
        if landing:
            dynamic = landing.get("data-a-dynamic-image")
            if dynamic:
                try:
                    img_map = json.loads(dynamic)
                    best = max(img_map.items(), key=lambda i: i[1][0] * i[1][1])
                    data["imagem"] = best[0]
                    logger.info(f"[EXTRACTOR][Amazon] Imagem data-a-dynamic-image ({best[1][0]}x{best[1][1]})")
                except Exception as e:
                    logger.warning(f"[EXTRACTOR][Amazon] Falha data-a-dynamic-image: {e}")
            if not data.get("imagem") and landing.get("data-old-hires"):
                data["imagem"] = landing["data-old-hires"]
            if not data.get("imagem") and landing.get("src"):
                src = landing["src"]
                if any(ext in src for ext in [".jpg", ".jpeg", ".png", ".webp"]):
                    data["imagem"] = src

    if not data.get("imagem"):
        alt = soup.select_one("#imgBlkFront")
        if alt and alt.get("src"):
            data["imagem"] = alt["src"]

    # Garante URL absoluta
    if data.get("imagem"):
        data["imagem"] = urljoin(final_url, data["imagem"])

    if not data.get("preco"):
        logger.warning("[EXTRACTOR][Amazon] Preço não encontrado.")
    if not data.get("imagem"):
        logger.warning("[EXTRACTOR][Amazon] Imagem não encontrada.")

    return data


def _extract_mercadolivre(soup: BeautifulSoup, final_url: str) -> dict:
    data: dict = {}

    # --- PREÇO ---
    # No ML, o preço de venda fica na 'second-line'. O preço riscado fica em 'original-value'.
    # Precisamos garantir que pegamos o valor correto.
    PRICE_SELECTORS = [
        ".ui-pdp-price__second-line .andes-money-amount__fraction", # Preço atual (com desconto)
        ".ui-pdp-price__current-price .andes-money-amount__fraction",
        "span.andes-money-amount__fraction",
    ]
    
    # Tentamos primeiro os seletores de 'preço atual'
    for sel in PRICE_SELECTORS:
        # Evita explicitamente o preço original/riscado
        tag = soup.select_one(sel)
        if tag:
            # Verifica se essa tag não está dentro de um container de 'preço original'
            if tag.find_parent(class_="ui-pdp-price__original-value"):
                continue
                
            fraction = tag.text.strip()
            cents_tag = tag.parent.select_one(".andes-money-amount__cents")
            price_str = fraction
            if cents_tag:
                price_str += f",{cents_tag.text.strip()}"
            
            p = clean_price(price_str)
            if p:
                data["preco"] = p
                logger.info(f"[EXTRACTOR][MercadoLivre] Preço com desconto via '{sel}' → {p}")
                break

    # Fallback meta (apenas se não achou no HTML, pois meta as vezes tem o preço cheio)
    if not data.get("preco"):
        tag = soup.select_one("meta[property='product:price:amount']") or soup.select_one("meta[itemprop='price']")
        if tag and tag.get("content"):
            data["preco"] = clean_price(tag["content"])

    # --- PREÇO ORIGINAL (Riscado) ---
    orig_tag = soup.select_one(".ui-pdp-price__original-value .andes-money-amount__fraction")
    if orig_tag:
        orig_cents = soup.select_one(".ui-pdp-price__original-value .andes-money-amount__cents")
        val_orig = orig_tag.text.strip()
        if orig_cents:
            val_orig += f",{orig_cents.text.strip()}"
        data["preco_original"] = clean_price(val_orig)
        logger.info(f"[EXTRACTOR][MercadoLivre] Preço original detectado: {data['preco_original']}")

    # Fallback JSON-LD / OG
    if not data.get("preco"):
        data["preco"] = _extract_generic_price(soup)

    # Fallback Brutal (Regex no estado da página)
    if not data.get("preco"):
        html_text = str(soup)
        m = re.search(r'"price":\s*(\d+(?:\.\d{2})?)', html_text)
        if m:
            val = m.group(1).replace(".", ",")
            data["preco"] = f"R$ {val}"
        else:
            m = re.search(r'R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)', soup.get_text())
            if m:
                data["preco"] = f"R$ {m.group(1)}"

    # --- IMAGEM ---
    img_tag = (
        soup.select_one(".ui-pdp-gallery__figure img") or
        soup.select_one(".ui-pdp-image img") or
        soup.select_one(".gallery-image-container img")
    )
    if img_tag:
        src = img_tag.get("data-zoom") or img_tag.get("src")
        if src:
            data["imagem"] = urljoin(final_url, src)
            logger.info(f"[EXTRACTOR][MercadoLivre] Imagem via seletor → {data['imagem'][:80]}")

    if not data.get("imagem"):
        data["imagem"] = _extract_generic_image(soup, final_url)

    if not data.get("preco"):
        logger.warning("[EXTRACTOR][MercadoLivre] Preço não encontrado.")
    if not data.get("imagem"):
        logger.warning("[EXTRACTOR][MercadoLivre] Imagem não encontrada.")

    return data


def _extract_magalu(soup: BeautifulSoup, final_url: str) -> dict:
    data: dict = {}

    # --- PREÇO: Magazine Luiza usa elementos com classe price ---
    PRICE_SELECTORS = [
        "[data-testid='price-value']",
        ".price-template__text",
        ".sc-kpDqfB",   # classe frequente (pode variar)
        "p[class*='price']",
        "span[class*='price']",
    ]
    for sel in PRICE_SELECTORS:
        tag = soup.select_one(sel)
        if tag and tag.get_text(strip=True):
            raw = tag.get_text(strip=True)
            price = clean_price(raw)
            if price:
                data["preco"] = price
                logger.info(f"[EXTRACTOR][Magalu] Preço via '{sel}' → {price}")
                break

    # Fallback JSON-LD / OG
    if not data.get("preco"):
        data["preco"] = _extract_generic_price(soup)

    # --- PREÇO ORIGINAL (Riscado) ---
    orig_tag = soup.select_one("[data-testid='price-original']") or soup.select_one(".price-template__item--old")
    if orig_tag:
        data["preco_original"] = clean_price(orig_tag.get_text(strip=True))

    # --- IMAGEM ---
    IMGSEL = [
        "[data-testid='image-selected-thumbnail']",
        ".product-media__image img",
        "img[class*='product']",
    ]
    for sel in IMGSEL:
        tag = soup.select_one(sel)
        if tag:
            src = tag.get("data-src") or tag.get("src")
            if src:
                data["imagem"] = urljoin(final_url, src)
                logger.info(f"[EXTRACTOR][Magalu] Imagem via '{sel}'")
                break

    if not data.get("imagem"):
        data["imagem"] = _extract_generic_image(soup, final_url)

    if not data.get("preco"):
        logger.warning("[EXTRACTOR][Magalu] Preço não encontrado.")
    if not data.get("imagem"):
        logger.warning("[EXTRACTOR][Magalu] Imagem não encontrada.")

    return data


def _extract_netshoes(soup: BeautifulSoup, final_url: str) -> dict:
    data: dict = {}

    # --- PREÇO: Netshoes ---
    # Priorizar o 'best-price' e evitar 'old-price'
    PRICE_SELECTORS = [
        ".product-price__best-price", 
        "span[itemprop='price']",
        ".txt-bold.txt-large",
    ]
    for sel in PRICE_SELECTORS:
        tag = soup.select_one(sel)
        if tag:
            # Se for o preço riscado, ignora
            if "old-price" in (tag.get("class") or []):
                continue
                
            raw = tag.get("content") or tag.get_text(strip=True)
            price = clean_price(raw)
            if price:
                data["preco"] = price
                logger.info(f"[EXTRACTOR][Netshoes] Preço com desconto via '{sel}' → {price}")
                break

    # Fallback JSON-LD / OG
    if not data.get("preco"):
        data["preco"] = _extract_generic_price(soup)

    # --- PREÇO ORIGINAL (Riscado) ---
    orig_tag = soup.select_one(".product-price__old-price") or soup.select_one(".txt-old-price")
    if orig_tag:
        data["preco_original"] = clean_price(orig_tag.get_text(strip=True))
        logger.info(f"[EXTRACTOR][Netshoes] Preço original detectado: {data['preco_original']}")

    # Fallback Brutal (Regex no HTML)
    if not data.get("preco"):
        m = re.search(r'R\$\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)', soup.get_text())
        if m:
            data["preco"] = f"R$ {m.group(1)}"

    # --- IMAGEM ---
    IMGSEL = [
        ".product-image-wrapper img",
        ".swiper-slide img",
        "img[class*='product']",
        "#imgSlide img",
    ]
    for sel in IMGSEL:
        tag = soup.select_one(sel)
        if tag:
            src = tag.get("data-src") or tag.get("src")
            if src:
                data["imagem"] = urljoin(final_url, src)
                logger.info(f"[EXTRACTOR][Netshoes] Imagem via '{sel}'")
                break

    if not data.get("imagem"):
        data["imagem"] = _extract_generic_image(soup, final_url)

    if not data.get("preco"):
        logger.warning("[EXTRACTOR][Netshoes] Preço não encontrado.")
    if not data.get("imagem"):
        logger.warning("[EXTRACTOR][Netshoes] Imagem não encontrada.")

    return data


def _extract_shopee(soup: BeautifulSoup, final_url: str) -> dict:
    data: dict = {}

    # Tenta descobrir o shop_id e item_id
    # Formatos comuns: /product/123/456, ou /opaanlp/123/456, ou -i.123.456
    match = re.search(r'(?:product|opaanlp|i\.)/?(?:[^\d]*)(\d+)[/\.](\d+)', final_url)
    if match:
        shop_id = match.group(1)
        item_id = match.group(2)
        api_url = f"https://shopee.com.br/api/v4/item/get?itemid={item_id}&shopid={shop_id}"
        try:
            r = requests.get(api_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json"
            }, timeout=10)
            if r.status_code == 200:
                json_data = r.json()
                if json_data.get("data"):
                    item = json_data["data"]
                    data["nome"] = item.get("name")
                    price_min = item.get("price_min", item.get("price", 0))
                    if price_min > 0:
                        val = price_min / 100000.0
                        data["preco"] = f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                    img = item.get("image")
                    if img:
                        data["imagem"] = f"https://down-br.img.susercontent.com/file/{img}"
                    logger.info("[EXTRACTOR][Shopee] Dados extraídos via API com sucesso!")
                    return data
        except Exception as e:
            logger.warning(f"[EXTRACTOR][Shopee] Fallback de API falhou: {e}")

    # Fallback JS HTML
    html_text = str(soup)
    price_match = re.search(r'"price":(\d{3,10})', html_text)
    if not price_match:
        price_match = re.search(r'"price_min":(\d{3,10})', html_text)
    
    if price_match:
        val = int(price_match.group(1))
        if val > 100000:
            val = val / 100000.0
            data["preco"] = f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    
    # Imagem
    img_match = re.search(r'"image":\s*"([^"]+)"', html_text)
    if img_match:
        img_id = img_match.group(1)
        if len(img_id) == 32:
            data["imagem"] = f"https://down-br.img.susercontent.com/file/{img_id}"

    # Nome
    name_match = re.search(r'"name":"([^"]+)"', html_text)
    if name_match:
        data["nome"] = name_match.group(1)

    return data


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def extract_product_data(url: str) -> dict:
    """
    Extrai dados do produto da URL fornecida (deve ser a URL JÁ RESOLVIDA).

    Returns dict com:
        nome, preco, imagem, loja, descricao, product_url, store_key
    """
    store_display, store_key = detect_store(url)

    data = {
        "nome":        None,
        "preco":       None,
        "imagem":      None,
        "loja":        store_display,
        "store_key":   store_key,
        "descricao":   None,
        "product_url": url,
    }

    logger.info(
        f"[EXTRACTOR] ── Nova extração ──────────────────────────────────\n"
        f"[EXTRACTOR] Loja detectada : {store_display} (key={store_key})\n"
        f"[EXTRACTOR] URL            : {url[:100]}"
    )

    try:
        # Escolhe headers apropriados
        headers = _HEADERS_AMAZON if store_key == "amazon" else _HEADERS_GENERIC
        session = requests.Session()
        session.headers.update(headers)
        res = session.get(url, timeout=15, allow_redirects=True)
        final_url = res.url
        logger.info(f"[EXTRACTOR] URL após redirect : {final_url[:100]}")
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        # --- NOME (genérico) ---
        data["nome"] = _extract_generic_name(soup)
        # Fallback Amazon-específico
        if not data["nome"] and store_key == "amazon":
            pt = soup.select_one("#productTitle")
            if pt:
                data["nome"] = pt.get_text(strip=True)
        logger.info(f"[EXTRACTOR] Nome           : {'OK → ' + data['nome'][:50] if data['nome'] else 'FALHA'}")

        # --- DESCRIÇÃO (genérica) ---
        data["descricao"] = _extract_generic_desc(soup)

        # --- PREÇO e IMAGEM por loja ---
        store_data: dict = {}
        if store_key == "amazon":
            store_data = _extract_amazon(soup, final_url)
        elif store_key == "mercadolivre":
            store_data = _extract_mercadolivre(soup, final_url)
        elif store_key == "magalu":
            store_data = _extract_magalu(soup, final_url)
        elif store_key == "netshoes":
            store_data = _extract_netshoes(soup, final_url)
        elif store_key == "shopee":
            store_data = _extract_shopee(soup, final_url)
        else:
            # Genérico: usa JSON-LD + OG
            store_data["preco"] = _extract_generic_price(soup)
            store_data["imagem"] = _extract_generic_image(soup, final_url)

        # Aplica resultados específicos (prioridade sobre genérico)
        if store_data.get("preco"):
            price = clean_price(store_data["preco"]) or store_data["preco"]
            data["preco"] = price
        if store_data.get("preco_original"):
            orig = clean_price(store_data["preco_original"]) or store_data["preco_original"]
            data["preco_original"] = orig
        if store_data.get("imagem"):
            data["imagem"] = store_data["imagem"]
        if store_data.get("nome"):
            data["nome"] = store_data["nome"]

        # Fallback preço genérico se loja específica falhou
        if not data["preco"]:
            data["preco"] = _extract_generic_price(soup)

        # Fallback imagem genérica se loja específica falhou
        if not data["imagem"]:
            data["imagem"] = _extract_generic_image(soup, final_url)

        logger.info(
            f"[EXTRACTOR] Preço          : {'OK → ' + data['preco'] if data['preco'] else 'FALHA'}\n"
            f"[EXTRACTOR] Imagem         : {'OK' if data['imagem'] else 'FALHA'}\n"
            f"[EXTRACTOR] ────────────────────────────────────────────────"
        )

    except requests.Timeout:
        logger.error(f"[EXTRACTOR] ⏱ Timeout ao acessar: {url}")
    except requests.RequestException as e:
        logger.error(f"[EXTRACTOR] 🌐 Erro de rede: {e}")
    except Exception as e:
        logger.error(f"[EXTRACTOR] ❌ Erro inesperado: {e}", exc_info=True)

    return data
