"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.9 (FINAL STRIKE) - Link mapping por short_name e coerência de categoria.
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
    """Extração minuciosa de dados de uma página de produto Mercado Livre."""
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. Título (Prioridade H1)
    t_tag = soup.select_one(".ui-pdp-title") or soup.select_one("h1")
    if t_tag: data["title"] = t_tag.get_text().strip()

    # 2. Imagem (og:image é excelente em páginas reais)
    og_i = (soup.find("meta", property="og:image") or {}).get("content")
    if og_i and "mlstatic" in og_i:
        data["image_url"] = og_i
    else:
        img_tag = soup.select_one(".ui-pdp-gallery__figure img") or soup.select_one("img.ui-pdp-image")
        if img_tag: data["image_url"] = img_tag.get("data-zoom") or img_tag.get("data-src") or img_tag.get("src")

    # 3. Preço (Priorizando o preço da oferta principal)
    # Buscamos o container da "segunda linha" onde fica o preço Pix/Oferta
    p_main = soup.select_one(".ui-pdp-price__second-line .andes-money-amount__fraction") or \
             soup.select_one(".andes-money-amount--main .andes-money-amount__fraction")
    
    if p_main:
        price_str = p_main.get_text().strip()
        cents = p_main.parent.select_one(".andes-money-amount__cents")
        if cents: price_str += f",{cents.get_text().strip()}"
        data["price"] = clean_price(price_str)
    
    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- FINAL STRIKE V3.9 --- {url[:50]}")

    try:
        # Extrair o short_name do link original para não pegar o produto errado
        parsed_orig = urlparse(url)
        q_orig = parse_qs(parsed_orig.query)
        target_short = q_orig.get("short_name", [parsed_orig.path.split("/")[-1]])[0]

        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        store_display, store_key = detect_store(final_url)
        result["loja"], result["store_key"] = store_display, store_key

        # SE FOR VITRINE SOCIAL: Buscar o link MLB que contenha o nosso short_name
        if "/social/" in final_url:
            logger.info(f"[EXTRACTOR] Vitrine detectada. Caçando link com short_name: {target_short}")
            # Procura links que tenham o short_name no href (comum no ML social)
            links_social = soup.find_all("a", href=re.compile(target_short))
            real_url = None
            if links_social:
                real_url = urljoin(final_url, links_social[0]["href"])
            else:
                # Fallback: pega o primeiro link de produto MLB que aparecer
                m_links = re.findall(r'https?://[^"\s]*MLB[^"\s>]*', html)
                if m_links: real_url = m_links[0]
            
            if real_url:
                logger.info(f"[EXTRACTOR] Indo para página real: {real_url}")
                res_real = session.get(real_url, headers=_HEADERS_ANTI_BLOCK, timeout=10)
                deep_data = _scrape_full_page(BeautifulSoup(res_real.text, "html.parser"), res_real.text)
                result.update({k: v for k, v in deep_data.items() if v})

        # Se não fomos por recursividade ou ela falhou, tenta extração direta
        if result["price"] == "Preço não disponível":
            direct_data = _scrape_full_page(soup, html)
            result.update({k: v for k, v in direct_data.items() if v})

        # --- VALIDAÇÕES FINAIS ---
        # 1. Filtro de Coerência (TV vs Suporte)
        if "TV" in result["title"].upper():
            try:
                p_val = float(result["price"].replace("R$ ", "").replace(".", "").replace(",", "."))
                if p_val < 400: # Preço de suporte/acessório
                    logger.warning(f"[EXTRACTOR] Preço detectado ({p_val}) é baixo demais para uma TV. Resetando.")
                    result["price"] = "Preço não disponível"
            except: pass

        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.9: {e}")
        result["error"] = str(e)

    return result
