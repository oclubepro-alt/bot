"""
product_extractor_v2.py — Extrator de produtos em camadas.

Ordem de prioridade:
  Prioridade 0 — Preço PIX/à-vista (antes de tudo)
  Camada 1 — Playwright (renderização real de JS)
  Camada 2 — requests + BeautifulSoup (fallback HTML)
  Camada 3 — Retorno seguro mínimo (nunca quebra o fluxo)

Regra de preço:
  1. Se existe preço PIX/à-vista → usa ele (is_pix_price=True)
  2. Senão: pega o MENOR entre promocional e original.
  Log obrigatório: PRECO_TIPO=PIX | PROMOCIONAL | ORIGINAL
"""
import logging
import re
import asyncio
import httpx
import json
import os
import random
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote, urljoin
from bot.utils.config import SCRAPERAPI_KEY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Contrato de saída — garante que o dict retornado NUNCA tem chaves ausentes
# Qualquer código que consuma extract_product_data_v2 pode usar .get() com
# segurança, mas esta função elimina KeyError mesmo com acesso direto.
# ---------------------------------------------------------------------------
_RESULT_SCHEMA: dict = {
    "store":          "Loja",
    "store_key":      "other",
    "final_url":      "",
    "titulo":         "Produto Disponível",
    "imagem":         None,
    "preco":          "Preço não disponível",
    "preco_original": None,
    "source_method":  "UNKNOWN",
    "is_pix_price":   False,
    "cupom":          None,
}


def _validate_result(result: dict) -> dict:
    """
    Garante que o dict de saída do pipeline sempre contém todas as chaves
    definidas em _RESULT_SCHEMA com tipos corretos.

    Regras:
      - Chaves ausentes recebem o valor padrão do schema.
      - 'preco' None ou vazio vira 'Preço não disponível'.
      - 'titulo' None ou vazio vira 'Produto Disponível'.
      - 'is_pix_price' é sempre bool.
      - 'final_url' vazio herda o valor de entrada se disponível.
    """
    for key, default in _RESULT_SCHEMA.items():
        if key not in result or result[key] is None and default is not None:
            result.setdefault(key, default)

    # Garante strings não-vazias nas chaves críticas
    if not result.get("preco"):
        result["preco"] = "Preço não disponível"
    if not result.get("titulo"):
        result["titulo"] = "Produto Disponível"

    # Garante tipo bool
    result["is_pix_price"] = bool(result.get("is_pix_price", False))

    return result

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
}

_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
}

_BLOCK_KEYWORDS = ["captcha", "blocked", "bot manager", "perfdrive", "shieldsquare", 
                  "acesso negado", "access denied", "validate.perfdrive.com",
                  "type the characters you see in this image", "robot", "human verification"]

_TIMEOUT_HTTP = 15
_TIMEOUT_PLAYWRIGHT = 45
_TIMEOUT_SCRAPERAPI = 60


# ---------------------------------------------------------------------------
# Camada 0: API Interna da Magalu — cascata de 3 endpoints
# ---------------------------------------------------------------------------

async def fetch_magalu_api(url: str) -> dict | None:
    """
    Tenta extrair dados da Magalu sem scraping, via 3 endpoints em cascata:
      1. API catalog interna (usada pelo app mobile)
      2. API de detalhes de produto (endpoint alternativo)
      3. Fetch leve do JSON-LD da página do produto
    Retorna None se todos falharem → pipeline cai para Camada 1 (ScraperAPI).
    """
    # Extrai o ID do produto da URL — padrão: /p/XXXXXXXX/
    match = re.search(r'/p/(\w+)/?', url)
    if not match:
        logger.warning("[MAGALU_API] ⚠️ ID do produto não encontrado na URL")
        return None

    product_id = match.group(1)
    logger.info(f"[MAGALU_API] ℹ️ Produto ID extraído: {product_id}")

    headers_json = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.magazineluiza.com.br/",
        "Origin": "https://www.magazineluiza.com.br",
        "x-requested-with": "com.magalu.magaluapp",
    }

    _ENDPOINTS_MAGALU = [
        # Endpoint 1: API catalog mobile (mais recente)
        f"https://ms.catalog.magazineluiza.com.br/api/v1/products/{product_id}",
        # Endpoint 2: API legada usada pelo site
        f"https://www.magazineluiza.com.br/api/v1/product/{product_id}/",
        # Endpoint 3: API de busca por código
        f"https://www.magazineluiza.com.br/api/v1/search/?q={product_id}&limit=1",
    ]

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS_MAGALU:
            try:
                logger.info(f"[MAGALU_API] ℹ️ Tentando: {endpoint}")
                resp = await client.get(endpoint, headers=headers_json)
                logger.info(f"[MAGALU_API] ℹ️ Status: {resp.status_code} | Endpoint: {endpoint}")

                if resp.status_code != 200:
                    continue

                # Verifica se retornou JSON válido
                ct = resp.headers.get("content-type", "")
                if "json" not in ct:
                    logger.warning(f"[MAGALU_API] ⚠️ Resposta não é JSON: {ct}")
                    continue

                data = resp.json()

                # --- Mapeamento Endpoint 1/2 (produto direto) ---
                titulo = (
                    data.get("title")
                    or data.get("name")
                    or data.get("product", {}).get("title")
                )
                imagem = (
                    data.get("image")
                    or data.get("thumbnail")
                    or data.get("product", {}).get("image")
                )
                price_obj = data.get("price") or data.get("product", {}).get("price") or {}
                best_price = (
                    price_obj.get("best_price")
                    or price_obj.get("sale_price")
                    or price_obj.get("price")
                    or data.get("price_in_cash")
                )
                orig_price = price_obj.get("original_price") or price_obj.get("list_price")

                # --- Mapeamento Endpoint 3 (busca) ---
                if not titulo and isinstance(data.get("result"), list) and data["result"]:
                    item = data["result"][0]
                    titulo = item.get("title") or item.get("name")
                    imagem = item.get("image") or item.get("thumbnail")
                    p = item.get("price") or {}
                    best_price = p.get("best_price") or p.get("sale_price") or item.get("price_in_cash")
                    orig_price = p.get("original_price")

                if titulo and best_price:
                    logger.info(f"[MAGALU_API] ✅ Sucesso | Título: {titulo[:50]} | Preço: {best_price}")
                    return {
                        "titulo": titulo,
                        "imagem": imagem,
                        "preco": _clean_price(str(best_price)),
                        "preco_original": _clean_price(str(orig_price)) if orig_price else None,
                        "source_method": "MAGALU_API_INTERNA",
                        "is_pix_price": True,
                    }
                else:
                    logger.warning(f"[MAGALU_API] ⚠️ Dados incompletos neste endpoint (título={titulo}, preço={best_price})")

            except Exception as e:
                logger.warning(f"[MAGALU_API] ❌ Exceção no endpoint {endpoint}: {str(e)[:80]}")
                continue

    # --- Fallback Camada 0b: JSON-LD leve da página ---
    try:
        logger.info("[MAGALU_API] ℹ️ Tentando JSON-LD leve da página...")
        headers_html = {
            "User-Agent": _HEADERS["User-Agent"],
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers_html)
            if resp.status_code == 200 and "radware" not in resp.text.lower():
                soup = BeautifulSoup(resp.text, "html.parser")
                preco_schema = _extract_price_from_schema(soup)
                titulo_tag = soup.select_one("h1[itemprop='name'], h1.header-product__title, h1")
                titulo_schema = titulo_tag.get_text(strip=True)[:80] if titulo_tag else None
                meta_img = soup.find("meta", attrs={"property": "og:image"})
                imagem_schema = meta_img["content"] if meta_img and meta_img.get("content") else None

                if titulo_schema and preco_schema:
                    logger.info(f"[MAGALU_API] ✅ JSON-LD/HTML leve OK | {titulo_schema[:40]}")
                    return {
                        "titulo": titulo_schema,
                        "imagem": imagem_schema,
                        "preco": preco_schema,
                        "preco_original": None,
                        "source_method": "MAGALU_HTML_LEVE",
                        "is_pix_price": False,
                    }
    except Exception as e:
        logger.warning(f"[MAGALU_API] ⚠️ JSON-LD leve falhou: {str(e)[:80]}")

    logger.warning("[MAGALU_API] ❌ Todos os endpoints falharam → caindo para Camada 1")
    return None


