"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.3 (THE INFILTRATOR) - Corrigida comunicação de store_key e extração profunda.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_HEADERS_ANTI_BLOCK = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", text)
    if match:
        val = match.group(1)
        if "," not in val: val += ",00"
        return f"R$ {val}"
    return None

def _meta(soup, *props):
    for prop in props:
        tag = soup.find("meta", property=prop) or soup.find("meta", {"name": prop})
        if tag and tag.get("content"): return tag["content"].strip()
    return None

def _extract_mercadolivre_api(url):
    match = re.search(r"MLB-?(\d+)", url)
    if match:
        api_url = f"https://api.mercadolibre.com/items/MLB{match.group(1)}"
        try:
            r = requests.get(api_url, timeout=5)
            if r.status_code == 200:
                js = r.json()
                return {
                    "nome": js.get("title"),
                    "preco": f"R$ {js.get('price', 0):.2f}".replace(".", ","),
                    "imagem": js.get("secure_thumbnail")
                }
        except: pass
    return {}

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, 
        "price": "Preço não disponível", 
        "title": "Produto", 
        "loja": "Desconhecida", 
        "store_key": "other", # IMPORTANTE: Campo faltante que causava o bug
        "error": None
    }
    logger.info(f"[EXTRACTOR] --- INFILTRATOR V3.3 --- {url[:50]}")

    try:
        res = requests.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        final_url = res.url
        store_display, store_key = detect_store(final_url)
        result["loja"] = store_display
        result["store_key"] = store_key

        # 1. API ML para links diretos
        if store_key == "mercadolivre" and "/MLB-" in final_url:
            ml = _extract_mercadolivre_api(final_url)
            if ml:
                result["title"], result["image_url"] = ml["nome"], ml["imagem"]
                result["price"] = clean_price(ml["preco"])
                if result["image_url"] and result["price"] != "Preço não disponível": return result

        # 2. Scraping Soup
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Meta Tags
        og_t = _meta(soup, "og:title", "twitter:title")
        og_d = _meta(soup, "og:description", "twitter:description")
        og_i = _meta(soup, "og:image", "twitter:image", "og:image:secure_url")
        og_p = _meta(soup, "product:price:amount", "og:price:amount", "og:price")

        # Título Inteligente (Vitrines)
        candidates = [og_t, og_d]
        for c in candidates:
            if not c: continue
            clean = re.sub(r"Visite a página.*|Mercado Livre|Descontinho.*|\||-|Encontre os melhores.*", "", c, flags=re.IGNORECASE).strip()
            if len(clean) > 15:
                result["title"] = clean
                break

        # Imagem - Busca agressiva em vitrines
        if og_i and "mercadolivre.com.br" in og_i: 
            result["image_url"] = urljoin(final_url, og_i)
        else:
            # Seletores de galeria e atributos escondidos
            m_img = soup.select_one("img[src*='MLB']") or soup.select_one(".ui-pdp-gallery__figure img") or soup.select_one("img.nav-header-logo")
            if m_img: result["image_url"] = urljoin(final_url, m_img.get("data-src") or m_img.get("src"))

        # Preço - Busca em profundidade
        if og_p: result["price"] = clean_price(og_p)
        
        if result["price"] == "Preço não disponível":
            # Scan em JSON oculto no HTML
            price_match = re.search(r'"price":\s*(\d+(?:\.\d{1,2})?)', res.text)
            if price_match: 
                result["price"] = clean_price(price_match.group(1))
            else:
                # Scan no texto visível
                raw_p = re.search(r'R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})', res.text)
                if raw_p: result["price"] = f"R$ {raw_p.group(1)}"

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.3: {e}")
        result["error"] = str(e)

    return result
