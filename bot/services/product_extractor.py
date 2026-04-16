"""
product_extractor.py - Extração via SEO Emulation (Versão 6.0).
V6.0 (THE KEYMASTER) - Emulação de Googlebot para bypass total de 403.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

# O "Disfarce Master": Googlebot é a única entidade que o ML não ousa bloquear
_GOOGLEBOT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = re.sub(r'[^\d,.]', '', str(text).replace('\xa0', ' '))
    if not text: return None
    # Garante formato R$ X.XXX,XX
    if "," not in text:
        if "." in text and len(text.split(".")[-1]) == 2: text = text.replace(".", ",")
        else: text = text.replace(".", "") + ",00"
    return f"R$ {text}"

def _extract_seo_data(soup, html):
    """Extrai dados das tags de SEO e Redes Sociais (quase impossíveis de bloquear)."""
    data = {"title": None, "price": None, "image_url": None}
    
    # 🎯 TITULO (SEO Prioritário)
    data["title"] = (soup.find("meta", property="og:title") or {}).get("content") or \
                    (soup.find("meta", name="twitter:title") or {}).get("content") or \
                    (soup.title.string if soup.title else None)
    
    # Limpa "Mercado Livre" do título
    if data["title"]:
                        data["title"] = re.sub(r'Mercado Livre.*|\||-', '', data["title"], flags=re.IGNORECASE).strip()

    # 💰 PREÇO (SEO e JSON-LD)
    # Tenta metatags de produto
    p_meta = (soup.find("meta", property="product:price:amount") or {}).get("content")
    if p_meta: data["price"] = clean_price(p_meta)

    # Tenta JSON-LD
    if not data["price"]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                js = json.loads(script.string)
                items = js if isinstance(js, list) else [js]
                for item in items:
                    if item.get("@type") == "Product":
                        off = item.get("offers", {})
                        p = off.get("price") if isinstance(off, dict) else (off[0].get("price") if off else None)
                        if p: data["price"] = clean_price(str(p))
            except: continue

    # Tenta tags Andes UI (Visual) se os invisíveis falharem
    if not data["price"]:
        p_tag = soup.select_one(".andes-money-amount--main .andes-money-amount__fraction")
        if p_tag:
            val = p_tag.get_text().strip()
            cents = p_tag.parent.select_one(".andes-money-amount__cents")
            if cents: val += f",{cents.get_text().strip()}"
            data["price"] = clean_price(val)

    # 🖼️ IMAGEM (OG Image)
    data["image_url"] = (soup.find("meta", property="og:image") or {}).get("content") or \
                        (soup.find("meta", name="twitter:image") or {}).get("content")
    
    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V6.0 (GOOGLEBOT) --- {url[:40]}")

    try:
        session = requests.Session()
        # Primeira tentativa como Googlebot (Página Original)
        res = session.get(url, headers=_GOOGLEBOT_HEADERS, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        result["loja"], result["store_key"] = detect_store(final_url)

        # Se for /social/, precisamos achar o MLB e ir pra lá como Googlebot
        if "/social/" in final_url:
            code = re.search(r'short_name=([^&"]+)', url)
            code = code.group(1) if code else ""
            m_link = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html) or \
                     re.search(r'https?://[^"\s]*MLB-?\d+[^"\s>]*', html)
            
            if m_link:
                real_url = m_link.group(0).replace("&amp;", "&")
                logger.info(f"[EXTRACTOR] Googlebot entrando na fonte: {real_url}")
                res_real = session.get(real_url, headers=_GOOGLEBOT_HEADERS, timeout=10)
                soup = BeautifulSoup(res_real.text, "html.parser")
                html = res_real.text

        # Extração via SEO (Método mais difícil de bloquear)
        seo_data = _extract_seo_data(soup, html)
        result.update({k: v for k, v in seo_data.items() if v})

        # Cleanup final
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V6.0: {e}")
        result["error"] = str(e)

    return result
