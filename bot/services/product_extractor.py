"""
product_extractor.py - Extração definitiva (Versão Omega).
V4.2 - Prioridade em busca de link real e suporte a vitrines sociais agressivo.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    # Pega apenas números, vírgulas e pontos
    text = re.sub(r'[^\d,.]', '', text.replace('\xa0', ' '))
    if not text: return None
    if "," not in text and "." not in text: text += ",00"
    elif "," not in text and "." in text:
        # Verifica se o ponto é separador de milhar ou decimal
        parts = text.split(".")
        if len(parts[-1]) != 2: text = text.replace(".", "") + ",00"
        else: text = text.replace(".", ",")
    return f"R$ {text}"

def _extract_data(soup):
    """Lógica unificada de extração (JSON-LD + HTML)."""
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. JSON-LD (Estatístico)
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            js = json.loads(script.string)
            items = js if isinstance(js, list) else [js]
            for item in items:
                if item.get("@type") == "Product":
                    data["title"] = data["title"] or item.get("name")
                    data["image_url"] = data["image_url"] or item.get("image")
                    off = item.get("offers", {})
                    p = off.get("price") if isinstance(off, dict) else (off[0].get("price") if off else None)
                    if p: data["price"] = data["price"] or clean_price(str(p))
        except: continue

    # 2. HTML (Visual)
    # Título
    t = soup.select_one(".ui-pdp-title") or soup.select_one("h1") or soup.select_one(".social-vitrine-item__title")
    if t: data["title"] = data["title"] or t.get_text().strip()
    
    # Imagem
    img = soup.select_one(".ui-pdp-gallery__figure img") or soup.select_one("img.ui-pdp-image") or soup.select_one(".social-vitrine-item__image img")
    if img: data["image_url"] = data["image_url"] or img.get("data-zoom") or img.get("src")
    
    # Preço
    p_tag = soup.select_one(".andes-money-amount--main .andes-money-amount__fraction") or \
            soup.select_one(".ui-pdp-price__second-line .andes-money-amount__fraction")
    if p_tag:
        p_val = p_tag.get_text().strip()
        cents = p_tag.parent.select_one(".andes-money-amount__cents")
        if cents: p_val += f",{cents.get_text().strip()}"
        data["price"] = data["price"] or clean_price(p_val)

    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V4.2 (OMEGA) --- {url[:40]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_HEADERS, timeout=15)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        result["loja"], result["store_key"] = detect_store(final_url)

        # Se for VITRINE SOCIAL: Forçar busca do link MLB antes de tudo
        if "/social/" in final_url:
            q = parse_qs(urlparse(url).query)
            code = q.get("short_name", [url.split("/")[-1]])[0]
            logger.info(f"[EXTRACTOR] Buscando link real para: {code}")
            
            # Regex sniper para achar o link do produto MLB dentro do HTML da vitrine
            m = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html) or \
                re.search(r'https?://[^"\s]*MLB-[^"\s>]*', html)
            
            if m:
                real_url = m.group(0).replace("&amp;", "&")
                logger.info(f"[EXTRACTOR] Pulando para página do produto: {real_url}")
                res_prod = session.get(real_url, headers=_HEADERS, timeout=10)
                prod_data = _extract_data(BeautifulSoup(res_prod.text, "html.parser"))
                result.update({k: v for k, v in prod_data.items() if v})

        # Extração de segurança (vitrine ou página direta)
        final_data = _extract_data(soup)
        for k, v in final_data.items():
            if v and (result[k] is None or result[k] in ["Produto", "Preço não disponível"]):
                result[k] = v

        # Fix final de imagem
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V4.2: {e}")
        result["error"] = str(e)

    return result
