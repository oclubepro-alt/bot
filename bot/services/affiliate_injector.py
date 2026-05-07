"""
affiliate_injector.py — Injeção de parâmetros de afiliado por loja.

Regras (Sniper V6.5):
  AMAZON        → adiciona ?tag=ID
  MERCADO LIVRE → adiciona ?matt_from=ID
  MAGALU        → adiciona ?utm_medium=affiliate&utm_source=ID
  SHOPEE        → adiciona ?af_id=ID
  NETSHOES      → gateway Rakuten
"""
import re
import logging
import os
from urllib.parse import urlparse, urlencode, parse_qs, urljoin
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IDs de afiliado lidos do ambiente
# ---------------------------------------------------------------------------
_IDS: dict[str, str] = {
    "amazon":       os.getenv("AFFILIATE_ID_AMAZON", "").strip(),
    "mercadolivre": os.getenv("AFFILIATE_ID_ML", "").strip(),
    "magalu":       os.getenv("AFFILIATE_ID_MAGALU", "").strip(),
    "netshoes":     os.getenv("AFFILIATE_ID_NETSHOES", "").strip(),
    "shopee":       os.getenv("AFFILIATE_ID_SHOPEE", "").strip(),
}

# ---------------------------------------------------------------------------
# Regras por loja (Sniper V6.5)
# ---------------------------------------------------------------------------

def _inject_amazon(url: str, tag: str) -> str:
    """Amazon: tag=ID"""
    url = re.sub(r"[?&]tag=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}tag={tag}"

def _inject_mercadolivre(url: str, tag: str) -> str:
    """Mercado Livre: matt_from=ID"""
    url = re.sub(r"[?&](matt_from|matt_tool)=[^&]*", "", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}matt_from={tag}"

def _inject_magalu(url: str, id_magalu: str) -> str:
    """Magalu: utm_medium=affiliate&utm_source=ID"""
    url = re.sub(r"[?&]utm_(source|medium)=[^&]*", "", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_medium=affiliate&utm_source={id_magalu}"

def _inject_shopee(url: str, shopee_id: str) -> str:
    """Shopee: af_id=ID"""
    url = re.sub(r"[?&]af_id=[^&]*", "", url)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}af_id={shopee_id}"

def _inject_netshoes(url: str, ns_id: str) -> str:
    from urllib.parse import quote
    encoded_url = quote(url, safe="")
    return f"https://click.linksynergy.com/deeplink?id={ns_id}&mid=43984&murl={encoded_url}"

# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------

def inject_affiliate(url: str, store_key: str = None) -> str:
    """Injeta a tag conforme a loja detectada na URL."""
    if not url or not isinstance(url, str):
        return url

    # Limpeza nuclear: Remove parâmetros de rastro/afiliação de terceiros antes de injetar
    # Remove utm_*, fbclid, gclid e tags comuns
    url = re.sub(r"[?&](utm_[^&]+|fbclid|gclid|aff_id|clickid)=[^&]*", "", url)
    
    if not store_key:
        from bot.utils.detect_store import detect_store
        _, store_key = detect_store(url)

    tag = _IDS.get(store_key, "").strip()
    if not tag:
        return url

    try:
        if store_key == "amazon": return _inject_amazon(url, tag)
        if store_key == "mercadolivre": return _inject_mercadolivre(url, tag)
        if store_key == "magalu": return _inject_magalu(url, tag)
        if store_key == "shopee": return _inject_shopee(url, tag)
        if store_key == "netshoes": return _inject_netshoes(url, tag)
    except Exception as e:
        logger.error(f"[INJECTOR] Erro ao injetar em {url}: {e}")
    return url

def aplicar_link_afiliado(texto: str) -> str:
    """
    Função Mestra: Scaneia o texto, encontra URLs e as converte.
    Garante que NADA saia sem tag.
    """
    if not texto: return texto
    urls = re.findall(r'(https?://[^\s<>"]+)', texto)
    novo_texto = texto
    for url in set(urls):
        if any(x in url for x in ["amzn.to", "shope.ee", "t.me", "mercadolivre.com/sec/"]):
            continue
        url_afiliada = inject_affiliate(url)
        if url_afiliada != url:
            novo_texto = novo_texto.replace(url, url_afiliada)
            logger.info(f"✅ [SNIPER] Link convertido no texto final: {url[:25]}... -> {url_afiliada[:25]}...")
    return novo_texto

def get_affiliate_url(original_url: str, resolved_url: str | None, store_key: str) -> str:
    """Wrapper para fluxos estruturados."""
    target = (resolved_url or original_url or "").strip()
    injected = inject_affiliate(target, store_key)
    return injected if injected != target else target
