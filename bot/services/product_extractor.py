"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.9.1 (GHOST PROTOCOL FIX) - Preservação de estado e fallback de títulos.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_HEADERS_ANTI_BLOCK = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Cache-Control": "max-age=0",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
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
    
    # Título (Andes UI + Meta Fallback)
    t_tag = soup.select_one(".ui-pdp-title") or soup.select_one("h1")
    if t_tag: 
        data["title"] = t_tag.get_text().strip()
    else:
        og_t = (soup.find("meta", property="og:title") or {}).get("content")
        if og_t: data["title"] = re.sub(r"Mercado Livre.*|\||-", "", og_t, flags=re.IGNORECASE).strip()

    # Preço (Promocional/Andes)
    p_main = soup.select_one(".ui-pdp-price__second-line .andes-money-amount__fraction") or \
             soup.select_one(".andes-money-amount--main .andes-money-amount__fraction") or \
             soup.select_one(".andes-money-amount__fraction")
    
    if p_main:
        # Verifica se não é preço riscado
        if not (p_main.find_parent("s") or "strike" in str(p_main.parent).lower()):
            price_str = p_main.get_text().strip()
            cents = p_main.parent.select_one(".andes-money-amount__cents")
            if cents: price_str += f",{cents.get_text().strip()}"
            data["price"] = clean_price(price_str)
    
    # Imagem
    og_i = (soup.find("meta", property="og:image") or {}).get("content")
    if og_i and "mlstatic" in og_i:
        data["image_url"] = og_i
    else:
        img_tag = soup.select_one(".ui-pdp-gallery__figure img") or soup.select_one("img.ui-pdp-image")
        if img_tag: data["image_url"] = img_tag.get("data-zoom") or img_tag.get("data-src") or img_tag.get("src")

    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V3.9.1 (GHOST FIX) --- {url[:50]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        store_display, store_key = detect_store(final_url)
        result["loja"], result["store_key"] = store_display, store_key

        # --- PRIMEIRA EXTRAÇÃO (VITRINE) ---
        first_pass = _scrape_full_page(soup, html)
        result["title"] = first_pass["title"] or "Produto"
        result["image_url"] = first_pass["image_url"]
        result["price"] = first_pass["price"] or "Preço não disponível"

        # --- SEGUNDA EXTRAÇÃO (RECURSIVA) ---
        if "/social/" in final_url:
            q_orig = parse_qs(urlparse(url).query)
            target_short = q_orig.get("short_name", [url.split("/")[-1]])[0]
            
            logger.info(f"[EXTRACTOR] Caçando short_name: {target_short}")
            links_social = soup.find_all("a", href=re.compile(target_short))
            real_url = urljoin(final_url, links_social[0]["href"]) if links_social else None
            
            if not real_url:
                m_links = re.findall(r'https?://[^"\s]*MLB[^"\s>]*', html)
                if m_links: real_url = m_links[0]
            
            if real_url:
                logger.info(f"[EXTRACTOR] Seguindo para: {real_url}")
                res_real = session.get(real_url, headers=_HEADERS_ANTI_BLOCK, timeout=10)
                deep_data = _scrape_full_page(BeautifulSoup(res_real.text, "html.parser"), res_real.text)
                
                # SÓ ATUALIZA SE OS NOVOS DADOS FOREM VÁLIDOS (Preservação de Estado)
                if deep_data["title"] and len(deep_data["title"]) > 10:
                    result["title"] = deep_data["title"]
                if deep_data["price"] and deep_data["price"] != "Preço não disponível":
                    # Validação de preço de TV
                    try:
                        p_val = float(deep_data["price"].replace("R$ ", "").replace(".", "").replace(",", "."))
                        if not ("TV" in result["title"].upper() and p_val < 350):
                            result["price"] = deep_data["price"]
                    except: pass
                if deep_data["image_url"]:
                    result["image_url"] = deep_data["image_url"]

        # Fallback final de imagem
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.9.1: {e}")
        result["error"] = str(e)

    return result