# ---------------------------------------------------------------------------
# Camada 0: API Interna da Netshoes — extração por SKU
# ---------------------------------------------------------------------------

async def fetch_netshoes_api(url: str) -> dict | None:
    """
    Extrai dados da Netshoes sem scraping usando a API interna por SKU.
    Padrão de URL: /nome-do-produto/NKB-4396-001-M (SKU é o último segmento)
    Tenta 2 endpoints em cascata + fallback HTML leve.
    """
    # Extrai SKU do último segmento da URL
    path = urlparse(url).path.rstrip("/")
    sku_match = re.search(r'/([A-Z0-9]{2,6}-[\w-]{4,30})$', path)
    if not sku_match:
        logger.warning("[NETSHOES_API] ⚠️ SKU não encontrado na URL")
        return None

    sku = sku_match.group(1)
    logger.info(f"[NETSHOES_API] ℹ️ SKU extraído: {sku}")

    headers_json = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Referer": "https://www.netshoes.com.br/",
    }

    _ENDPOINTS_NETSHOES = [
        # Endpoint 1: API de produto por SKU (app mobile)
        f"https://api.netshoes.com.br/v1/products/{sku}",
        # Endpoint 2: API catalog
        f"https://www.netshoes.com.br/api/catalog/product/{sku}",
    ]

    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        for endpoint in _ENDPOINTS_NETSHOES:
            try:
                logger.info(f"[NETSHOES_API] ℹ️ Tentando: {endpoint}")
                resp = await client.get(endpoint, headers=headers_json)
                logger.info(f"[NETSHOES_API] ℹ️ Status: {resp.status_code}")

                if resp.status_code != 200:
                    continue
                ct = resp.headers.get("content-type", "")
                if "json" not in ct:
                    continue

                data = resp.json()

                titulo = (
                    data.get("name")
                    or data.get("title")
                    or data.get("product", {}).get("name")
                )
                imagem = (
                    data.get("image")
                    or data.get("thumbnail")
                    or data.get("images", [{}])[0].get("url")
                )
                price_obj = data.get("price") or data.get("pricing") or {}
                best_price = (
                    price_obj.get("sale_price")
                    or price_obj.get("best_price")
                    or price_obj.get("price")
                    or data.get("finalPrice")
                )
                orig_price = price_obj.get("list_price") or price_obj.get("original_price")

                if titulo and best_price:
                    logger.info(f"[NETSHOES_API] ✅ Sucesso | {titulo[:50]} | Preço: {best_price}")
                    return {
                        "titulo": titulo,
                        "imagem": imagem,
                        "preco": _clean_price(str(best_price)),
                        "preco_original": _clean_price(str(orig_price)) if orig_price else None,
                        "source_method": "NETSHOES_API_INTERNA",
                        "is_pix_price": False,
                    }
                else:
                    logger.warning(f"[NETSHOES_API] ⚠️ Dados incompletos neste endpoint")

            except Exception as e:
                logger.warning(f"[NETSHOES_API] ❌ Exceção: {str(e)[:80]}")
                continue

    # --- Fallback Camada 0b: HTML leve + JSON-LD ---
    try:
        logger.info("[NETSHOES_API] ℹ️ Tentando HTML leve + JSON-LD...")
        headers_html = {
            "User-Agent": _HEADERS["User-Agent"],
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        }
        async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers_html)
            if resp.status_code == 200 and "radware" not in resp.text.lower() and "blocked" not in resp.text.lower():
                soup = BeautifulSoup(resp.text, "html.parser")
                preco_schema = _extract_price_from_schema(soup) or _extract_price_netshoes(soup)[0]
                titulo_tag = soup.select_one(".header-product__title, h1")
                titulo_schema = titulo_tag.get_text(strip=True)[:80] if titulo_tag else None
                meta_img = soup.find("meta", attrs={"property": "og:image"})
                imagem_schema = meta_img["content"] if meta_img and meta_img.get("content") else None

                if titulo_schema and preco_schema:
                    logger.info(f"[NETSHOES_API] ✅ HTML leve OK | {titulo_schema[:40]}")
                    return {
                        "titulo": titulo_schema,
                        "imagem": imagem_schema,
                        "preco": preco_schema,
                        "preco_original": None,
                        "source_method": "NETSHOES_HTML_LEVE",
                        "is_pix_price": False,
                    }
    except Exception as e:
        logger.warning(f"[NETSHOES_API] ⚠️ HTML leve falhou: {str(e)[:80]}")

    logger.warning("[NETSHOES_API] ❌ Todos os endpoints falharam → caindo para Camada 1")
    return None


