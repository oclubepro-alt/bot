"""
product_extractor.py - Extração definitiva via JSON-LD e Redirecionamento (V4.1).
Versão V4.1 (THE FINISHER) - Extração ultra-robusta focada em metadados estruturados.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_BR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://www.google.com.br/",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = str(text).replace("\xa0", " ").replace(".", "").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        val = float(match.group(1))
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return None

def _extract_from_json_ld(soup):
    """Extrai dados do JSON-LD (Padrão Schema.org que o ML usa)."""
    data = {"title": None, "price": None, "image_url": None}
    try:
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                content = json.loads(script.string)
                # O ML coloca uma lista ou um objeto direto
                items = content if isinstance(content, list) else [content]
                for item in items:
                    if item.get("@type") == "Product":
                        if not data["title"]: data["title"] = item.get("name")
                        if not data["image_url"]: data["image_url"] = item.get("image")
                        offers = item.get("offers", {})
                        if isinstance(offers, dict):
                            price = offers.get("price")
                            if price: data["price"] = clean_price(str(price))
                        elif isinstance(offers, list) and offers:
                            price = offers[0].get("price")
                            if price: data["price"] = clean_price(str(price))
            except: continue
    except: pass
    return data

def _scrape_html_fallback(soup):
    """Fallback manual caso o JSON-LD falhe."""
    data = {"title": None, "price": None, "image_url": None}
    
    # Título
    t = soup.select_one(".ui-pdp-title") or soup.select_one("h1")
    if t: data["title"] = t.get_text().strip()
    
    # Preço principal (evitando riscados)
    p_tags = soup.select(".andes-money-amount--main .andes-money-amount__fraction")
    if p_tags:
        val = p_tags[0].get_text().strip()
        cents = p_tags[0].parent.select_one(".andes-money-amount__cents")
        if cents: val += f",{cents.get_text().strip()}"
        data["price"] = clean_price(val)
        
    # Imagem
    img = soup.select_one(".ui-pdp-gallery__figure img") or soup.select_one("img.ui-pdp-image")
    if img: data["image_url"] = img.get("data-zoom") or img.get("src")
    
    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V4.1 (THE FINISHER) --- {url[:40]}")

    try:
        session = requests.Session()
        # Segue redirecionamentos manualmente para não perder cookies
        res = session.get(url, headers=_BR_HEADERS, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        # Detecta loja no URL final
        store_display, store_key = detect_store(final_url)
        result["loja"], result["store_key"] = store_display, store_key

        # 1. Tenta JSON-LD (Mais estável)
        ld_data = _extract_from_json_ld(soup)
        
        # 2. Tenta HTML Fallback
        html_data = _scrape_html_fallback(soup)
        
        # Merge inteligente
        result["title"] = ld_data["title"] or html_data["title"] or "Produto"
        result["price"] = ld_data["price"] or html_data["price"] or "Preço não disponível"
        result["image_url"] = ld_data["image_url"] or html_data["image_url"]

        # 3. Recursividade para Social (Se ainda estivermos em /social/)
        if "/social/" in final_url and result["title"] in ["Produto", "Perfil Social"]:
            logger.info("[EXTRACTOR] Detectada vitrine social ainda. Caçando link MLB...")
            # Pega o link da TV baseado no short_name do URL original
            q_orig = parse_qs(urlparse(url).query)
            target_short = q_orig.get("short_name", [url.split("/")[-1]])[0]
            
            m = re.search(fr'https?://[^"\s]*{target_short}[^"\s]*MLB[^"\s>]*', html)
            if m:
                real_url = m.group(0).replace("&amp;", "&")
                logger.info(f"[EXTRACTOR] Indo para a fonte definitiva: {real_url}")
                res_real = session.get(real_url, headers=_BR_HEADERS, timeout=10)
                final_soup = BeautifulSoup(res_real.text, "html.parser")
                final_data = _extract_from_json_ld(final_soup)
                final_html = _scrape_html_fallback(final_soup)
                
                if final_data["title"]: result["title"] = final_data["title"]
                if final_data["price"] and final_data["price"] != "Preço não disponível": result["price"] = final_data["price"]
                if final_data["image_url"]: result["image_url"] = final_data["image_url"]
                
                # Fallback do fallback
                if result["title"] == "Produto": result["title"] = final_html["title"] or "Produto"

        # Limpeza final de URL de imagem
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V4.1: {e}")
        result["error"] = str(e)

    return result
