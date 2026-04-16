"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.8.1 (RESTART FIX) - Reforço na extração de nome e limpeza de sessão.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_HEADERS_ANTI_BLOCK = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = re.sub(r'[^0-9,.]', '', text.replace('\xa0', ' '))
    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", text)
    if match:
        val = match.group(1)
        if "," not in val: val += ",00"
        return f"R$ {val}"
    return None

def _scrape_full_page(soup, html):
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. Título (Reforçado)
    t_tag = soup.select_one(".ui-pdp-title") or soup.select_one("h1") or soup.select_one(".social-vitrine-item__title")
    if t_tag: 
        data["title"] = t_tag.get_text().strip()
    else:
        # Fallback para metadados
        og_t = (soup.find("meta", property="og:title") or {}).get("content")
        if og_t: data["title"] = re.sub(r"Mercado Livre.*|\||-", "", og_t, flags=re.IGNORECASE).strip()

    # 2. Preço (Priorizando menor valor)
    price_containers = soup.select(".ui-pdp-price__second-line .andes-money-amount__fraction") or \
                       soup.select(".andes-money-amount--main .andes-money-amount__fraction") or \
                       soup.select(".andes-money-amount__fraction")
    
    prices_found = []
    for p in price_containers:
        # Pula preços riscados
        parent_text = p.parent.get_text().lower() if p.parent else ""
        if "antes" in parent_text or p.find_parent("s") or p.find_parent(class_=re.compile("strike|old")):
            continue
            
        digits = p.get_text().strip()
        cents_tag = p.parent.select_one(".andes-money-amount__cents")
        if cents_tag: digits += f",{cents_tag.get_text().strip()}"
        prices_found.append(digits)

    if prices_found:
        def to_float(s): return float(s.replace(".", "").replace(",", "."))
        prices_found.sort(key=to_float)
        data["price"] = clean_price(prices_found[0])

    # 3. Imagem
    img_tag = soup.select_one(".ui-pdp-gallery__figure img") or \
              soup.select_one("img.ui-pdp-image") or \
              soup.select_one(".social-vitrine-item__image img")
    if img_tag:
        data["image_url"] = img_tag.get("data-zoom") or img_tag.get("data-src") or img_tag.get("src")

    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V3.8.1 (RESTART FIX) --- {url[:50]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        store_display, store_key = detect_store(final_url)
        result["loja"], result["store_key"] = store_display, store_key

        # Recursividade para Social
        if "/social/" in final_url:
            links = re.findall(r'https?://(?:www\.|produto\.)?mercadolivre\.com\.br/[^"\s]*MLB-?[^"\s>]*', html)
            if links:
                inner_res = session.get(links[0], headers=_HEADERS_ANTI_BLOCK, timeout=10)
                deep_data = _scrape_full_page(BeautifulSoup(inner_res.text, "html.parser"), inner_res.text)
                result.update({k: v for k, v in deep_data.items() if v})

        # Extração Direta Fallback
        direct_data = _scrape_full_page(soup, html)
        if result["title"] == "Produto": result["title"] = direct_data["title"] or "Produto"
        if not result["image_url"]: result["image_url"] = direct_data["image_url"]
        if result["price"] == "Preço não disponível": result["price"] = direct_data["price"]

        # Finalização de imagem
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.8.1: {e}")
        result["error"] = str(e)

    return result
