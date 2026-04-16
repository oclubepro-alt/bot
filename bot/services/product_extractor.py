"""
product_extractor.py - Versão 6.3 (Railway Edition).
V6.3 - Fallbacks aprimorados para preço/título e diagnósticos de ambiente Railway.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_GOOGLEBOT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = re.sub(r'[^\d,.]', '', str(text).replace('\xa0', ' '))
    if not text: return None
    if "," not in text:
        if "." in text and len(text.split(".")[-1]) == 2: text = text.replace(".", ",")
        else: text = text.replace(".", "") + ",00"
    return f"R$ {text}"

def _extract_seo_data(soup, html):
    """Extração via metadados SEO e seletores visuais."""
    data = {"title": None, "price": None, "image_url": None, "descricao": None}
    
    # --- 1. TITULO ---
    t_og = soup.find(name="meta", attrs={"property": "og:title"})
    t_tw = soup.find(name="meta", attrs={"name": "twitter:title"})
    h1 = soup.find(name="h1")
    
    data["title"] = (t_og.get("content") if t_og else None) or \
                    (t_tw.get("content") if t_tw else None) or \
                    (h1.get_text().strip() if h1 else None) or \
                    (soup.title.string if soup.title else None)
    
    if data["title"]:
        data["title"] = re.sub(r'Mercado Livre.*|\||-|Smart TV', '', data["title"], flags=re.IGNORECASE).strip()
        if "AOC" in data["title"] and "Smart TV" not in data["title"]:
            data["title"] = f"Smart TV {data['title']}"

    # --- 2. PREÇO (Camadas de Precedência) ---
    # Camada A: Metadados estruturados (Invisível)
    p_meta = soup.find(name="meta", attrs={"property": "product:price:amount"})
    if p_meta: data["price"] = clean_price(p_meta.get("content"))

    # Camada B: JSON-LD
    if not data["price"]:
        for script in soup.find_all(name="script", attrs={"type": "application/ld+json"}):
            try:
                js = json.loads(script.string)
                items = js if isinstance(js, list) else [js]
                for item in items:
                    if item.get("@type") == "Product":
                        off = item.get("offers", {})
                        if isinstance(off, dict):
                            p = off.get("price")
                            if p: data["price"] = clean_price(str(p))
                        elif isinstance(off, list) and off:
                            p = off[0].get("price")
                            if p: data["price"] = clean_price(str(p))
            except: continue

    # Camada C: Seletores CSS Visuais (Específicos ML)
    if not data["price"]:
        # Tenta seletor principal do Mercado Livre
        price_selectors = [
            ".ui-pdp-price__second-line .andes-money-amount__fraction",
            ".andes-money-amount--main .andes-money-amount__fraction",
            ".price-tag-fraction",
            "[itemprop='price']"
        ]
        for sel in price_selectors:
            p_tag = soup.select_one(sel)
            if p_tag:
                val = p_tag.get_text().strip()
                # Tenta pegar centavos se houver
                parent = p_tag.parent
                cents = parent.select_one(".andes-money-amount__cents") or parent.select_one(".price-tag-cents")
                if cents:
                    val += f",{cents.get_text().strip()}"
                data["price"] = clean_price(val)
                if data["price"]: break

    # --- 3. IMAGEM ---
    img_og = soup.find(name="meta", attrs={"property": "og:image"})
    img_tw = soup.find(name="meta", attrs={"name": "twitter:image"})
    data["image_url"] = (img_og.get("content") if img_og else None) or \
                        (img_tw.get("content") if img_tw else None)
    
    # --- 4. DESCRIÇÃO ---
    desc_og = soup.find(name="meta", attrs={"property": "og:description"})
    if desc_og: data["descricao"] = desc_og.get("content")
    
    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V6.3 (RAILWAY) --- {url[:50]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_GOOGLEBOT_HEADERS, timeout=15, allow_redirects=True)
        
        logger.info(f"[EXTRACTOR] Status: {res.status_code} | Bytes: {len(res.text)}")
        
        if res.status_code != 200:
            logger.warning(f"[EXTRACTOR] Alerta: Recebido status {res.status_code}")

        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        result["loja"], result["store_key"] = detect_store(final_url)

        # Se for /social/ (ML)
        if "/social/" in final_url:
            m_code = re.search(r'MLB-?\d+', html) or re.search(r'short_name=([^&"]+)', url)
            code = m_code.group(0) if m_code else ""
            m_link = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html)
            
            if m_link:
                real_url = m_link.group(0).replace("&amp;", "&")
                logger.info(f"[EXTRACTOR] MLB Social detectado -> Seguindo para fonte: {real_url[:50]}")
                res_real = session.get(real_url, headers=_GOOGLEBOT_HEADERS, timeout=10)
                soup = BeautifulSoup(res_real.text, "html.parser")
                html = res_real.text

        # Extração
        final_data = _extract_seo_data(soup, html)
        result.update({k: v for k, v in final_data.items() if v})

        # Fix final da imagem
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V6.3: {e}")
        result["error"] = str(e)

    return result
