"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.2 (THE VISIONARY) - Foco em extração de imagem e preço em páginas sociais.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

# Headers completos para evitar bloqueio de imagem
_HEADERS_ANTI_BLOCK = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Connection": "keep-alive",
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

def extract_json_ld(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string: continue
        try:
            data = json.loads(script.string)
            if isinstance(data, list) and data: data = data[0]
            if data.get("@type") == "Product": return data
        except: continue
    return {}

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
    result = {"image_url": None, "price": "Preço não disponível", "title": "Produto", "loja": "Desconhecida", "error": None}
    logger.info(f"[EXTRACTOR] --- VISIONARY V3.2 --- {url[:50]}")

    try:
        res = requests.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        final_url = res.url
        store_display, store_key = detect_store(final_url)
        result["loja"] = store_display

        # 1. Tenta API se for produto direto
        if store_key == "mercadolivre" and "/MLB-" in final_url:
            ml_data = _extract_mercadolivre_api(final_url)
            if ml_data:
                result["title"], result["image_url"] = ml_data["nome"], ml_data["imagem"]
                result["price"] = clean_price(ml_data["preco"])
                if result["image_url"] and result["price"] != "Preço não disponível": return result

        # 2. Scraping Agressivo
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Meta Tags
        og_t = _meta(soup, "og:title", "twitter:title")
        og_d = _meta(soup, "og:description", "twitter:description")
        og_i = _meta(soup, "og:image", "twitter:image", "og:image:secure_url")
        og_p = _meta(soup, "product:price:amount", "og:price:amount", "og:price")

        # Imagem - Fallback Especial para ML Vitrines
        if og_i: 
            result["image_url"] = urljoin(final_url, og_i)
        else:
            # Procura a primeira imagem com "MLB" ou em galerias
            m_img = soup.select_one("img[src*='MLB']") or soup.select_one(".ui-pdp-gallery__figure img")
            if m_img: result["image_url"] = urljoin(final_url, m_img.get("data-src") or m_img.get("src"))

        # Preço - Fallback de metadados
        if og_p: result["price"] = clean_price(og_p)

        # Título - Lógica de Vitrine (Vesta em V3.1)
        candidates = [og_t, og_d]
        for c in candidates:
            if not c: continue
            clean = re.sub(r"Visite a página.*|Mercado Livre|Descontinho.*|\||-", "", c, flags=re.IGNORECASE).strip()
            if len(clean) > 15:
                result["title"] = clean
                break

        # Fallback de Preço (Scan Bruto em JSON ou HTML)
        if result["price"] == "Preço não disponível":
            # Procura em scripts
            price_match = re.search(r'"price":\s*(\d+(?:\.\d{1,2})?)', res.text)
            if price_match: 
                result["price"] = clean_price(price_match.group(1))
            else:
                # Procura R$ XX,XX no texto visível
                raw_p = re.search(r'R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})', res.text)
                if raw_p: result["price"] = f"R$ {raw_p.group(1)}"

        # Finalização Amazon
        if store_key == "amazon" and result["price"] == "Preço não disponível":
            tag_p = soup.select_one("span.a-price .a-offscreen") or soup.select_one(".a-price-whole")
            if tag_p: result["price"] = clean_price(tag_p.text)

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.2: {e}")
        result["error"] = str(e)

    return result
