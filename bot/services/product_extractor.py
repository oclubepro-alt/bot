"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.8 (PRICE MASTER) - Prioridade para menor preço (Pix/Oferta) e filtragem de preço antigo.
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
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Referer": "https://www.mercadolivre.com.br/",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    # Remove tudo que não é número, vírgula ou ponto
    text = re.sub(r'[^0-9,.]', '', text.replace('\xa0', ' '))
    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", text)
    if match:
        val = match.group(1)
        if "," not in val: val += ",00"
        return f"R$ {val}"
    return None

def _scrape_full_page(soup, html):
    """Extração profunda focada em capturar o preço promocional real."""
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. Título
    t_tag = soup.select_one(".ui-pdp-title") or soup.select_one("h1") or soup.select_one(".social-vitrine-item__title")
    if t_tag: data["title"] = t_tag.get_text().strip()

    # 2. Preço (Priorizando promoção)
    # Procuramos por andes-money-amount que NÃO estejam dentro de containers de "preço antigo"
    # O Mercado Livre costuma usar .ui-pdp-price__second-line para o preço principal
    price_containers = soup.select(".ui-pdp-price__second-line .andes-money-amount__fraction") or \
                       soup.select(".andes-money-amount--main .andes-money-amount__fraction") or \
                       soup.select(".andes-money-amount__fraction")
    
    prices_found = []
    for p in price_containers:
        # Ignora se for preço riscado (antigo)
        parent_text = p.parent.get_text().lower() if p.parent else ""
        if "antes" in parent_text or "<s>" in str(p.parent):
            continue
            
        digits = p.get_text().strip()
        cents_tag = p.parent.select_one(".andes-money-amount__cents")
        if cents_tag:
            digits += f",{cents_tag.get_text().strip()}"
        
        prices_found.append(digits)

    if prices_found:
        # Pega o menor preço encontrado (geralmente o do Pix ou Promocional)
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
    logger.info(f"[EXTRACTOR] --- PRICE MASTER V3.8 --- {url[:50]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        store_display, store_key = detect_store(final_url)
        result["loja"], result["store_key"] = store_display, store_key

        # Tentar recursividade se for vitrine social
        if "/social/" in final_url:
            links = re.findall(r'https?://(?:www\.|produto\.)?mercadolivre\.com\.br/[^"\s]*MLB-?[^"\s>]*', html)
            if links:
                inner_res = session.get(links[0], headers=_HEADERS_ANTI_BLOCK, timeout=10)
                deep_data = _scrape_full_page(BeautifulSoup(inner_res.text, "html.parser"), inner_res.text)
                result.update({k: v for k, v in deep_data.items() if v})
                if result["price"] != "Preço não disponível": return result

        # Extração Direta
        direct_data = _scrape_full_page(soup, html)
        result["title"] = direct_data["title"] or result["title"]
        result["image_url"] = direct_data["image_url"] or result["image_url"]
        result["price"] = direct_data["price"] or result["price"]

        # Se ainda falhar, tenta metadados básicos como último recurso
        if result["price"] == "Preço não disponível":
            tw_data1 = (soup.find("meta", {"name": "twitter:data1"}) or {}).get("content")
            if tw_data1: result["price"] = clean_price(tw_data1)

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.8: {e}")
        result["error"] = str(e)

    return result