# ---------------------------------------------------------------------------
# Helpers de preço
# ---------------------------------------------------------------------------

def _parse_price_to_float(text: str) -> float | None:
    """Converte 'R$ 1.299,90' ou 'R\u00a0189,90' ou '399.00' → float."""
    if not text:
        return None
    # Normaliza: remove espaço não-quebrável (\xa0) e parenteséticos
    text = str(text).replace('\u00a0', ' ').replace('\xa0', ' ')
    text = re.sub(r"\(.*?\)", "", text)
    cleaned = re.sub(r"[^\d,.]", "", text)
    if not cleaned:
        return None

    if "," in cleaned:
        # Padrão BR: 1.299,90 -> 1299.90
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        # Padrão Internacional ou BR sem decimal: 399.00 ou 1.200
        # Se houver apenas um ponto e ele estiver na posição de centavos (2 antes do fim),
        # e não for um número gigante, tratamos como decimal (comum em JSON-LD).
        parts = cleaned.split('.')
        if len(parts) == 2 and len(parts[1]) == 2:
            # Caso 399.00 -> mantém o ponto como decimal
            pass
        else:
            # Caso 1.200 -> remove o ponto (divisor de milhar)
            cleaned = cleaned.replace(".", "")
            
    try:
        val = float(cleaned)
        # Sanidade mínima: preços absurdos > 500k em itens comuns costumam ser erro de parsing
        # (A menos que seja um carro ou imóvel, mas pro bot de achadinhos 500k é safe limit)
        if val > 500000: return None
        return val
    except Exception:
        return None


def _clean_price(raw: str) -> str | None:
    """Normaliza preço para exibição: R$ 1.299,90"""
    if not raw:
        return None
    val = _parse_price_to_float(raw)
    if val is None:
        return None
    # Re-formata no padrão BR
    reais = int(val)
    centavos = round((val - reais) * 100)
    reais_fmt = f"{reais:,}".replace(",", ".")
    return f"R$ {reais_fmt},{centavos:02d}"


def _choose_lower_price(p1: str | None, p2: str | None) -> tuple[str | None, str | None]:
    """
    Retorna (preco_promocional, preco_original).
    Sempre coloca o MENOR como promocional.
    """
    v1 = _parse_price_to_float(p1) if p1 else None
    v2 = _parse_price_to_float(p2) if p2 else None

    if v1 is None and v2 is None:
        return None, None
    if v1 is None:
        return _clean_price(p2), None
    if v2 is None:
        return _clean_price(p1), None

    if v1 <= v2:
        return _clean_price(p1), _clean_price(p2)
    else:
        return _clean_price(p2), _clean_price(p1)


# ---------------------------------------------------------------------------
# Prioridade 0: Preço PIX / à vista — buscado ANTES dos seletores padrão
# ---------------------------------------------------------------------------

_PIX_PATTERN = re.compile(r'pix|à\s*vista', re.IGNORECASE)


def _find_price_near_text(soup: BeautifulSoup, text_pattern, price_selectors: list[str]) -> str | None:
    """
    Procura pelo texto que casa com text_pattern e tenta encontrar
    um preço nos elementos vizinhos (subindo até 6 níveis na árvore).
    Retorna o primeiro valor numérico válido encontrado.
    """
    for text_node in soup.find_all(string=text_pattern):
        parent = text_node.parent
        for _ in range(6):
            if parent is None:
                break
            for sel in price_selectors:
                tag = parent.select_one(sel)
                if tag:
                    val = tag.get_text(strip=True)
                    if _parse_price_to_float(val):
                        return val
            parent = parent.parent
    return None


def _extract_pix_price_amazon(soup: BeautifulSoup) -> str | None:
    """Amazon: busca preço 'no Pix' / 'à vista no Pix'."""
    price_selectors = [
        ".a-price .a-offscreen",
        ".a-price-whole",
        ".a-price .a-price-whole",
    ]
    val = _find_price_near_text(soup, _PIX_PATTERN, price_selectors)
    if val:
        logger.info(f"[EXTRACTOR_V2] Amazon PIX price encontrado: {val}")
        return _clean_price(val)
    return None


def _extract_pix_price_ml(soup: BeautifulSoup) -> str | None:
    """Mercado Livre: busca preço 'no Pix' na seção de desconto Pix."""
    # Tenta primeiro via seletor específico de desconto Pix
    pix_section = soup.select_one(".ui-pdp-price--pix, [data-testid='pix-price']")
    if pix_section:
        frac = pix_section.select_one(".andes-money-amount__fraction")
        if frac:
            val = frac.get_text(strip=True)
            cents = pix_section.select_one(".andes-money-amount__cents")
            if cents:
                val += f",{cents.get_text(strip=True)}"
            if _parse_price_to_float(val):
                logger.info(f"[EXTRACTOR_V2] ML PIX price (seletor direto): {val}")
                return _clean_price(val)
    return None


def _extract_price_from_schema(soup: BeautifulSoup) -> str | None:
    """Busca universal de preço usando JSON-LD Schema.org (Agressivo)."""
    scripts = soup.find_all('script', type='application/ld+json')
    for s in scripts:
        if not s.string: continue
        try:
            data = json.loads(s.string)
            if not isinstance(data, dict): continue
            
            # Normaliza para lista (mesmo se for um objeto só ou @graph)
            items = data.get('@graph', [data])
            if not isinstance(items, list): items = [items]
            
            for item in items:
                # Procura por Product ou MainEntity (comum na Magalu/Netshoes)
                if item.get('@type') in ('Product', 'ProductCollection'):
                    offers = item.get('offers')
                    if not offers: continue
                    
                    if isinstance(offers, dict):
                        # Padrão simples
                        p = offers.get('price') or offers.get('lowPrice')
                        if p: return _clean_price(str(p))
                    elif isinstance(offers, list):
                        # Lista de ofertas
                        for off in offers:
                            p = off.get('price')
                            if p: return _clean_price(str(p))
                            
                # Fallback: qualquer coisa que pareça uma oferta solta
                if item.get('@type') == 'Offer':
                    p = item.get('price')
                    if p: return _clean_price(str(p))
        except Exception:
            pass
    return None


