"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.4 (INFILTRATOR MAX) - Bypassing 403 e detecção de vitrine social profunda.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

# Headers de navegação real para evitar 403
_HEADERS_ANTI_BLOCK = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
    "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
    "Sec-Ch-Ua-Mobile": "?0",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = text.replace("\xa0", " ").strip()
    # Padrão: R$ 1.234,56 ou apenas 1.234,56
    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", text)
    if match:
        val = match.group(1)
        if "," not in val: val += ",00"
        return f"R$ {val}"
    return None

def _meta(soup, *props):
    for prop in props:
        tag = soup.find("meta", property=prop) or soup.find("meta", {"name": prop})
        if tag and tag.get("content"): return tag["content"].strip()
    return None

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, 
        "price": "Preço não disponível", 
        "title": "Produto", 
        "loja": "Desconhecida", 
        "store_key": "other",
        "error": None
    }
    logger.info(f"[EXTRACTOR] --- INFILTRATOR MAX V3.4 --- {url[:50]}")

    try:
        # Usamos uma sessão para manter cookies e simular navegação melhor
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        html = res.text
        soup = BeautifulSoup(html, "html.parser")
        
        final_url = res.url
        store_display, store_key = detect_store(final_url)
        result["loja"] = store_display
        result["store_key"] = store_key

        # 1. Título Sniper (Melhorado para Vitrines ML)
        og_t = _meta(soup, "og:title", "twitter:title")
        og_d = _meta(soup, "og:description", "twitter:description")
        
        candidates = [og_t, og_d]
        for c in candidates:
            if not c or len(c) < 10: continue
            # Limpa lixo de marketing
            clean = re.sub(r"Visite a página.*|Mercado Livre|Descontinho.*|\||-|Encontre os melhores.*|Veja este produto.*", "", c, flags=re.IGNORECASE).strip()
            if len(clean) > 15:
                result["title"] = clean
                break

        # 2. Imagem Sniper (Busca em profundidade no HTML)
        tags_img = [
            "og:image", "og:image:secure_url", "og:image:url", 
            "twitter:image", "twitter:image:src", "thumbnail"
        ]
        og_i = _meta(soup, *tags_img)
        
        if og_i and "mercadolivre.com.br" in og_i:
            result["image_url"] = og_i
        else:
            # Tenta encontrar a primeira imagem que pareça ser do produto
            # MLB imagens são as oficiais de produtos
            found_img = re.search(r'https://http2\.mlstatic\.com/D_NQ_NP_(\d+)-MLB(\d+)-F\.jpg', html)
            if found_img:
                result["image_url"] = found_img.group(0)
            else:
                # Procura por qualquer imagem grande no corpo
                img_tag = soup.select_one("img[src*='MLB']") or soup.select_one("img.nav-header-logo")
                if img_tag:
                    result["image_url"] = urljoin(final_url, img_tag.get("data-src") or img_tag.get("src"))

        # 3. Preço Sniper (Regex agressivo se meta falhar)
        og_p = _meta(soup, "product:price:amount", "og:price:amount", "og:price", "twitter:data1")
        if og_p:
            result["price"] = clean_price(og_p)
            
        if result["price"] == "Preço não disponível":
            # Procura por padrões de preço em JSON ou texto
            # Padrão: "price": 1234.56 ou R$ 1.234,56
            js_price = re.search(r'"price":\s*(\d+(?:\.\d{1,2})?)', html)
            if js_price:
                result["price"] = clean_price(js_price.group(1))
            else:
                # Procura no HTML bruto perto de onde o nome do produto aparece
                price_match = re.search(r'R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})', html)
                if price_match:
                    result["price"] = f"R$ {price_match.group(1)}"

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.4: {e}")
        result["error"] = str(e)

    return result
