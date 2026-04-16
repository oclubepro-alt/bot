"""
product_extractor.py - Extração robusta de dados do produto via scraping.
Versão V3.5 (SHADOW TRACER) - Localização de item específico em vitrines sociais via ID.
"""
import logging
import re
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs

from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

_HEADERS_ANTI_BLOCK = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Referer": "https://www.mercadolivre.com.br/",
}

def clean_price(text: str) -> str | None:
    if not text: return None
    text = text.replace("\xa0", " ").strip()
    match = re.search(r"(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)", text)
    if match:
        val = match.group(1)
        if "," not in val: val += ",00"
        return f"R$ {val}"
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
    logger.info(f"[EXTRACTOR] --- SHADOW TRACER V3.5 --- {url[:50]}")

    try:
        # Tenta pegar o short_name do link (ex: 22yDfB2)
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        short_name = params.get("short_name", [parsed.path.split("/")[-1]])[0]
        
        session = requests.Session()
        res = session.get(url, headers=_HEADERS_ANTI_BLOCK, timeout=15, allow_redirects=True)
        html = res.text
        soup = BeautifulSoup(html, "html.parser")
        
        final_url = res.url
        store_display, store_key = detect_store(final_url)
        result["loja"] = store_display
        result["store_key"] = store_key

        # 1. Título via Meta (Geralmente é confiável para o item principal)
        og_t = (soup.find("meta", property="og:title") or {}).get("content")
        og_d = (soup.find("meta", property="og:description") or {}).get("content")
        
        for c in [og_t, og_d]:
            if not c: continue
            clean = re.sub(r"Visite a página.*|Mercado Livre|Descontinho.*|\||-|Encontre os melhores.*|Veja este produto.*", "", c, flags=re.IGNORECASE).strip()
            if len(clean) > 15:
                result["title"] = clean
                break

        # 2. Busca o Bloco de Dados do Item Específico (Sniper Index)
        # Em vitrines sociais, os dados ficam em scripts ou em cards com o ID do short_name
        
        # Estratégia de Imagem: Busca pela imagem que contenha o ID do produto ou seja a maior da página
        ml_imgs = re.findall(r'https://http2\.mlstatic\.com/D_NQ_NP_[^"\s]+\.jpg', html)
        if ml_imgs:
            # Pega a primeira que não seja um ícone pequeno (F.jpg ou O.jpg são melhores)
            for img in ml_imgs:
                if "-F.jpg" in img or "-O.jpg" in img:
                    result["image_url"] = img
                    break
            if not result["image_url"]: result["image_url"] = ml_imgs[0]

        # Estratégia de Preço: Procura o preço PRÓXIMO ao título no HTML
        # Se for uma TV, o preço deve ser > 400.00
        all_prices = re.findall(r'R\$\s?(\d{1,3}(?:\.\d{3})*,\d{2})', html)
        valid_prices = []
        for p in all_prices:
            val_float = float(p.replace(".", "").replace(",", "."))
            # Heurística: Se o título tem "TV", ignoramos preços < 300 reais (provavelmente acessórios)
            if "TV" in result["title"].upper() and val_float < 400:
                continue
            valid_prices.append(p)
        
        if valid_prices:
            result["price"] = f"R$ {valid_prices[0]}"
        elif og_d:
            # Tenta extrair preço da descrição meta
            p_desc = clean_price(og_d)
            if p_desc: result["price"] = p_desc

        # Fallback de Imagem se ainda não tiver
        if not result["image_url"]:
            img_meta = (soup.find("meta", property="og:image") or {}).get("content")
            if img_meta: result["image_url"] = img_meta

    except Exception as e:
        logger.error(f"[EXTRACTOR] Erro V3.5: {e}")
        result["error"] = str(e)

    return result
