"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.7 (THE ORACLE) - Sensors para Andes UI e Metadados Twitter.
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
    text = re.sub(r'[^0-9,.]', '', text.replace('\xa0', ' '))
    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", text)
    if match:
        val = match.group(1)
        if "," not in val: val += ",00"
        return f"R$ {val}"
    return None

def _scrape_full_page(soup, html):
    """Extração profunda usando seletores conhecidos do Mercado Livre (Andes UI)."""
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. Título
    t_tag = soup.select_one(".ui-pdp-title") or soup.select_one("h1")
    if t_tag: data["title"] = t_tag.get_text().strip()

    # 2. Preço (Andes UI)
    p_tag = soup.select_one(".andes-money-amount__fraction") or soup.select_one(".ui-pdp-price__price .andes-money-amount__fraction")
    if p_tag:
        decimals = soup.select_one(".andes-money-amount__cents")
        price_str = p_tag.get_text().strip()
        if decimals: price_str += f",{decimals.get_text().strip()}"
        data["price"] = clean_price(price_str)

    # 3. Imagem
    img_tag = soup.select_one(".ui-pdp-gallery__figure img") or soup.select_one("img.ui-pdp-image")
    if img_tag:
        data["image_url"] = img_tag.get("data-zoom") or img_tag.get("data-src") or img_tag.get("src")

    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- THE ORACLE V3.7 --- {url[:50]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        store_display, store_key = detect_store(final_url)
        result["loja"], result["store_key"] = store_display, store_key

        # --- FASE 1: Metadados Estruturados (Confiáveis para Redes Sociais) ---
        og_t = (soup.find("meta", property="og:title") or {}).get("content")
        og_d = (soup.find("meta", property="og:description") or {}).get("content")
        og_i = (soup.find("meta", property="og:image") or {}).get("content")
        
        # Detecção de Preço via Twitter Tags (Truque ML Vitrines)
        tw_label1 = (soup.find("meta", {"name": "twitter:label1"}) or {}).get("content", "").lower()
        tw_data1  = (soup.find("meta", {"name": "twitter:data1"}) or {}).get("content")
        
        if "preço" in tw_label1 and tw_data1:
            result["price"] = clean_price(tw_data1)

        # --- FASE 2: Recursividade em Vitrines ---
        if "/social/" in final_url and result["price"] == "Preço não disponível":
            logger.info("[EXTRACTOR] Vitrine Social sem preço. Buscando link MLB...")
            links = re.findall(r'https?://(?:www\.|produto\.)?mercadolivre\.com\.br/[^"\s]*MLB-?[^"\s>]*', html)
            if links:
                logger.info(f"[EXTRACTOR] Seguindo link: {links[0]}")
                inner_res = session.get(links[0], headers=_HEADERS_ANTI_BLOCK, timeout=10)
                inner_data = _scrape_full_page(BeautifulSoup(inner_res.text, "html.parser"), inner_res.text)
                result.update({k: v for k, v in inner_data.items() if v})

        # --- FASE 3: Scraping Direto (Andes UI) ---
        direct_data = _scrape_full_page(soup, html)
        if not result["image_url"]: result["image_url"] = direct_data["image_url"] or og_i
        if not result["title"] or result["title"] == "Produto": 
            result["title"] = direct_data["title"] or re.sub(r"Mercado Livre.*|\||-", "", og_t, flags=re.IGNORECASE).strip() if og_t else "Produto"
        if result["price"] == "Preço não disponível": result["price"] = direct_data["price"]

        # --- FASE 4: Heurísticas Finais ---
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])
            
        # Filtro de TV barato (acessórios)
        if "TV" in result["title"].upper() and result["price"] != "Preço não disponível":
            try:
                p_val = float(result["price"].replace("R$ ", "").replace(".", "").replace(",", "."))
                if p_val < 350: result["price"] = "Preço não disponível"
            except: pass

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.7: {e}")
        result["error"] = str(e)

    return result
