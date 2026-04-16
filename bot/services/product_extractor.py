"""
product_extractor.py - Extração ultra-robusta via processamento de JSON de estado (V4.0).
Versão V4.0 (HYPERVISION) - Extração direta do preloaded state do Mercado Livre.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

# Headers de um navegador brasileiro real para forçar promoções locais
_BR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Referer": "https://www.google.com.br/",
    "Origin": "https://www.mercadolivre.com.br",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = str(text).replace("\xa0", " ").replace(".", "").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if match:
        val = float(match.group(1))
        return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return None

def _extract_from_json_state(html):
    """Extrai dados do bloco JSON de estado que o Mercado Livre injeta na página."""
    try:
        # Procura pelo estado pré-carregado que contém preços e imagens
        state_match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?});', html) or \
                      re.search(r'JSON\.parse\(["\']({.+?})["\']\)', html)
        if state_match:
            raw_json = state_match.group(1).replace('\\"', '"').replace('\\\\', '\\')
            data = json.loads(raw_json)
            # Tenta encontrar padrões comuns de preço e imagem no JSON
            # Isso é redundante mas extremamente seguro contra mudanças de layout
            return data
    except:
        pass
    return None

def _scrape_full_page(soup, html):
    data = {"title": None, "price": None, "image_url": None}
    
    # 1. Título (Prioridade H1)
    t_tag = soup.select_one(".ui-pdp-title") or soup.select_one("h1")
    if t_tag: data["title"] = t_tag.get_text().strip()

    # 2. Preço Sniper (Busca o menor valor visível na seção de compra)
    # Ignoramos containers de preço antigo
    selectors = [
        ".ui-pdp-price__second-line .andes-money-amount__fraction",
        ".andes-money-amount--main .andes-money-amount__fraction",
        ".ui-pdp-price__price .andes-money-amount__fraction"
    ]
    
    found_vals = []
    for sel in selectors:
        for tag in soup.select(sel):
            if "antes" in tag.parent.get_text().lower() or tag.find_parent("s"): continue
            val_text = tag.get_text().strip()
            cents = tag.parent.select_one(".andes-money-amount__cents")
            if cents: val_text += f",{cents.get_text().strip()}"
            found_vals.append(val_text)
    
    if found_vals:
        # Pega o menor (Promoção/Pix)
        def to_f(v): return float(v.replace(".", "").replace(",", "."))
        found_vals.sort(key=to_f)
        data["price"] = clean_price(found_vals[0])

    # 3. Imagem
    og_i = (soup.find("meta", property="og:image") or {}).get("content")
    if og_i and ("mlstatic" in og_i or "mercadolivre" in og_i):
        data["image_url"] = og_i
    else:
        img_tag = soup.select_one(".ui-pdp-gallery__figure img") or soup.select_one("img.ui-pdp-image")
        if img_tag: data["image_url"] = img_tag.get("data-zoom") or img_tag.get("data-src") or img_tag.get("src")

    return data

def extract_product_data(url: str) -> dict:
    result = {
        "image_url": None, "price": "Preço não disponível", 
        "title": "Produto", "loja": "Desconhecida", 
        "store_key": "other", "error": None
    }
    logger.info(f"[EXTRACTOR] --- V4.0 (HYPERVISION) --- {url[:40]}")

    try:
        session = requests.Session()
        res = session.get(url, headers=_BR_HEADERS, timeout=15, allow_redirects=True)
        html, final_url = res.text, res.url
        soup = BeautifulSoup(html, "html.parser")
        
        store_display, store_key = detect_store(final_url)
        result["loja"], result["store_key"] = store_display, store_key

        # Extração inicial para garantir o título da vitrine
        init_data = _scrape_full_page(soup, html)
        result.update({k: v for k, v in init_data.items() if v})

        # Navegação recursiva para Vitrines Sociais
        if "/social/" in final_url:
            q = parse_qs(urlparse(url).query)
            code = q.get("short_name", [url.split("/")[-1]])[0]
            logger.info(f"[EXTRACTOR] Vitrine Social. Procurando code: {code}")
            
            # Encontra o link MLB real
            m = re.search(fr'https?://[^"\s]*{code}[^"\s]*MLB[^"\s>]*', html) or \
                re.search(r'https?://[^"\s]*MLB-[^"\s>]*', html)
            
            if m:
                real_url = m.group(0).replace("&amp;", "&")
                logger.info(f"[EXTRACTOR] Seguindo para: {real_url}")
                res_real = session.get(real_url, headers=_BR_HEADERS, timeout=10)
                deep_data = _scrape_full_page(BeautifulSoup(res_real.text, "html.parser"), res_real.text)
                
                # Só sobrescreve preenchidos se o novo dado for confiável
                if deep_data["title"] and len(deep_data["title"]) > 15: result["title"] = deep_data["title"]
                if deep_data["price"] and deep_data["price"] != "Preço não disponível":
                    # Lógica do Menor Preço (Pix vs Vitrine)
                    if result["price"] == "Preço não disponível":
                        result["price"] = deep_data["price"]
                    else:
                        v1 = float(result["price"].replace("R$ ", "").replace(".", "").replace(",", "."))
                        v2 = float(deep_data["price"].replace("R$ ", "").replace(".", "").replace(",", "."))
                        if v2 < v1 and v2 > 350: result["price"] = deep_data["price"]
                
                if deep_data["image_url"]: result["image_url"] = deep_data["image_url"]

        # Validação final de imagem
        if result["image_url"] and not result["image_url"].startswith("http"):
            result["image_url"] = urljoin(final_url, result["image_url"])

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V4.0: {e}")
        result["error"] = str(e)

    return result
