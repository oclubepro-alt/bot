"""
product_extractor.py - Extração Indestrutível (Versão 5.0).
V5.0 (SINGULARITY) - Mineração de dados brutos e rotação de User-Agents.
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
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1"
]

def clean_price(text: str) -> str | None:
    if not text: return None
    text = re.sub(r'[^\d,.]', '', str(text).replace('\xa0', ' '))
    if not text: return None
    if "," not in text and "." not in text: text += ",00"
    elif "," not in text and "." in text:
        parts = text.split(".")
        if len(parts[-1]) != 2: text = text.replace(".", "") + ",00"
        else: text = text.replace(".", ",")
    return f"R$ {text}"

def _brute_force_mining(html):
    """Procura por padrões de nome, preço e imagem no texto puro do HTML."""
    data = {"title": None, "price": None, "image_url": None}
    
    # Busca Nome (patterns comuns em scripts de analytics)
    m_name = re.search(r'"name"\s*:\s*"([^"]+)"', html) or \
             re.search(r'"title"\s*:\s*"([^"]+)"', html) or \
             re.search(r'<title>([^<]+)</title>', html)
    if m_name: 
        name = m_name.group(1).strip()
        if "Mercado Livre" not in name or len(name) > 30:
            data["title"] = name.split(" | ")[0].split(" - ")[0]

    # Busca Preço (patterns de valor decimal)
    m_price = re.search(r'"price"\s*:\s*"?(\d+[\.,]\d{2})"?', html) or \
              re.search(r'"amount"\s*:\s*(\d+\.?\d*)', html)
    if m_price:
        data["price"] = clean_price(m_price.group(1))

    # Busca Imagem
    m_img = re.search(r'"image"\s*:\s*"([^"]+)"', html) or \
            re.search(r'https?://[^"\s]*mlstatic\.com/[^"\s]*\-O\.jpg', html)
    if m_img:
        data["image_url"] = m_img.group(1).replace("\\/", "/")

    return data

def _extract_all(soup, html):
    """Extração unificada em camadas: JSON-LD -> HTML -> Regex Mining."""
    data = {"title": None, "price": None, "image_url": None}
    
    # Camada 1: JSON-LD
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

    # Camada 2: HTML Seletores
    t = soup.select_one(".ui-pdp-title") or soup.select_one("h1") or soup.select_one(".social-vitrine-item__title")
    if t: data["title"] = data["title"] or t.get_text().strip()
    
    p_tag = soup.select_one(".andes-money-amount--main .andes-money-amount__fraction") or \
            soup.select_one(".ui-pdp-price__second-line .andes-money-amount__fraction")
    if p_tag:
        p_val = p_tag.get_text().strip()
        cents = p_tag.parent.select_one(".andes-money-amount__cents")
        if cents: p_val += f",{cents.get_text().strip()}"
        data["price"] = data["price"] or clean_price(p_val)

    # Camada 3: Brute Force Regex (Mining)
    mining = _brute_force_mining(html)
    for k, v in mining.items():
        if v and (data[k] is None or data[k] == "Produto"):
            data[k] = v

    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V5.0 (SINGULARITY) --- {url[:40]}")

    try:
        ua = random.choice(_USER_AGENTS)
        headers = {"User-Agent": ua, "Accept": "*/*", "Accept-Language": "pt-BR,pt;q=0.9"}
        
        session = requests.Session()
        res = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        result["loja"], result["store_key"] = detect_store(final_url)

        # Trata Vitrine Social pulando direto pro produto
        if "/social/" in final_url:
            m_mlb = re.search(r'MLB-?\d+', html) or re.search(r'short_name=([^&"]+)', url)
            code = m_mlb.group(0) if m_mlb else ""
            m_link = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html)
            if m_link:
                real_url = m_link.group(0).replace("&amp;", "&")
                logger.info(f"[EXTRACTOR] Indo para página final: {real_url}")
                res_f = session.get(real_url, headers=headers, timeout=10)
                final_data = _extract_all(BeautifulSoup(res_f.text, "html.parser"), res_f.text)
                result.update({k: v for k, v in final_data.items() if v})

        # Extração de segurança
        fallback = _extract_all(soup, html)
        for k, v in fallback.items():
            if v and (result[k] is None or result[k] in ["Produto", "Preço não disponível"]):
                result[k] = v

        # Fix de URL
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V5.0: {e}")
        result["error"] = str(e)

    return result
