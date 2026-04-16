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
    """Extração via metadados SEO e seletores visuais específicos."""
    data = {"title": None, "price": None, "image_url": None, "descricao": None}
    
    # --- 1. TITULO (Prioridade para o que o usuário vê) ---
    # Seletores específicos de lojas famosas (ML, Amazon, Magalu)
    title_selectors = [
        ".ui-pdp-title",          # Mercado Livre Produto
        ".ui-vpp-title",          # Mercado Livre VPP
        "#productTitle",           # Amazon
        "h1[itemprop='name']",     # Magalu/Generico
        ".header-product__title", # Netshoes
        ".product-name",          # Geral
    ]
    
    found_title = None
    for sel in title_selectors:
        tag = soup.select_one(sel)
        if tag and len(tag.get_text().strip()) > 15: # Evita pegar lixo
            found_title = tag.get_text().strip()
            logger.info(f"[EXTRACTOR] Título pego via seletor CSS: {sel}")
            break

    if not found_title or found_title.lower() == "mercado livre":
        t_og = soup.find(name="meta", attrs={"property": "og:title"})
        t_tw = soup.find(name="meta", attrs={"name": "twitter:title"})
        h1_gen = soup.find(name="h1")
        
        found_title = (t_og.get("content") if t_og else None) or \
                    (t_tw.get("content") if t_tw else None) or \
                    (h1_gen.get_text().strip() if h1_gen else None) or \
                    (soup.title.string if soup.title else None)

    if found_title:
        logger.info(f"[EXTRACTOR] Título Bruto: {found_title[:60]}")
        # Limpeza fina
        cleaned = re.sub(r'\s*[|–-]\s*Mercado Livre.*', '', found_title, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*[|–-]\s*Amazon\.com.*', '', cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.strip()
        
        if "AOC" in cleaned and "Smart TV" not in cleaned:
            cleaned = f"Smart TV {cleaned}"
        data["title"] = cleaned

    # --- 2. PREÇO (Camadas de Precedência) ---
    p_meta = soup.find(name="meta", attrs={"property": "product:price:amount"})
    if p_meta: data["price"] = clean_price(p_meta.get("content"))

    if not data["price"]:
        for script in soup.find_all(name="script", attrs={"type": "application/ld+json"}):
            try:
                js = json.loads(script.string)
                items = js if isinstance(js, list) else [js]
                for item in items:
                    # ML e outros podem usar esquemas aninhados
                    product_data = item if item.get("@type") == "Product" else None
                    if not product_data and isinstance(item.get("mainEntity"), dict):
                        if item["mainEntity"].get("@type") == "Product":
                            product_data = item["mainEntity"]
                    
                    if product_data:
                        off = product_data.get("offers", {})
                        if isinstance(off, dict):
                            p = off.get("price")
                            if p: data["price"] = clean_price(str(p))
                        elif isinstance(off, list) and off:
                            p = off[0].get("price")
                            if p: data["price"] = clean_price(str(p))
                    if data["price"]: break
            except: continue

    if not data["price"]:
        price_selectors = [
            ".ui-pdp-price__second-line .andes-money-amount__fraction",
            ".andes-money-amount--main .andes-money-amount__fraction",
            ".ui-pdp-price__part--main .andes-money-amount__fraction",
            ".ui-pdp-price .andes-money-amount__fraction",
            "[itemprop='price']",
            ".price-tag-fraction",
        ]
        for sel in price_selectors:
            p_tag = soup.select_one(sel)
            if p_tag:
                val = p_tag.get_text().strip()
                parent = p_tag.parent
                cents = parent.select_one(".andes-money-amount__cents") or \
                        parent.select_one(".price-tag-cents")
                if cents: val += f",{cents.get_text().strip()}"
                data["price"] = clean_price(val)
                if data["price"]:
                    logger.info(f"[EXTRACTOR] Preço pego via seletor: {sel}")
                    break

    # Fallback Extremo: Regex no HTML para preços R$
    if not data["price"]:
        match = re.search(r'R\$\s*(\d{1,3}(\.\d{3})*,\d{2})', html)
        if match:
            data["price"] = f"R$ {match.group(1)}"
            logger.info("[EXTRACTOR] Preço pego via Regex Fallback")

    # --- 3. IMAGEM ---
    img_og = soup.find(name="meta", attrs={"property": "og:image"})
    img_tw = soup.find(name="meta", attrs={"name": "twitter:image"})
    img_rel = soup.find(name="link", attrs={"rel": "image_src"})
    img_sel = soup.select_one(".ui-pdp-gallery__figure__image, .ui-pdp-image")
    
    data["image_url"] = (img_og.get("content") if img_og else None) or \
                        (img_tw.get("content") if img_tw else None) or \
                        (img_rel.get("href") if img_rel else None) or \
                        (img_sel.get("src") if img_sel else None)
    
    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V6.5 (SNIPER) --- {url[:50]}")

    try:
        from bot.utils.url_resolver import extract_from_query
        session = requests.Session()
        res = session.get(url, headers=_GOOGLEBOT_HEADERS, timeout=15, allow_redirects=True)
        html = res.text
        # Limpa o link final caso tenha caído em um redirecionador de afiliado (Viglink/etc)
        final_url = extract_from_query(res.url)
        soup = BeautifulSoup(html, "html.parser")
        
        result["loja"], result["store_key"] = detect_store(final_url)
        result["product_url"] = final_url  # Salva a URL limpa para uso posterior

        # /social/
        if "/social/" in final_url:
            m_code = re.search(r'MLB-?\d+', html) or re.search(r'short_name=([^&"]+)', url)
            code = m_code.group(0) if m_code else ""
            m_link = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html)
            if m_link:
                real_url = m_link.group(0).replace("&amp;", "&")
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
        logger.error(f"[EXTRACTOR] Erro V6.5: {e}")
        result["error"] = str(e)

    return result