def _extract_price_from_body_regex(soup: BeautifulSoup) -> str | None:
    """
    ULTIMATO: Busca qualquer padrão de R$ no corpo da página.
    Ideal para quando a Amazon bloqueia seletores mas deixa o texto.
    """
    text = soup.get_text()
    # Padrão: R$ seguido de números, pontos e vírgulas
    matches = re.findall(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text)
    if matches:
        # Pega o primeiro que não seja 0,00
        for m in matches:
            if m != "0,00":
                logger.info(f"[EXTRACTOR_V2] Preço minerado via Regex Body: R$ {m}")
                return f"R$ {m}"
    return None


def _extract_pix_price_magalu(soup: BeautifulSoup) -> str | None:
    """Magalu: busca preço 'no Pix' próximo ao label PIX."""
    price_selectors = [
        "[data-testid='price-value']",
        ".sc-kLojnp",
    ]
    val = _find_price_near_text(soup, _PIX_PATTERN, price_selectors)
    if val:
        logger.info(f"[EXTRACTOR_V2] Magalu PIX price encontrado: {val}")
        return _clean_price(val)
    return None


# ---------------------------------------------------------------------------
# Extração de preço por loja — seletores com prioridade por tipo
# ---------------------------------------------------------------------------

def _is_valid_price_tag(tag) -> bool:
    """Verifica se a tag não pertence a um preço unitário ou a um preço riscado/tachado."""
    if not tag: return False

    # Verifica se a própria tag ou um pai imediato tem classe de preço tachado (a-text-price)
    # Isso exclui o preço original que aparece riscado antes do preço real
    tag_classes = set(tag.get("class") or [])
    parent = tag.parent
    parent_classes = set(parent.get("class") or []) if parent else set()
    grandparent = parent.parent if parent else None
    grandparent_classes = set(grandparent.get("class") or []) if grandparent else set()

    # Exclui se está dentro de elemento de preço riscado (mas só nas baixas-confiança)
    # Nota: a-text-price é o container do preço original na Amazon
    if "a-text-price" in parent_classes or "a-text-price" in grandparent_classes:
        # Permite apenas se também tiver 'priceToPay' no contexto (é o preço real)
        has_price_to_pay = (
            "priceToPay" in parent_classes or
            "priceToPay" in grandparent_classes or
            (grandparent and grandparent.parent and 
             "priceToPay" in set(grandparent.parent.get("class") or []))
        )
        if not has_price_to_pay:
            return False

    # Sobe até 5 níveis para buscar contexto de 'unidade'
    text_context = tag.get_text(strip=True).lower()
    p = tag.parent
    for _ in range(5):
        if p is None: break
        # Coleta só o texto direto (não o texto de todos os filhos)
        direct_text = " ".join(t for t in p.strings if t.strip()).lower()
        text_context += " " + direct_text
        p = p.parent
    
    # Palavras-chave que indicam preço unitário (Amazon / ML / Magalu)
    unit_keywords = [
        "/ unidade", "/unidade", "por unidade", "/ unit",
        "por ml", "por kg", "por g ", "por metro", "/m ", " cada",
        "preço por", "valor por", " unid", "(unid", "por litro", "por l "
    ]
    return not any(k in text_context for k in unit_keywords)


