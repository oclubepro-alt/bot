"""
product_extractor.py - Versão 5.2 (Money Maker).
V5.2 - Foco em seletores de preço de vitrine social e metadados de descrição.
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
    # Remove tudo exceto números, pontos e vírgulas
    text = re.sub(r'[^\d,.]', '', str(text).replace('\xa0', ' '))
    if not text: return None
    # Se não tem vírgula, assume que o ponto é decimal ou adiciona ,00
    if "," not in text:
        if "." in text:
            parts = text.split(".")
            if len(parts[-1]) == 2: text = text.replace(".", ",")
            else: text = text.replace(".", "") + ",00"
        else:
            text += ",00"
    return f"R$ {text}"

def _extract_all(soup, html):
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. JSON-LD
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

    # 2. Título
    t = soup.select_one(".ui-pdp-title") or soup.select_one("h1") or soup.select_one(".social-vitrine-item__title")
    if t: data["title"] = data["title"] or t.get_text().strip()
    
    # 3. Preço (Aumentando cobertura de seletores)
    price_selectors = [
        ".andes-money-amount--main .andes-money-amount__fraction",
        ".ui-pdp-price__second-line .andes-money-amount__fraction",
        ".social-vitrine-item__price",
        ".price-tag-fraction",
        "[itemprop='price']"
    ]
    for sel in price_selectors:
        p_tag = soup.select_one(sel)
        if p_tag:
            p_val = p_tag.get_text().strip()
            # Tenta pegar centavos se estiverem perto
            cents = p_tag.parent.select_one(".andes-money-amount__cents") or p_tag.parent.select_one(".price-tag-cents")
            if cents: p_val += f",{cents.get_text().strip()}"
            data["price"] = data["price"] or clean_price(p_val)
            if data["price"]: break

    # 4. Fallback de Descrição (Muitas vezes o preço está aqui)
    if not data["price"]:
        desc = (soup.find("meta", property="og:description") or {}).get("content") or ""
        # Procura padrão R$ 1.234,56
        m_price = re.search(r'R\$\s?(\d+[\.,]\d{2})', desc) or re.search(r'por\s?(\d+[\.,]\d{2})', desc)
        if m_price:
            data["price"] = clean_price(m_price.group(1))

    # 5. Imagem
    img = soup.select_one(".ui-pdp-gallery__figure img") or \
          soup.select_one("img.ui-pdp-image") or \
          soup.select_one(".social-vitrine-item__image img") or \
          (soup.find("meta", property="og:image") or {}).get("content")
    if img:
        url = img if isinstance(img, str) else (img.get("data-zoom") or img.get("src"))
        data["image_url"] = data["image_url"] or url

    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V5.2 (MONEY MAKER) --- {url[:40]}")

    try:
        headers = {"User-Agent": random.choice(_USER_AGENTS)}
        session = requests.Session()
        res = session.get(url, headers=headers, timeout=15)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        result["loja"], result["store_key"] = detect_store(final_url)

        # Extração em profundidade
        data = _extract_all(soup, html)
        result.update({k: v for k, v in data.items() if v})

        # Recursividade Social
        if "/social/" in final_url:
            m_code = re.search(r'MLB-?\d+', html) or re.search(r'short_name=([^&"]+)', url)
            code = m_code.group(0) if m_code else ""
            if code:
                m_link = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html)
                if m_link:
                    real_url = m_link.group(0).replace("&amp;", "&")
                    logger.info(f"[EXTRACTOR] Indo para página real: {real_url}")
                    res_f = session.get(real_url, headers=headers, timeout=10)
                    final_data = _extract_all(BeautifulSoup(res_f.text, "html.parser"), res_f.text)
                    if final_data["title"] and len(final_data["title"]) > 10: result["title"] = final_data["title"]
                    if final_data["price"] and final_data["price"] != "Preço não disponível": result["price"] = final_data["price"]
                    if final_data["image_url"]: result["image_url"] = final_data["image_url"]

        if result["title"]: result["title"] = re.sub(r'Mercado Livre.*|\||-', '', result["title"], flags=re.IGNORECASE).strip()
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V5.2: {e}")
        result["error"] = str(e)

    return result
