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

_HEADERS_ANTI_BLOCK = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
}

# ---------------------------------------------------------------------------
# Utilidades gerais
# ---------------------------------------------------------------------------

def clean_price(text: str) -> str | None:
    """Extrai e limpa o formato de preço do texto bruto."""
    if not text:
        return None
    
    # Remove espaços invisíveis e ruídos
    text = text.replace("\xa0", " ").replace("&nbsp;", " ").strip()
    
    # Caso 1: Formato JSON-LD puro (ex: 989.1 ou 1099)
    # Procura um número puro com opcionalmente um ponto e 1-2 casas decimais
    match_pure = re.match(r"^(\d+(?:\.\d{1,2})?)$", text)
    if match_pure:
        val = float(match_pure.group(1))
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # Caso 2: Formato com texto/símbolo (ex: R$ 1.299,90 ou 89.90)
    match = re.search(r"(\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{1,2}))", text)
    if match:
        val = match.group(1)
        # Normaliza: se tem ponto simples tipo "89.9", vira "89,90"
        if "." in val and "," not in val and val.count(".") == 1:
            val = val.replace(".", ",")
        if "," in val and len(val.split(",")[1]) == 1:
            val += "0"
        return f"R$ {val}"
    
    # Caso 3: Inteiro simples
    match_int = re.search(r"(?:R\$|USD)\s*(\d+)", text, re.IGNORECASE)
    if match_int:
        return f"R$ {match_int.group(1)},00"
        
    return None


def extract_json_ld(soup: BeautifulSoup) -> dict:
    """Busca dados estruturados JSON-LD do tipo Product."""
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string: continue
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "Product": return item
            elif data.get("@type") == "Product":
                return data
            elif "@graph" in data and isinstance(data["@graph"], list):
                for item in data["@graph"]:
                    if item.get("@type") == "Product": return item
        except Exception:
            continue
    return {}


def _meta(soup: BeautifulSoup, *props: str) -> str | None:
    """Retorna o conteúdo da primeira meta tag encontrada (OG, Twitter ou Name)."""
    for prop in props:
        tag = soup.find("meta", property=prop) or soup.find("meta", {"name": prop})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


# ---------------------------------------------------------------------------
# Extratores por domínio (Etapa 2 - Prioridade 3)
# ---------------------------------------------------------------------------

def _extract_aliexpress(soup: BeautifulSoup, final_url: str) -> dict:
    """Extração AliExpress: OG Tags e seletor fallback."""
    data = {
        "preco": _meta(soup, "og:price:amount", "product:price:amount"),
        "imagem": _meta(soup, "og:image", "twitter:image"),
        "nome": _meta(soup, "og:title")
    }
    if not data["preco"]:
        tag = soup.select_one(".product-price-value") or soup.select_one(".uniform-banner-box-price")
        if tag: data["preco"] = tag.text.strip()
    return data


def _extract_mercadolivre_api(url: str) -> dict:
    """Extrai via API oficial do Mercado Livre (mais estável)."""
    match = re.search(r"MLB-?(\d+)", url, re.IGNORECASE)
    if match:
        ml_id = f"MLB{match.group(1)}"
        api_url = f"https://api.mercadolibre.com/items/{ml_id}"
        try:
            r = requests.get(api_url, timeout=10, headers=_HEADERS_ANTI_BLOCK)
            if r.status_code == 200:
                js = r.json()
                return {
                    "nome": js.get("title"),
                    "preco": f"R$ {js.get('price', 0):.2f}".replace(".", ","),
                    "imagem": js.get("secure_thumbnail") or js.get("thumbnail")
                }
        except Exception as e:
            logger.warning(f"[EXTRACTOR][ML-API] Falha: {e}")
    return {}


def _extract_shopee_api(url: str) -> dict:
    """Extrai via API interna da Shopee (para SPAs)."""
    match = re.search(r"[/\.](\d+)[/\.](\d+)", url) # Tenta achar shopid/itemid
    if match:
        shop_id, item_id = match.group(1), match.group(2)
        # Às vezes a ordem inverte dependendo da URL, mas o itemid costuma ser o longo
        if len(shop_id) > len(item_id): shop_id, item_id = item_id, shop_id
        
        api_url = f"https://shopee.com.br/api/v4/item/get?itemid={item_id}&shopid={shop_id}"
        try:
            r = requests.get(api_url, headers=_HEADERS_ANTI_BLOCK, timeout=10)
            if r.status_code == 200:
                res = r.json()
                if res.get("data"):
                    item = res["data"]
                    return {
                        "nome": item.get("name"),
                        "preco": f"R$ {item.get('price', 0) / 100000:.2f}".replace(".", ","),
                        "imagem": f"https://down-br.img.susercontent.com/file/{item['image']}" if item.get("image") else None
                    }
        except Exception: pass
    return {}


# ---------------------------------------------------------------------------
# Entrada principal
# ---------------------------------------------------------------------------

