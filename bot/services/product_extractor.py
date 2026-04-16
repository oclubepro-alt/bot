"""
product_extractor.py - Versão 5.1 (Bug Hunter).
V5.1 - Correção de erro de regex e fallback agressivo de título.
"""
import logging
import re
import json
import requests
import random
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1"
]

def clean_price(text: str) -> str | None:
    if not text: return None
    text = re.sub(r'[^\d,.]', '', str(text).replace('\xa0', ' '))
    if not text: return None
    if "," not in text and "." not in text: text += ",00"
    return f"R$ {text}"

def _extract_text(html, pattern, group=1):
    """Extração segura de regex."""
    m = re.search(pattern, html)
    return m.group(group).strip() if m else None

def _extract_all(soup, html):
    data = {"title": None, "price": None, "image_url": None}
    
    # JSON-LD
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

    # HTML
    t = soup.select_one(".ui-pdp-title") or soup.select_one("h1") or soup.select_one(".social-vitrine-item__title")
    if t: data["title"] = data["title"] or t.get_text().strip()
    
    # Meta
    data["title"] = data["title"] or _extract_text(html, r'property="og:title"\s+content="([^"]+)"')
    data["image_url"] = data["image_url"] or _extract_text(html, r'property="og:image"\s+content="([^"]+)"')

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
    logger.info(f"[EXTRACTOR] --- V5.1 (BUG HUNTER) --- {url[:40]}")

    try:
        headers = {"User-Agent": random.choice(_USER_AGENTS)}
        session = requests.Session()
        res = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        result["loja"], result["store_key"] = detect_store(final_url)

        # 1. Tenta extrair da página atual (Vitrine ou Produto)
        initial = _extract_all(soup, html)
        result.update({k: v for k, v in initial.items() if v})

        # 2. Se for vitrine, tenta ir pro link MLB
        if "/social/" in final_url:
            # Busca código MLB de forma segura
            m_code = re.search(r'MLB-?\d+', html)
            code = m_code.group(0) if m_code else ""
            if code:
                m_link = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html)
                if m_link:
                    real_url = m_link.group(0).replace("&amp;", "&")
                    logger.info(f"[EXTRACTOR] Indo para página real: {real_url}")
                    res_f = session.get(real_url, headers=headers, timeout=10)
                    final_data = _extract_all(BeautifulSoup(res_f.text, "html.parser"), res_f.text)
                    # Atualiza mantendo o que já era bom
                    if final_data["title"] and len(final_data["title"]) > 10: result["title"] = final_data["title"]
                    if final_data["price"] and final_data["price"] != "Preço não disponível": result["price"] = final_data["price"]
                    if final_data["image_url"]: result["image_url"] = final_data["image_url"]

        # Limpeza final
        if result["title"]: result["title"] = re.sub(r'Mercado Livre.*|\||-', '', result["title"], flags=re.IGNORECASE).strip()
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V5.1: {e}")
        result["error"] = str(e)

    return result
