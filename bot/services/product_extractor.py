"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.6 (RECURSIVE SCANNER) - Extração em duas etapas para Vitrines Sociais.
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
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", text)
    if match:
        val = match.group(1)
        if "," not in val: val += ",00"
        return f"R$ {val}"
    return None

def _extract_from_html(html, url):
    """Função interna de extração direta de uma página de produto real."""
    soup = BeautifulSoup(html, "html.parser")
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. Título
    og_t = (soup.find("meta", property="og:title") or {}).get("content")
    if og_t: data["title"] = re.sub(r"Mercado Livre.*|\||-", "", og_t, flags=re.IGNORECASE).strip()
    
    # 2. Imagem (Alta resolução)
    og_i = (soup.find("meta", property="og:image") or {}).get("content")
    if og_i: data["image_url"] = og_i
    else:
        m = re.search(r'https://http2\.mlstatic\.com/D_NQ_NP_[^"\s]+-O\.jpg', html)
        if m: data["image_url"] = m.group(0)

    # 3. Preço
    og_p = (soup.find("meta", property="product:price:amount") or {}).get("content")
    if og_p: data["price"] = clean_price(og_p)
    else:
        m_p = re.search(r'R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})', html)
        if m_p: data["price"] = f"R$ {m_p.group(1)}"
        
    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- RECURSIVE SCANNER V3.6 --- {url[:50]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        html = res.text
        
        final_url = res.url
        store_display, store_key = detect_store(final_url)
        result["loja"] = store_display
        result["store_key"] = store_key

        # SE FOR PÁGINA SOCIAL - ATIVAR RECURSIVIDADE
        if "/social/" in final_url:
            logger.info("[EXTRACTOR] Vitrine Social detectada. Buscando link do produto real...")
            # Procura links MLB- ou links que pareçam ser de produtos reais do ML
            links_real = re.findall(r'https://www\.mercadolivre\.com\.br/p/MLB[^"\s?#]+', html) or \
                         re.findall(r'https://produto\.mercadolivre\.com\.br/MLB-[^"\s?#]+', html)
            
            if links_real:
                real_product_url = links_real[0]
                logger.info(f"[EXTRACTOR] Seguindo para o produto real: {real_product_url}")
                res_real = session.get(real_product_url, headers=_HEADERS_ANTI_BLOCK, timeout=10)
                deep_data = _extract_from_html(res_real.text, real_product_url)
                
                result["title"] = deep_data["title"] or result["title"]
                result["image_url"] = deep_data["image_url"] or result["image_url"]
                result["price"] = deep_data["price"] or result["price"]
                
                if result["image_url"] and result["price"] != "Preço não disponível":
                    return result

        # ELSE: Extração normal (ou se a recursividade falhou)
        normal_data = _extract_from_html(html, final_url)
        result["title"] = normal_data["title"] or result["title"]
        result["image_url"] = normal_data["image_url"] or result["image_url"]
        result["price"] = normal_data["price"] or result["price"]

        # Heurística de Preço para TV (V3.5)
        if "TV" in result["title"].upper() and result["price"] != "Preço não disponível":
            p_val = float(result["price"].replace("R$ ", "").replace(".", "").replace(",", "."))
            if p_val < 300: result["price"] = "Preço não disponível" # Provavelmente acessório

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.6: {e}")
        result["error"] = str(e)

    return result