def _extract_price_amazon(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """
    Amazon: Extração robusta combinando JSON-LD, scripts internos e seletores.
    Prioriza dados estruturados (JSON) antes de seletores CSS voláteis.
    """
    preco_promo = None
    preco_orig  = None

    # 1. TENTA EXTRAIR VIA SCRIPTS DE ESTADO (JSON INTERNO)
    # Amazon costuma colocar os dados de oferta em scripts 'text/a-state' ou 'application/ld+json'
    scripts = soup.find_all("script")
    for script in scripts:
        try:
            content = script.string or ""
            if not content: continue
            
            # Padrão 1: JSON-LD (Standard)
            if script.get("type") == "application/ld+json":
                data = json.loads(content)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if item.get("@type") == "Product":
                        offers = item.get("offers", {})
                        if isinstance(offers, dict):
                            p = offers.get("price")
                            if p and _parse_price_to_float(str(p)):
                                preco_promo = str(p)
                                # Preço original no JSON-LD às vezes não existe ou está em highPrice
                                break
            
            # Padrão 2: Amazon a-state (Data do BuyBox)
            # Usa regex não-greedy e com limite de tamanho para evitar JSON corrompido
            if "desktop-dp-price-detail" in content or ("Offers" in content and "DisplayAmount" in content):
                # Regex não-greedy com lookahead para JSON bem-formado
                for m in re.finditer(r'(\{[^{]{0,5000}"Offers"[^}]{0,5000}\})', content):
                    try:
                        data = json.loads(m.group(1))
                        p, o = _parse_amazon_paapi_dict(data)
                        if p:
                            logger.info(f"[EXTRACTOR_V2] Amazon preço via JSON a-state: {p}")
                            preco_promo = p
                            if o: preco_orig = o
                            break
                    except Exception:
                        continue
                if preco_promo: break
        except Exception:
            continue
        if preco_promo: break

    # 2. SELETORES CSS (FALLBACK SE O JSON FALHAR)
    # ORDEM IMPORTA: seletores mais específicos (buybox) antes dos genéricos
    if not preco_promo:
        promo_selectors = [
            # Seletores de alta confiança (buybox principal)
            ".a-price.priceToPay .a-offscreen",
            "#corePrice_feature_div .priceToPay .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
            "#priceblock_dealprice",
            "#priceblock_ourprice",
            "#price_inside_buybox",
            # Seletores de média confiança (podem pegar preço riscado se .priceToPay falhar)
            "#corePrice_feature_div .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            # Fallback genérico (baixa confiança — só se tudo acima falhar)
            "#corePrice_feature_div .a-price-whole",
        ]
        for sel in promo_selectors:
            for tag in soup.select(sel):
                if not _is_valid_price_tag(tag): continue
                val = tag.get_text(strip=True)
                
                # Recompõe centavos se pegou só a parte inteira
                if "a-price-whole" in sel:
                    parent = tag.parent
                    fraction = parent.select_one(".a-price-fraction") if parent else None
                    if fraction:
                        val = f"{val.replace(',', '').replace('.', '')},{fraction.get_text(strip=True)}"
                
                if _parse_price_to_float(val):
                    preco_promo = val
                    logger.info(f"[EXTRACTOR_V2] Amazon preço promo via '{sel}': {preco_promo}")
                    break
            if preco_promo: break

    # 3. PREÇO ORIGINAL (Riscado)
    if not preco_orig:
        orig_selectors = [
            ".a-text-price .a-offscreen", 
            "#listPrice", 
            ".basisPrice .a-offscreen",
            "#priceBlockStrikePriceString",
            ".a-price.a-text-price span.a-offscreen"
        ]
        for sel in orig_selectors:
            for tag in soup.select(sel):
                if _is_valid_price_tag(tag):
                    val = tag.get_text(strip=True)
                    if _parse_price_to_float(val):
                        preco_orig = val
                        break
            if preco_orig: break

    return _choose_lower_price(preco_promo, preco_orig)


def _extract_coupon_amazon(soup: BeautifulSoup) -> str | None:
    """
    Detecta cupons de desconto na página da Amazon.
    Ex: 'Aplique o cupom de R$ 50,00', 'Economize 10% com cupom'.
    """
    coupon_selectors = [
        "#shoveler-coupon-text",
        ".cpn-btm-msg",
        ".ux-coupon-text",
        ".vpc-coupon-label",
        "#vcp-coupon-text",
        ".a-size-base.a-color-success" # Às vezes cupons simples aparecem aqui
    ]
    for sel in coupon_selectors:
        tag = soup.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if "cupom" in text.lower() or "coupon" in text.lower() or "economize" in text.lower():
                # Limpa excesso de espaços e retorna
                return re.sub(r"\s+", " ", text).strip()
                
    # Busca por texto direto se o seletor falhar
    for tag in soup.find_all(string=re.compile(r"cupom", re.I)):
        parent = tag.parent
        if parent and "economize" in parent.get_text().lower():
            return parent.get_text(strip=True)

    return None


def _parse_amazon_paapi_dict(item: dict) -> tuple[str | None, str | None]:
    """
    Processa um dicionário no formato Amazon PA-API v5 ou similar (a-state).
    Lógica baseada na sugestão do usuário.
    """
    try:
        # Suporte a múltiplos níveis de aninhamento comuns em a-state
        offers = item.get("Offers") or item.get("offers")
        if not offers and "desktop-dp-price-detail" in item:
            offers = item["desktop-dp-price-detail"].get("Offers")
        
        if not offers:
            # Tenta busca recursiva simples por 'Listings'
            if "Listings" in str(item):
                pass # Poderia implementar, mas vamos focar no óbvio primeiro
            else:
                return None, None

        listings = (offers.get("Listings") or []) or offers.get("listings") or []
        if not listings:
            return None, None

        listing = listings[0]
        
        # Preço Atual (Price)
        price_obj = listing.get("Price") or listing.get("price") or {}
        p_promo = price_obj.get("DisplayAmount") or price_obj.get("Amount")

        # Preço Original (SavingBasis)
        saving_obj = listing.get("SavingBasis") or listing.get("savingBasis") or {}
        p_orig = saving_obj.get("DisplayAmount") or saving_obj.get("Amount")

        # Fallback se DisplayAmount vier vazio mas Amount tiver número
        if p_promo and not isinstance(p_promo, str): p_promo = str(p_promo)
        if p_orig and not isinstance(p_orig, str): p_orig = str(p_orig)

        return p_promo, p_orig
    except Exception as e:
        logger.debug(f"[AMAZON_JSON] Erro no parse PA-API: {e}")
        return None, None


def _extract_price_ml(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Mercado Livre: usar .andes-money-amount--cents-superscript, nunca --previous."""
    preco_promo = None
    preco_orig  = None

    # Preço promocional
    promo_selectors = [
        ".ui-pdp-price__second-line .andes-money-amount__fraction",
        ".andes-money-amount--main .andes-money-amount__fraction",
        ".ui-pdp-price .andes-money-amount__fraction",
        ".andes-money-amount__fraction", # Genérico como última opção
    ]
    for sel in promo_selectors:
        # Pega todas as tags e filtra explicitly as que são "previous" (riscadas)
        for tag in soup.select(sel):
            parent_container = tag.find_parent(class_=re.compile(r"andes-money-amount"))
            if parent_container and "andes-money-amount--previous" in parent_container.get("class", []):
                continue # Pula preço riscado
            
            val = tag.get_text(strip=True)
            parent = tag.parent
            cents = parent.select_one(".andes-money-amount__cents") if parent else None
            if cents:
                val += f",{cents.get_text(strip=True)}"
            
            if _parse_price_to_float(val):
                preco_promo = val
                logger.info(f"[EXTRACTOR_V2] ML preço promo via '{sel}': {preco_promo}")
                break
        if preco_promo:
            break

    # Preço original riscado — seletor da classe "previous"
    orig_tag = soup.select_one(".andes-money-amount--previous .andes-money-amount__fraction")
    if orig_tag:
        preco_orig = orig_tag.get_text(strip=True)

    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_magalu(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Magalu: pegar preço do [data-testid='price-value'], ignorar 'no-price-value'."""
    preco_promo = None
    preco_orig  = None

    promo_tag = soup.select_one("[data-testid='price-value'], .sc-kLojnp")
    if promo_tag:
        preco_promo = promo_tag.get_text(strip=True)

    orig_tag = soup.select_one("[data-testid='no-price-value'], .sc-jJoQJp")
    if orig_tag:
        preco_orig = orig_tag.get_text(strip=True)

    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_netshoes(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Netshoes: .product-final-price é o promo, .old-price é o original."""
    promo_tag = soup.select_one(".product-final-price, .best-price")
    orig_tag  = soup.select_one(".old-price")
    preco_promo = promo_tag.get_text(strip=True) if promo_tag else None
    preco_orig  = orig_tag.get_text(strip=True)  if orig_tag  else None
    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_generic(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Genérico: meta tags de preço de venda têm prioridade."""
    preco_promo = None
    preco_orig  = None

    # 1. Meta sale_price → promo; price:amount → original ou fallback
    sale_meta = soup.find("meta", attrs={"property": "product:sale_price:amount"})
    price_meta = soup.find("meta", attrs={"property": "product:price:amount"})

    if sale_meta and sale_meta.get("content"):
        preco_promo = sale_meta["content"]
    if price_meta and price_meta.get("content"):
        candidate = price_meta["content"]
        if preco_promo:
            preco_orig = candidate
        else:
            preco_promo = candidate

    if preco_promo:
        logger.info(f"[EXTRACTOR_V2] Preço via meta tag: promo={preco_promo}, orig={preco_orig}")
        return _choose_lower_price(preco_promo, preco_orig)

    # 2. JSON-LD
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
                        logger.info(f"[EXTRACTOR_V2] Preço via JSON-LD: {price}")
                        return _clean_price(str(price)), None
        except Exception:
            continue

    # 3. Regex bruto no HTML
    match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", str(soup))
    if match:
        val = f"R$ {match.group(1)}"
        logger.info(f"[EXTRACTOR_V2] Preço via regex bruto: {val}")
        return val, None

    return None, None


# ---------------------------------------------------------------------------
# Extração completa da página
# ---------------------------------------------------------------------------

def _extract_from_soup(soup: BeautifulSoup, base_url: str, store_key: str = "other") -> dict:
    """Extrai título, preço promocional, preço original, imagem, cupom e flag PIX."""
    data = {"titulo": None, "preco": None, "preco_original": None, "imagem": None, "is_pix_price": False, "cupom": None}

    # ── DETECÇÃO DE BLOQUEIO ────────────────────────────────────────────────
    page_text_lower = soup.get_text().lower()
    page_title_lower = (soup.title.string.lower() if soup.title else "")
    
    if any(p in page_title_lower for p in _BLOCK_KEYWORDS) or \
       any(p in page_text_lower for p in ["radware bot manager", "please verify you are a human"]):
        logger.warning(f"[EXTRACTOR_V2] Bloqueio detectado no HTML: {page_title_lower}")
        return {
            "titulo": f"BLOQUEIO: {page_title_lower or 'Acesso Negado'}",
            "preco": "Erro: Captcha/Block",
            "imagem": None,
            "source_method": "BLOCKED"
        }

    # ── TÍTULO ──────────────────────────────────────────────────────────────
    title_selectors = [
        "#productTitle",             # Amazon
        ".ui-pdp-title",             # Mercado Livre
        "h1[itemprop='name']",       # Magalu / genérico
        ".header-product__title",    # Netshoes
        "h1.product-name", "h1",
    ]
    for sel in title_selectors:
        tag = soup.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if len(text) > 10:
                raw = re.sub(r"^(Amazon\.com\.br|Mercado Livre|Magalu|Magazine Luiza)\s*[:\-]\s*", "", text, flags=re.I)
                raw = re.sub(r"\s*[|–\-]\s*(Amazon|Mercado Livre|Magalu|Magazine Luiza|Shopee).*", "", raw, flags=re.I)
                data["titulo"] = raw.strip()
                break

    # Fallback título via Meta
    if not data["titulo"]:
        for attr_name, attr_val in [("property", "og:title"), ("name", "twitter:title"), ("name", "title")]:
            meta = soup.find("meta", attrs={attr_name: attr_val})
            if meta and meta.get("content"):
                data["titulo"] = meta["content"].strip()
                break

    # ── PREÇO PRIORIDADE 0: PIX / à vista (Magalu, ML) ─────────────────────
    pix_price = None
    if store_key == "mercadolivre":
        pix_price = _extract_pix_price_ml(soup)
    elif store_key == "magalu":
        pix_price = _extract_pix_price_magalu(soup)
    elif store_key == "amazon":
        pix_price = _extract_pix_price_amazon(soup) # Amazon PIX fallback

    if pix_price:
        data["preco"] = pix_price
        data["is_pix_price"] = True
        # Ainda busca original para contexto
        if store_key == "mercadolivre": _, preco_orig = _extract_price_ml(soup)
        elif store_key == "magalu": _, preco_orig = _extract_price_magalu(soup)
        else: preco_orig = None
        data["preco_original"] = preco_orig
    else:
        # ── PREÇO PADRÃO POR LOJA ──────────────────────────────────────────
        if store_key == "amazon":
            # Amazon: .a-price .a-offscreen (menor valor)
            preco, preco_orig = _extract_price_amazon(soup)
        elif store_key == "mercadolivre":
            preco, preco_orig = _extract_price_ml(soup)
        elif store_key == "magalu":
            preco, preco_orig = _extract_price_magalu(soup)
        elif store_key == "netshoes":
            # Netshoes: .product-final-price
            preco, preco_orig = _extract_price_netshoes(soup)
        else:
            preco, preco_orig = _extract_price_generic(soup)

        data["preco"] = preco
        data["preco_original"] = preco_orig

    # ── CUPOM (Amazon) ──────────────────────────────────────────────────────
    if store_key == "amazon":
        data["cupom"] = _extract_coupon_amazon(soup)

    # ── ULTIMATO DE PREÇO (Schema / Regex) ───────────────────────────────
    if not data["preco"]:
        data["preco"] = _extract_price_from_schema(soup) or _extract_price_from_body_regex(soup)

    # ── IMAGEM ──────────────────────────────────────────────────────────────
    # Prioridade meta og:image como solicitado
    for og_prop in ["og:image", "twitter:image"]:
        meta = soup.find("meta", attrs={"property": og_prop}) or soup.find("meta", attrs={"name": og_prop})
        if meta and meta.get("content"):
            data["imagem"] = meta["content"]
            break

    if not data["imagem"]:
        img_tag = soup.select_one(".ui-pdp-gallery__figure__image, #imgBlkFront, #landingImage")
        if img_tag:
            src = img_tag.get("src") or img_tag.get("data-src")
            if src: data["imagem"] = urljoin(base_url, src)

    return data


async def get_page_html(url: str) -> tuple[str | None, str]:
    """
    Pipeline Híbrido de Extração (V5 Hardened):
    1. ScraperAPI (Premium + Browser Render)
    2. Playwright Local (Anti-Detecção)
    3. Requests Simples (Fallback)
    """
    # [DEBUG] Diagnóstico de Bypass
    if not SCRAPERAPI_KEY:
        logger.info("[EXTRATOR V5] ℹ️ SCRAPERAPI_KEY ausente. Camada de bypass premium desativada.")
    else:
        logger.info("[EXTRATOR V5] ✅ SCRAPERAPI_KEY detectada. Iniciando Camada 1.")


    # ── TENTATIVA 1: ScraperAPI ───────────────────────────────────────────
    if SCRAPERAPI_KEY:
        try:
            logger.info(f"[EXTRACTOR_V2] Camada 1: ScraperAPI | url={url[:60]}")
            
            is_amazon = "amazon" in url.lower() or "amzn.to" in url.lower()
            is_magalu = "magazineluiza" in url.lower() or "magalu" in url.lower()
            is_shopee = "shopee" in url.lower()
            is_netshoes = "netshoes" in url.lower()
            
            payload = {
                'api_key': SCRAPERAPI_KEY,
                'url': url,
                'render': 'true',        # JS rendering obrigatório
                'country_code': 'br',    # IP brasileiro obrigatório
                'device_type': 'desktop' # Magalu bloqueia mobile frequentemente
            }

            # Magalu e Netshoes exigem ultra_premium
            if is_magalu or is_netshoes:
                payload['ultra_premium'] = 'true'
                logger.info("[SCRAPERAPI] ⚡ Usando ultra_premium para domínio protegido")
            
            # Amazon exige premium
            elif is_amazon:
                payload['premium'] = 'true'
            
            # Shopee precisa de sessão mantida
            if is_shopee:
                payload['keep_headers'] = 'true'

            async with httpx.AsyncClient(timeout=_TIMEOUT_SCRAPERAPI) as client:
                resp = await client.get('http://api.scraperapi.com', params=payload)
                
                if resp.status_code == 200:
                    html = resp.text
                    html_lower = html.lower()
                    
                    # Detectar CAPTCHA/Bloqueio no conteúdo (Radware, etc)
                    bloqueios = ["radware", "captcha", "robot", "blocked", "access denied", "unusual traffic", "verify you are human"]
                    found_block = None
                    for termo in bloqueios:
                        if termo in html_lower:
                            found_block = termo
                            break
                    
                    if not found_block:
                        logger.info(f"[SCRAPERAPI] ✅ Sucesso ({len(html)} chars)")
                        return html, "SCRAPERAPI"
                    else:
                        logger.warning(f"[SCRAPERAPI] ❌ BLOQUEIO DETECTADO: '{found_block}' — indo para Playwright")
                else:
                    logger.warning(f"[SCRAPERAPI] ❌ Falhou com status {resp.status_code}: {resp.text[:200]}")
                    if resp.status_code in [403, 500]:
                        logger.warning("[SCRAPERAPI] ⚠️ Plano pode precisar de upgrade para suportar 'ultra_premium' ou 'premium'. Caindo pro Playwright.")
        except Exception as e:
            logger.warning(f"[SCRAPERAPI] ❌ Exceção: {str(e)[:100]}")

    # ── TENTATIVA 2: Requests Simples (Sem Playwright/Google Chrome) ──────
    try:
        logger.info(f"[EXTRACTOR_V2] Camada 2: Requests Simples | url={url[:60]}")
        async with httpx.AsyncClient(timeout=_TIMEOUT_HTTP, follow_redirects=True, headers=_HEADERS) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                logger.info("[REQUESTS] ✅ Sucesso")
                return resp.text, "REQUESTS_FALLBACK"
    except Exception as e:
        logger.warning(f"[REQUESTS] ❌ Falhou: {str(e)[:100]}")

    return None, "FALHA_TOTAL"


def _extract_search_term_from_url(url: str) -> str | None:
    """Extrai o nome do produto da URL para usar como busca na Lomadee."""
    from bot.services.lomadee_service import extrair_termo_busca
    try:
        termo = extrair_termo_busca(url)
        return termo if len(termo) >= 3 else None
    except Exception:
        return None


def _normalize_amazon_url(url: str) -> str:
    """
    Extrai o ASIN de qualquer variante de URL Amazon e retorna
    uma URL limpa: https://www.amazon.com.br/dp/{ASIN}
    
    Suporta:
      - amazon.com.br/dp/XXXXXXXXXX
      - amazon.com.br/gp/product/XXXXXXXXXX
      - amazon.com.br/gp/aw/d/XXXXXXXXXX
      - amazon.com.br/exec/obidos/ASIN/XXXXXXXXXX
      - amazon.com.br/o/ASIN/XXXXXXXXXX
      - amzn.to/XXXXX  (após resolução já foi convertido)
    """
    if not url or "amazon" not in url.lower():
        return url

    # Padrões para capturar ASIN (10 caracteres alfanuméricos)
    _ASIN_PATTERNS = [
        r"/dp/([A-Z0-9]{10})",
        r"/gp/product/([A-Z0-9]{10})",
        r"/gp/aw/d/([A-Z0-9]{10})",
        r"/exec/obidos/ASIN/([A-Z0-9]{10})",
        r"/exec/obidos/tg/detail/-/([A-Z0-9]{10})",
        r"/o/ASIN/([A-Z0-9]{10})",
        r"[?&]asin=([A-Z0-9]{10})",
        r"/([A-Z0-9]{10})(?:[/?#]|$)",  # fallback genérico
    ]

    for pattern in _ASIN_PATTERNS:
        m = re.search(pattern, url, re.IGNORECASE)
        if m:
            asin = m.group(1).upper()
            clean = f"https://www.amazon.com.br/dp/{asin}"
            if clean != url:
                logger.info(f"[AMAZON_NORM] ASIN extraído: {asin} → {clean}")
            return clean

    # Sem ASIN identificado — retorna original
    logger.debug(f"[AMAZON_NORM] Nenhum ASIN encontrado em: {url[:80]}")
    return url


async def extract_product_data_v2(url: str) -> dict:
    """Orquestrador do Pipeline Híbrido V5 (5 Camadas)."""
    from bot.utils.detect_store import detect_store
    from bot.utils.url_resolver import resolve_url

    logger.info(f"[EXTRATOR] ── INÍCIO PIPELINE V5 ── {url[:80]}")
    
    result = {
        "store": "desconhecida", "store_key": "other",
        "final_url": url, "titulo": "Produto", "imagem": None,
        "preco": "Preço não disponível", "preco_original": None,
        "source_method": "INICIANDO", "is_pix_price": False
    }

    # Resolve encurtadores simples antes de começar
    final_url = url
    try:
        # Resolve amzn.to, magalu.me e encurtadores comuns
        _SHORTENERS = ["amzn.to", "amzn.com/gp/r.", "magalu.me", "t.co", "bit.ly", "tinyurl.com", "ow.ly", "is.gd"]
        if any(x in url for x in _SHORTENERS):
            logger.info(f"[EXTRATOR] Resolvendo encurtador: {url[:60]}")
            final_url = await asyncio.to_thread(resolve_url, url)
            logger.info(f"[EXTRATOR] URL resolvida: {final_url[:80]}")
    except Exception as e:
        logger.warning(f"[EXTRATOR] Falha ao resolver encurtador: {e}")

    # Normaliza URLs Amazon para /dp/ASIN (remove parâmetros sujos, gp/product, etc.)
    if "amazon" in final_url.lower() or "amzn" in final_url.lower():
        final_url = _normalize_amazon_url(final_url)

    result["final_url"] = final_url
    store_display, store_key = detect_store(final_url)
    result["store"] = store_display
    result["store_key"] = store_key
    
    logger.info(f"[EXTRATOR] Loja detectada: {store_key} | URL: {final_url[:80]}")


    # ── CAMADA 0: LOMADEE API (Prioridade para Magalu e Netshoes) ─────────
    if store_key in ["magalu", "netshoes"]:
        search_term = _extract_search_term_from_url(final_url)
        if search_term:
            logger.info(f"[EXTRATOR] Camada 0: Tentando Lomadee API para '{search_term}'...")
            try:
                from bot.services.lomadee_service import buscar_produto_lomadee
                # Como a função de busca é síncrona, rodamos em thread para não bloquear o loop
                lomadee_results = await asyncio.to_thread(buscar_produto_lomadee, search_term, 1)
                
                if lomadee_results:
                    p = lomadee_results[0]
                    logger.info(f"[EXTRATOR] Camada 0 (LOMADEE): ✅ Sucesso | {p['nome'][:50]}")
                    result.update({
                        "titulo": p["nome"],
                        "imagem": p["imagem"],
                        "preco": p["preco"],
                        "source_method": "LOMADEE_API",
                        "is_pix_price": False,
                    })
                    return result
                else:
                    logger.warning(f"[EXTRATOR] Camada 0 (LOMADEE): ❌ Nenhum resultado para '{search_term}'")
            except Exception as e:
                logger.error(f"[EXTRATOR] Camada 0 (LOMADEE): ❌ Erro: {e}")

    # ── CAMADA 0b: API INTERNA (Magalu e Netshoes) ─────────────────────────
    if store_key == "magalu":
        logger.info("[EXTRATOR] Camada 0: Tentando Magalu API Interna...")
        api_data = await fetch_magalu_api(final_url)
        if api_data:
            logger.info(f"[EXTRATOR] Camada 0 (MAGALU): ✅ Sucesso via {api_data.get('source_method')}")
            result.update(api_data)
            return result
        else:
            logger.warning("[EXTRATOR] Camada 0 (MAGALU): ❌ Falhou — caindo para Camada 1")

    elif store_key == "netshoes":
        logger.info("[EXTRATOR] Camada 0: Tentando Netshoes API Interna...")
        api_data = await fetch_netshoes_api(final_url)
        if api_data:
            logger.info(f"[EXTRATOR] Camada 0 (NETSHOES): ✅ Sucesso via {api_data.get('source_method')}")
            result.update(api_data)
            return result
        else:
            logger.warning("[EXTRATOR] Camada 0 (NETSHOES): ❌ Falhou — caindo para Camada 1")

    # ── CAMADA 1-3: Fluxo de HTML ──────────────────────────────────────────
    html, method = await get_page_html(final_url)
    result["source_method"] = method

    if html:
        # 2. Parseamento Centralizado (BS4)
        data = _extract_from_soup(BeautifulSoup(html, "html.parser"), final_url, store_key)
        
        # Merge de resultados se não estiver bloqueado no parser
        if "BLOQUEIO" not in (data.get("titulo") or ""):
            for k in ["titulo", "preco", "preco_original", "imagem", "is_pix_price", "cupom"]:
                if data.get(k): result[k] = data[k]
            logger.info(f"[EXTRATOR] Camada {method}: ✅ Sucesso")
        else:
            result["titulo"] = data.get("titulo")
            result["source_method"] = f"{method}_BUT_PARSER_BLOCKED"
            logger.warning(f"[EXTRATOR] Camada {method}: ❌ Bloqueio no conteúdo")

    # ── CAMADA 4: Fallback Seguro ──────────────────────────────────────────
    if not result.get("titulo") or result["titulo"] == "Produto":
        result["titulo"] = "Produto Disponível"
        if result["source_method"] == "FALHA_TOTAL":
            result["source_method"] = "FALLBACK_MINIMO"

    # Blindagem final: garante contrato de saída completo e tipos corretos
    result = _validate_result(result)

    logger.info(f"[EXTRATOR] Metodo final usado: {result['source_method']}")
    logger.info(f"[EXTRATOR] Preco final: {result['preco']}")
    logger.info(f"[EXTRATOR] Titulo final: {result['titulo'][:60]}")
    return result
