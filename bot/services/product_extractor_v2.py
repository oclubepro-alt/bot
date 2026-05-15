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
from bot.utils.config import SCRAPINGDOG_API_KEY

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
                  "acesso negado", "access denied", "validate.perfdrive.com", "radware",
                  "type the characters you see in this image", "human verification",
                  "verify you are human", "robot check", "unusual traffic from your computer"]

_TIMEOUT_HTTP = 15
_TIMEOUT_PLAYWRIGHT = 45



# ---------------------------------------------------------------------------
# Camada 0: API Interna da Magalu — cascata de 3 endpoints
# ---------------------------------------------------------------------------

async def fetch_magalu_api(url: str) -> dict | None:
    """
    Tenta extrair dados da Magalu sem scraping, via cascata de APIs:
      1. API mobile catalog (ms.catalog.magazineluiza.com.br)
      2. API site product (www.magazineluiza.com.br/api/v1/product/)
    """
    # Extrai o ID do produto da URL — padrão: /p/XXXXXXXX/
    match = re.search(r'/p/(\w+)/?', url)
    if not match:
        logger.warning("[MAGALU_API] ⚠️ ID do produto não encontrado na URL")
        return None

    product_id = match.group(1)
    logger.info(f"[MAGALU_API] ℹ️ Produto ID extraído: {product_id}")

    # Headers robustos para emular app/mobile e evitar blocks simples
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "pt-BR,pt;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "x-requested-with": "com.magalu.magaluapp"
    }

    _ENDPOINTS_MAGALU = [
        f"https://www.magazineluiza.com.br/api/v2/product/{product_id}",
        f"https://www.magazineluiza.com.br/api/v1/product/{product_id}/",
        f"https://m.magazineluiza.com.br/api/v1/product/{product_id}/"
    ]

    async with httpx.AsyncClient(timeout=12, follow_redirects=True, verify=False) as client:
        for endpoint in _ENDPOINTS_MAGALU:
            try:
                logger.info(f"[MAGALU_API] ℹ️ Tentando: {endpoint}")
                resp = await client.get(endpoint, headers=headers)
                
                if resp.status_code != 200:
                    continue

                data = resp.json()

                # --- Mapeamento flexível ---
                # Se for do ms.catalog, os dados podem estar direto ou em 'product'
                titulo = data.get("title") or data.get("name") or data.get("product", {}).get("title")
                
                # Preço
                p_obj = data.get("price") or data.get("product", {}).get("price") or {}
                best_price = p_obj.get("best_price") or p_obj.get("sale_price") or data.get("price_in_cash")
                
                # Imagem
                imagem = data.get("image") or data.get("thumbnail") or data.get("product", {}).get("image")
                if not imagem and data.get("images"):
                    imagem = data["images"][0].get("url")

                if titulo and best_price:
                    logger.info(f"[MAGALU_API] ✅ Sucesso via {endpoint}")
                    return {
                        "titulo": titulo,
                        "imagem": imagem,
                        "preco": _clean_price(str(best_price)),
                        "preco_original": None,
                        "source_method": "MAGALU_API_INTERNA",
                        "is_pix_price": True,
                    }

            except Exception as e:
                logger.warning(f"[MAGALU_API] ❌ Erro em {endpoint}: {str(e)[:80]}")
                continue

    # Camada 0b: Scraping LEVE (Apenas MetaTags/JSON-LD) com Mobile Headers
    try:
        logger.info("[MAGALU_API] ℹ️ Tentando extração leve via Mobile Headers...")
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                html = resp.text
                if any(p in html.lower() for p in ["radware", "captcha"]):
                    logger.warning("[MAGALU_API] ⚠️ Bloqueio detectado no HTML leve.")
                    return None
                
                # Tenta extrair do __NEXT_DATA__ ou similar se existir
                soup = BeautifulSoup(html, 'html.parser')
                
                # 1. JSON-LD
                scripts = soup.find_all("script", type="application/ld+json")
                preco_schema, _ = _extract_price_from_schema(soup)
                titulo_tag = soup.select_one("h1")
                titulo_schema = titulo_tag.get_text(strip=True) if titulo_tag else None
                
                if titulo_schema and preco_schema:
                    logger.info("[MAGALU_API] ✅ JSON-LD/HTML leve OK")
                    return {
                        "titulo": titulo_schema,
                        "imagem": None,
                        "preco": preco_schema,
                        "preco_original": None,
                        "source_method": "MAGALU_HTML_LEVE",
                        "is_pix_price": False,
                    }
    except Exception as e:
        logger.warning(f"[MAGALU_API] ⚠️ JSON-LD leve falhou: {str(e)[:80]}")

    # Camada 0c: Fallback via Busca (Resiliente a blocks de produto direto)
    try:
        logger.info("[MAGALU_API] ℹ️ Tentando fallback via busca por ID...")
        search_url = f"https://www.magazineluiza.com.br/busca/{product_id}"
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
            resp = await client.get(search_url)
            if resp.status_code == 200:
                html = resp.text
                if not any(p in html.lower() for p in ["radware", "captcha"]):
                    soup = BeautifulSoup(html, 'html.parser')
                    # Tenta pegar o primeiro produto da lista de busca
                    first_prod = soup.select_one('a[data-testid="product-card-container"]')
                    if first_prod:
                        title_tag = first_prod.select_one('h3[data-testid="product-title"]')
                        price_tag = first_prod.select_one('p[data-testid="price-value"]')
                        img_tag = first_prod.select_one('img[data-testid="image"]')
                        
                        if title_tag and price_tag:
                            logger.info("[MAGALU_API] ✅ Sucesso via Busca")
                            return {
                                "titulo": title_tag.get_text(strip=True),
                                "imagem": img_tag.get("src") if img_tag else None,
                                "preco": price_tag.get_text(strip=True),
                                "source_method": "MAGALU_SEARCH_API",
                                "is_pix_price": True
                            }
    except Exception as e:
        logger.warning(f"[MAGALU_API] ❌ Fallback busca falhou: {str(e)[:80]}")

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

    async with httpx.AsyncClient(timeout=12, follow_redirects=True, verify=False) as client:
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