def extract_product_data(url: str) -> dict:
    """
    Função Mestra de Extração (Etapas 1, 2, 3 e 4).
    """
    # Fallback padrão (Etapa 4)
    result = {
        "image_url": None,
        "price":     "Preço não disponível",
        "title":     "Produto",
        "loja":      "Desconhecida",
        "error":     None
    }

    logger.info(f"[EXTRACTOR] --- V2.1 --- Iniciando para: {url[:60]}")

    try:
        # Etapa 1 — Resolução de Redirecionamentos
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        # Força UTF-8 para evitar problemas com R$ e acentos
        res.encoding = 'utf-8' 
        final_url = res.url
        logger.info(f"[EXTRACTOR] URL Final: {final_url[:60]}")

        # Identifica a loja para estratégias específicas
        store_display, store_key = detect_store(final_url)
        result["loja"] = store_display

        # Etapa 2 — Estratégia por Domínio Especial (API)
        if store_key == "mercadolivre":
            ml_data = _extract_mercadolivre_api(final_url)
            if ml_data:
                result["title"] = ml_data.get("nome") or result["title"]
                result["price"] = clean_price(ml_data.get("preco")) or result["price"]
                result["image_url"] = ml_data.get("imagem")
                if result["image_url"] and result["price"] != "Preço não disponível":
                    return result

        if store_key == "shopee":
            shp_data = _extract_shopee_api(final_url)
            if shp_data:
                result["title"] = shp_data.get("nome") or result["title"]
                result["price"] = clean_price(shp_data.get("preco")) or result["price"]
                result["image_url"] = shp_data.get("imagem")
                if result["image_url"]: return result

        # Scraping HTML (Soup)
        soup = BeautifulSoup(res.text, "html.parser")

        # --- Estratégia 1: Meta Tags (OG) ---
        og_img = _meta(soup, "og:image", "twitter:image")
        og_price = _meta(soup, "product:price:amount", "og:price:amount", "og:price")
        og_title = _meta(soup, "og:title", "twitter:title")

        if og_img:   result["image_url"] = urljoin(final_url, og_img)
        if og_price: result["price"]     = clean_price(og_price) or result["price"]
        if og_title: 
            # EXTRA: Se preço falhou mas está no Título (Comum no Mercado Livre)
            if result["price"] == "Preço não disponível":
                price_match = re.search(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", og_title)
                if price_match:
                    result["price"] = f"R$ {price_match.group(1)}"
            
            # Limpa " - R$ ..." e " no Mercado Livre" do título
            clean_t = re.sub(r"\s-\sR\$.*", "", og_title)
            clean_t = re.sub(r"\sno\sMercado\sLivre.*", "", clean_t, flags=re.IGNORECASE)
            result["title"] = clean_t.strip()

        # --- Estratégia 2: JSON-LD ---
        if result["price"] == "Preço não disponível" or not result["image_url"] or result["title"] == "Produto":
            jld = extract_json_ld(soup)
            if jld:
                if not result["image_url"] and jld.get("image"):
                    img = jld["image"]
                    if isinstance(img, list) and img: img = img[0]
                    if isinstance(img, dict): img = img.get("url")
                    result["image_url"] = urljoin(final_url, str(img))
                
                if result["price"] == "Preço não disponível":
                    offers = jld.get("offers")
                    if isinstance(offers, dict):
                        p = offers.get("price") or offers.get("lowPrice")
                        if p: result["price"] = clean_price(str(p)) or result["price"]
                    elif isinstance(offers, list) and offers[0].get("price"):
                        result["price"] = clean_price(str(offers[0]["price"])) or result["price"]
                
                # JSON-LD costuma ter o nome limpo do produto
                if jld.get("name"):
                    result["title"] = str(jld["name"]).strip()

        # --- Estratégia 3: Seletores CSS Específicos ---
        if store_key == "amazon":
            # Preço Amazon
            for sel in ["span.a-price .a-offscreen", "#priceblock_ourprice", "#priceblock_dealprice"]:
                tag = soup.select_one(sel)
                if tag:
                    result["price"] = clean_price(tag.text) or result["price"]
                    break
            # Imagem Amazon
            for sel in ["#landingImage", "#imgBlkFront", "#main-image"]:
                tag = soup.select_one(sel)
                if tag:
                    img = tag.get("data-old-hires") or tag.get("src")
                    if img: result["image_url"] = urljoin(final_url, img)
                    break
        
        elif store_key == "mercadolivre":
            # Preço ML (Seletores de classe andes e ui-pdp)
            if result["price"] == "Preço não disponível":
                sel_p = [".ui-pdp-price__second-line .andes-money-amount__fraction", 
                         ".ui-pdp-price__current-price .andes-money-amount__fraction",
                         ".andes-money-amount__fraction"]
                for s in sel_p:
                    tag = soup.select_one(s)
                    if tag:
                        cents = tag.parent.select_one(".andes-money-amount__cents")
                        p_str = tag.text.strip() + (f",{cents.text.strip()}" if cents else ",00")
                        result["price"] = clean_price(p_str)
                        break
            
            # Imagem ML
            if not result["image_url"]:
                sel_img = [".ui-pdp-gallery__figure img", ".ui-pdp-image", "img.ui-pdp-image"]
                for s in sel_img:
                    tag = soup.select_one(s)
                    if tag:
                        img = tag.get("data-zoom") or tag.get("src")
                        if img: result["image_url"] = urljoin(final_url, img)
                        break

        elif store_key == "magalu":
            tag = soup.select_one("[data-testid='price-value']")
            if tag: result["price"] = clean_price(tag.text) or result["price"]

        elif store_key == "aliexpress":
            ali = _extract_aliexpress(soup, final_url)
            if ali.get("preco"): result["price"] = clean_price(ali["preco"]) or result["price"]
            if ali.get("imagem"): result["image_url"] = urljoin(final_url, ali["imagem"])
            if ali.get("nome"): result["title"] = ali["nome"]

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[EXTRACTOR] Falha na extração de {url}: {e}")

    # Fallback final de título se nada funcionou
    if result["title"] == "Produto":
        title_tag = soup.find("title") if 'soup' in locals() else None
        if title_tag: result["title"] = title_tag.text.strip()

    return result
