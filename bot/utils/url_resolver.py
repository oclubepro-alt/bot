import logging
import requests
from urllib.parse import urlparse, parse_qs, unquote

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

def extract_from_query(url: str) -> str:
    """Tenta extrair uma URL embutida em parâmetros de afiliados (ex: Viglink, Rakuten/Awin)."""
    if not url: return url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    
    # Parâmetros comuns de redirecionamento de afiliados
    # u = Viglink, murl = Rakuten, ued = Awin
    keys_to_check = ["u", "murl", "ued", "url", "dest", "link", "redir", "target"]
    
    for key in keys_to_check:
        # Busca case-insensitive
        actual_key = next((k for k in qs.keys() if k.lower() == key), None)
        if actual_key:
            potential_url = unquote(qs[actual_key][0])
            if potential_url.startswith("http"):
                logger.info(f"[URL_RESOLVER] URL extraída do parâmetro '{actual_key}': {potential_url[:60]}...")
                return potential_url
            
    return url


def resolve_url(url: str, timeout: int = 12) -> str:
    url = url.strip()
    logger.info(f"[URL_RESOLVER] Resolvendo: {url[:100]}")

    try:
        from bot.utils.config import HTTP_PROXY
        proxies = {
            "http": HTTP_PROXY,
            "https": HTTP_PROXY,
        } if HTTP_PROXY else None
        
        # Usamos GET porque HEAD frequentemente é bloqueado ou ignorado por shorteners
        resp = requests.get(
            url,
            headers=_HEADERS,
            allow_redirects=True,
            timeout=timeout,
            stream=True,   # Evita baixar o body pesado
            proxies=proxies,
        )
        final = resp.url
        resp.close()
        
        # Resolve redirecionadores via parâmetro no caso de cair em interstitial de afiliado
        final = extract_from_query(final)

        if final and final != url:
            logger.info(f"[URL_RESOLVER] ✅ GET OK → {final[:100]}")
        else:
            logger.info("[URL_RESOLVER] GET: URL não redirecionada (já é final).")
            final = url
        return final
    except Exception as e_get:
        logger.warning(f"[URL_RESOLVER] GET falhou ({e_get}). Tentando URL original.")
        return url