async def fetch_amazon_scrapingdog(url: str) -> dict | None:
    """
    Extrai dados da Amazon via Scrapingdog API (Pago).
    Custo: 5 créditos por request (com country=br).
    """
    if not SCRAPINGDOG_API_KEY:
        logger.warning("[SCRAPINGDOG] ⚠️ SCRAPINGDOG_API_KEY não configurada!")
        return None

    # Extrai ASIN
    asin_match = re.search(r"/(?:dp|gp/product|product-reviews|aw/d|vdp|d)/([A-Z0-9]{10})", url, re.I)
    if not asin_match:
        asin_match = re.search(r"[/\?&](?:pd_rd_i|ASIN|item_id)=([A-Z0-9]{10})", url, re.I)
    
    if not asin_match:
        logger.warning(f"[SCRAPINGDOG] ⚠️ ASIN não encontrado na URL: {url[:60]}")
        return None
        
    asin = asin_match.group(1).upper()
    
    endpoint = "https://api.scrapingdog.com/amazon/product"
    params = {
        "api_key": SCRAPINGDOG_API_KEY,
        "asin": asin,
        "domain": "com.br",
        "country": "br"
    }
    
    try:
        logger.info(f"[SCRAPINGDOG] 📡 Consultando ASIN {asin} na Scrapingdog...")
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(endpoint, params=params)
            
            if resp.status_code == 200:
                data = resp.json()
                # Scrapingdog às vezes retorna uma lista com um objeto
                if isinstance(data, list) and len(data) > 0:
                    data = data[0]
                
                # Se houver erro na resposta da API (ex: crédito insuficiente)
                if data.get("error"):
                    logger.error(f"[SCRAPINGDOG] ❌ Erro da API: {data.get('error')}")
                    return None

                titulo = data.get("title") or data.get("name")
                price_raw = data.get("price") or data.get("sale_price")
                
                # Imagem
                imagem = None
                if data.get("images") and isinstance(data["images"], list):
                    imagem = data["images"][0]
                elif data.get("main_image"):
                    imagem = data["main_image"]

                if titulo and price_raw:
                    logger.info(f"[SCRAPINGDOG] ✅ Sucesso | {titulo[:50]} | Preço: {price_raw}")
                    return {
                        "titulo": titulo,
                        "imagem": imagem,
                        "preco": _clean_price(str(price_raw)),
                        "preco_original": _clean_price(str(data.get("original_price"))) if data.get("original_price") else None,
                        "source_method": "SCRAPINGDOG_API",
                        "is_pix_price": False,
                        "cupom": data.get("coupon_text") or data.get("coupon")
                    }
                else:
                    logger.warning("[SCRAPINGDOG] ⚠️ Resposta da API sem título ou preço.")
                    return None
            else:
                logger.error(f"[SCRAPINGDOG] ❌ Erro HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.error(f"[SCRAPINGDOG] ❌ Exceção Scrapingdog: {str(e)}")
    
    return None
# ---------------------------------------------------------------------------
# Helpers de preço
# ---------------------------------------------------------------------------

def _parse_price_to_float(price_str: str) -> float | None:
    """
    Converte strings de preço em float, lidando com formatos variados:
    - R$ 49,90 -> 49.9
    - 1.249,00 -> 1249.0
    - 1,249.00 -> 1249.0 (Internacional)
    - 49 -> 49.0
    """
    if not price_str:
        return None
        
    if isinstance(price_str, (int, float)):
        return float(price_str)

    if not isinstance(price_str, str):
        return None

    try:
        # 1. Limpeza básica: remove parênteses e caracteres não numéricos (exceto , e .)
        text = re.sub(r"\(.*?\)", "", price_str)
        clean = re.sub(r'[^\d,.]', '', text)
        if not clean: return None

        # 2. Heurística para decidir o formato (BR vs US)
        last_comma = clean.rfind(',')
        last_dot = clean.rfind('.')

        if last_comma > last_dot:
            # Formato BR: 1.249,00
            clean = clean.replace('.', '').replace(',', '.')
        elif last_dot > last_comma:
            # Formato US: 1,249.00
            clean = clean.replace(',', '')
        elif last_comma != -1:
            # Só tem vírgula: 49,90
            clean = clean.replace(',', '.')

        val = float(clean)
        # Sanity check: preços absurdos (> 1M) costumam ser erro de parsing
        if val > 1000000:
            return None
        return val
    except Exception:
        return None


def _clean_price(raw: str) -> str | None:
    """Normaliza preço para exibição: R$ 1.299,90 (Para HTML)"""
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


def format_api_price(amount: any) -> str | None:
    """
    Formata um preço vindo de uma API (número ou string puramente numérica com ponto).
    Evita a heurística de _clean_price que pode confundir milhar com decimal.
    """
    if amount is None:
        return None
    try:
        # Se for string, remove símbolos mas mantém o ponto
        if isinstance(amount, str):
            # Remove R$, espaços, etc, mas preserva o ponto decimal
            amount = amount.replace("R$", "").replace(" ", "").replace(",", ".")
            # Se tiver múltiplos pontos, remove todos exceto o último
            if amount.count(".") > 1:
                parts = amount.split(".")
                amount = "".join(parts[:-1]) + "." + parts[-1]
        
        val = float(amount)
        reais = int(val)
        centavos = round(abs(val - reais) * 100)
        # Ajuste se centavos arredondar para 100
        if centavos == 100:
            reais += 1
            centavos = 0
            
        reais_fmt = f"{reais:,}".replace(",", ".")
        return f"R$ {reais_fmt},{centavos:02d}"
    except (ValueError, TypeError):
        return None


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


def _extract_price_from_meta(soup: BeautifulSoup) -> str | None:
    """Extrai preço de meta tags (OG, Twitter, Product)."""
    meta_selectors = [
        ("property", "product:sale_price:amount"),
        ("property", "product:price:amount"),
        ("property", "og:price:amount"),
        ("name", "twitter:data1"), # Comum no Twitter Card para preço
        ("itemprop", "price"),
    ]
    for attr, val in meta_selectors:
        meta = soup.find("meta", attrs={attr: val})
        if meta and meta.get("content"):
            price = meta["content"].strip()
            # Limpa "R$" se vier no meta
            if _parse_price_to_float(price):
                return _clean_price(price)
    return None


def _extract_price_from_schema(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Tenta extrair preço via application/ld+json."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            content = script.string or ""
            if not content: continue
            data = json.loads(content)
            
            # Pode ser um dict ou list de dicts
            items = data if isinstance(data, list) else [data]
            for item in items:
                # Busca recursiva por "offers"
                offers = item.get("offers")
                if not offers and item.get("@type") == "Product":
                    offers = item.get("offers")
                
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                    if price:
                        return _clean_price(str(price)), None
                elif isinstance(offers, list) and offers:
                    price = offers[0].get("price") or offers[0].get("lowPrice")
                    if price:
                        return _clean_price(str(price)), None
        except:
            continue
    return None, None


def _extract_price_from_body_regex(soup: BeautifulSoup) -> str | None:
    """
    ULTIMATO: Busca qualquer padrão de R$ no corpo da página.
    Ideal para quando a Amazon bloqueia seletores mas deixa o texto.
    """
    # Remove scripts e estilos para não pegar números de lá
    for s in soup(["script", "style"]): s.decompose()
    
    text = soup.get_text(separator=" ")
    
    # Padrão 1: R$ 1.234,56 ou R$ 49,90
    matches = re.findall(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text)
    if matches:
        for m in matches:
            if m != "0,00":
                logger.info(f"[EXTRACTOR_V2] Preço minerado via Regex Body (BR): R$ {m}")
                return f"R$ {m}"
    
    # Padrão 2: 49.90 (Comum em JSON ou labels de API)
    matches_intl = re.findall(r"(?:\s|^)(\d{1,5}\.\d{2})(?:\s|$)", text)
    if matches_intl:
        for m in matches_intl:
            if float(m) > 1.0:
                logger.info(f"[EXTRACTOR_V2] Preço minerado via Regex Body (Intl): {m}")
                return f"R$ {m.replace('.', ',')}"

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
        # Permite apenas se também tiver 'priceToPay' ou 'apexPriceToPay' no contexto (é o preço real)
        valid_contexts = {"priceToPay", "apexPriceToPay", "priceToBuy"}
        has_valid_context = any(c in parent_classes or c in grandparent_classes for c in valid_contexts)
        if not has_valid_context:
            return False

    texto = tag.get_text(strip=True)
    classes = tag.get("class") or []

    # Sobe até 5 níveis para buscar contexto de 'unidade' (Amazon pattern)
    text_context = texto.lower()
    p = tag.parent
    for _ in range(5):
        if p is None: break
        # Coleta só o texto direto (não o texto de todos os filhos)
        direct_text = " ".join(t for t in p.strings if t.strip()).lower()
        text_context += " " + direct_text
        p = p.parent
    
    # 1. Filtro de palavras banidas (preço por unidade, etc)
    # MODIFICAÇÃO: 'unidade' e 'ml' agora só bloqueiam se houver um slash '/' antes (indica preço unitário)
    # ou se for explicitamente 'cada' / 'por unidade'.
    blacklist_strong = ["cada", "por unidade", "valor do ml", "valor do kg", "valor do grama"]
    for term in blacklist_strong:
        if term in text_context:
            return False

    # Filtros contextuais que podem estar no nome do produto (ex: Pack 12 Unidades)
    # Só bloqueamos se parecer um cálculo de preço unitário (R$ X / unidade)
    if re.search(r"/\s*(unidade|unid|ml|kg|g|m|pç|unit)", text_context):
        return False

    # 2. Filtro de Classes CSS
    bad_classes = [
        "a-text-price", "basisPrice", "listPrice", "unitPrice", 
        "price-per-unit", "a-size-small", "a-color-secondary", "strikethrough"
    ]
    # 'a-offscreen' não deve ser bloqueado, pois a Amazon usa para o preço principal em leitores de tela
    if any(c in bad_classes for c in classes):
        return False
        
    return True


def _extract_price_amazon(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Amazon: pegar preço promo e original."""
    preco_promo = None
    preco_orig  = None

    # 1. TENTA JSON-LD OU SCRIPTS (ALTA CONFIANÇA)
    preco_promo, preco_orig = _extract_price_from_schema(soup)
    if not preco_promo:
        p_script, o_script = _extract_price_from_scripts_amazon(soup)
        if p_script: 
            preco_promo = p_script
            if not preco_orig: preco_orig = o_script

    # 2. SELETORES CSS (FALLBACK)
    if not preco_promo:
        promo_selectors = [
            ".a-price.priceToPay .a-offscreen",
            "#corePrice_feature_div .priceToPay .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
            "#corePriceDisplay_mobile_feature_div .a-price .a-offscreen",
            ".a-price.apexPriceToPay .a-offscreen",
            "#corePrice_desktop .a-offscreen",
            "#priceblock_dealprice",
            "#priceblock_ourprice",
            "#priceblock_saleprice",
            "#price_inside_buybox",
            ".buybox-price",
            ".a-price .a-offscreen",
            "span.a-price",
            "span.a-color-price",
            "#corePrice_feature_div .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-offscreen",
            ".a-price:not(.a-text-price) .a-offscreen",
            ".a-size-base.a-color-price",
            "#price",
            ".price",
            # Seletores de baixa confiança (outros vendedores / listings)
            "#olp_feature_div .a-color-price",
            ".olp-padding-right .a-color-price",
            "#alternativeOffer .a-price .a-offscreen",
            ".olp-offer-price",
            ".a-size-mini .a-color-price",
        ]
        for sel in promo_selectors:
            for tag in soup.select(sel):
                if not _is_valid_price_tag(tag): continue
                val = tag.get_text(strip=True)
                
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

    # 3. PREÇO ORIGINAL (DE)
    if not preco_orig:
        orig_selectors = [
            ".a-price.a-text-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen",
            ".basisPrice .a-offscreen",
            ".a-line-through",
            "span.a-text-strike",
            ".priceBlockStrikePriceString",
        ]
        for sel in orig_selectors:
            tag = soup.select_one(sel)
            if tag:
                val = tag.get_text(strip=True)
                if _parse_price_to_float(val):
                    preco_orig = val
                    break

    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_from_scripts_amazon(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """
    Busca em tags <script> por dados de preço (a-state, P.register).
    """
    for script in soup.find_all("script"):
        content = script.string or ""
        if not content: continue
        
        # Tenta extrair blocos JSON de a-state
        if "a-state" in content or "desktop-dp-price-detail" in content:
            try:
                # Busca por algo que pareça um JSON dentro do script
                json_matches = re.findall(r"({.*})", content)
                for json_str in json_matches:
                    try:
                        data = json.loads(json_str)
                        p, o = _parse_amazon_paapi_dict(data)
                        if p: return p, o
                    except: continue
            except: pass
            
    return None, None


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
    
    # Detecção proativa de bloqueio
    is_blocked = any(p in page_title_lower for p in _BLOCK_KEYWORDS) or \
                 any(p in page_text_lower for p in ["radware bot manager", "please verify you are a human", "unusual traffic from your computer"])

    if is_blocked:
        logger.warning(f"[EXTRACTOR_V2] Bloqueio detectado no HTML: {page_title_lower}")
        return {
            "titulo": None, 
            "preco": None,
            "imagem": None,
            "source_method": "BLOCKED"
        }

    # ── TÍTULO ──────────────────────────────────────────────────────────────
    title_selectors = [
        "#productTitle",             # Amazon principal
        "#title",                    # Amazon secundário
        ".product-title",            # Genérico
        ".ui-pdp-title",             # Mercado Livre
        "h1[itemprop='name']",       # Magalu / genérico
        ".header-product__title",    # Netshoes
        "h1.product-name", 
        "h1.title",
        "h1",
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
    
    # Fallback ULTIMATO: Título da Tag HTML
    if not data["titulo"] and soup.title:
        raw_title = soup.title.get_text(strip=True)
        if raw_title and len(raw_title) > 5:
            # Limpa lixo comum
            raw_title = re.sub(r"^(Amazon\.com\.br|Mercado Livre|Magalu|Magazine Luiza)\s*[:\-]\s*", "", raw_title, flags=re.I)
            data["titulo"] = raw_title.split(":")[0].split("|")[0].strip()

    # ── VALIDAÇÃO DE TÍTULO (Anti-Vazamento de Bloqueio) ────────────────────
    if data["titulo"]:
        t_low = data["titulo"].lower()
        if any(p in t_low for p in _BLOCK_KEYWORDS) or "bloqueio" in t_low:
            logger.warning(f"[EXTRACTOR_V2] Título suspeito de bloqueio rejeitado: {data['titulo']}")
            data["titulo"] = None
            return {
                "titulo": None,
                "preco": None,
                "imagem": None,
                "source_method": "BLOCKED"
            }

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

    # ── ULTIMATO DE PREÇO (Meta / Schema / Regex) ──────────────────────────
    if not data["preco"]:
        # Tenta meta tags primeiro (rápido e confiável)
        data["preco"] = _extract_price_from_meta(soup)
        
        if not data["preco"]:
            # Tenta schema.org
            p_schema, o_schema = _extract_price_from_schema(soup)
            if p_schema:
                data["preco"] = p_schema
                if not data["preco_original"]: data["preco_original"] = o_schema
        
        if not data["preco"]:
            # Tenta regex bruto como última opção
            data["preco"] = _extract_price_from_body_regex(soup)

    # Fallback preco_original via meta se estiver vazio
    if not data["preco_original"] and store_key == "amazon":
        _, data["preco_original"] = _extract_price_generic(soup)

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
    1. HTTPX Mobile (Fallback de Alta Qualidade)
    2. Requests Simples (Fallback)
    """

    # ── TENTATIVA 1b: HTTPX Direto com Mobile User-Agent (Fallback de Alta Qualidade) ──────
    try:
        logger.info(f"[EXTRACTOR_V2] Camada 1b: HTTPX Mobile | url={url[:60]}")
        mobile_headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "pt-BR,pt;q=0.9",
            "Referer": "https://www.google.com/",
        }
        # Fallback de Alta Qualidade: Mobile User-Agent
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=mobile_headers) as client:
            # Se for Amazon, tenta a versão /gp/aw/d/ que é mais leve e menos protegida
            target_url = url
            if "amazon.com.br" in url:
                asin_match = re.search(r"/(?:dp|gp/product|aw/d)/([A-Z0-9]{10})", url)
                if asin_match:
                    target_url = f"https://www.amazon.com.br/gp/aw/d/{asin_match.group(1)}?psc=1"
            
            resp = await client.get(target_url)
            if resp.status_code == 200:
                html = resp.text
                if not any(p in html.lower() for p in ["radware", "captcha", "blocked"]):
                    logger.info(f"[HTTPX_MOBILE] ✅ Sucesso | URL={target_url[:50]}...")
                    return html, "HTTPX_MOBILE"
    except Exception as e:
        logger.warning(f"[HTTPX_MOBILE] ❌ Falhou: {str(e)[:100]}")
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

    # Tenta extrair o ASIN (10 caracteres alfanuméricos) de vários formatos comuns
    # Regex expandida para pegar em mais contextos (incluindo links patrocinados)
    asin_match = re.search(r"/(?:dp|gp/product|product-reviews|aw/d|vdp|d)/([A-Z0-9]{10})", url, re.I)
    if not asin_match:
        # Tenta pegar pd_rd_i=... ou similar
        asin_match = re.search(r"[/\?&](?:pd_rd_i|ASIN|item_id)=([A-Z0-9]{10})", url, re.I)
    
    if not asin_match:
        # Tenta pegar qualquer string de 10 chars que comece com B0 (comum em ASINs)
        asin_match = re.search(r"[/\?&=](B[A-Z0-9]{9})", url, re.I)

    if asin_match:
        asin = asin_match.group(1).upper()
        domain = "www.amazon.com.br" if "amazon.com.br" in url.lower() else "www.amazon.com"
        clean = f"https://{domain}/dp/{asin}"
        logger.info(f"[AMAZON_NORM] ASIN extraído: {asin} -> {clean}")
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
        _SHORTENERS = ["amzn.to", "amzn.com/gp/r.", "magalu.me", "t.co", "bit.ly", "ow.ly", "is.gd"]
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

    elif store_key == "amazon":
        # Tenta primeiro a Scrapingdog (Nova recomendação do usuário)
        logger.info("[EXTRATOR] Camada 0: Tentando Scrapingdog API...")
        api_data = await fetch_amazon_scrapingdog(final_url)
        
        if api_data:
            logger.info("[EXTRATOR] Camada 0 (SCRAPINGDOG): ✅ Sucesso")
            result.update(api_data)
            return result
            
        # Se falhar Scrapingdog, tenta a Amazon Creators API (Antiga, pode estar inativa)
        logger.info("[EXTRATOR] Camada 0b: Tentando Amazon Creators API (Fallback)...")
        try:
            from bot.services.amazon_api import amazon_api
            api_data = await amazon_api.get_product_details(final_url)
            if api_data and api_data.get("preco") and api_data.get("preco") != "Preço não disponível":
                logger.info(f"[EXTRATOR] Camada 0b (AMAZON_API): ✅ Sucesso")
                result.update(api_data)
                return result
            elif api_data:
                logger.warning("[EXTRATOR] Camada 0b (AMAZON_API): ⚠️ Dados parciais. Tentando scraping...")
                result.update({k: v for k, v in api_data.items() if v and v != "Preço não disponível"})
        except Exception as e:
            logger.error(f"[EXTRATOR] Camada 0b (AMAZON_API): ❌ Erro: {e}")

    elif store_key == "netshoes":
        logger.info("[EXTRATOR] Camada 0: Tentando Netshoes API Interna...")
        api_data = await fetch_netshoes_api(final_url)
        if api_data:
            logger.info(f"[EXTRATOR] Camada 0 (NETSHOES): ✅ Sucesso via {api_data.get('source_method')}")
            result.update(api_data)
            return result
        else:
            logger.warning("[EXTRATOR] Camada 0 (NETSHOES): ❌ Falhou — caindo para Camada 1")

    elif store_key == "mercadolivre":
        logger.info("[EXTRATOR] Camada 0: Tentando Mercado Livre API Oficial...")
        try:
            from bot.services.mercadolivre_api import mercadolivre_api
            api_data = await mercadolivre_api.get_product_details(final_url)
            if api_data:
                logger.info("[EXTRATOR] Camada 0 (ML_API): ✅ Sucesso")
                result.update(api_data)
                return result
        except Exception as e:
            logger.error(f"[EXTRATOR] Camada 0 (ML_API): ❌ Erro: {e}")

    # ── CAMADA 1-3: Fluxo de HTML ──────────────────────────────────────────
    html, method = await get_page_html(final_url)
    result["source_method"] = method

    if html:
        # 2. Parseamento Centralizado (BS4)
        data = _extract_from_soup(BeautifulSoup(html, "html.parser"), final_url, store_key)
        
        # Merge de resultados se não estiver bloqueado no parser
        # Merge de resultados se não estiver bloqueado no parser
        is_result_blocked = (data.get("source_method") == "BLOCKED")
        
        if not is_result_blocked:
            for k in ["titulo", "preco", "preco_original", "imagem", "is_pix_price", "cupom"]:
                if data.get(k): result[k] = data[k]
            logger.info(f"[EXTRATOR] Camada {method}: ✅ Sucesso")
        else:
            result["source_method"] = f"{method}_BUT_BLOCKED"
            logger.warning(f"[EXTRATOR] Camada {method}: ❌ Bloqueio detectado no conteúdo")

    # ── CAMADA 4: Fallback Seguro ──────────────────────────────────────────
    if not result.get("titulo") or result["titulo"] == "Produto":
        # Tenta inferir da URL se tudo falhar
        if "amazon" in final_url.lower():
            result["titulo"] = "Produto Amazon"
        elif "magalu" in final_url.lower():
            result["titulo"] = "Produto Magalu"
        elif "mercadolivre" in final_url.lower():
            result["titulo"] = "Produto Mercado Livre"
        else:
            result["titulo"] = "Produto Disponível"
            
        if result["source_method"] == "FALHA_TOTAL":
            result["source_method"] = "FALLBACK_MINIMO"

    # Blindagem final: garante contrato de saída completo e tipos corretos
    result = _validate_result(result)

    logger.info(f"[EXTRATOR] Metodo final usado: {result['source_method']}")
    logger.info(f"[EXTRATOR] Preco final: {result['preco']}")
    logger.info(f"[EXTRATOR] Titulo final: {result['titulo'][:60]}")
    return result
