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
    """Tenta extrair uma URL embutida em parâmetros de afiliados (ex: Rakuten/Awin)."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    
    # Rakuten usa 'murl'
    if "murl" in qs:
        return unquote(qs["murl"][0])
    # Awin usa 'ued'
    if "ued" in qs:
        return unquote(qs["ued"][0])
    # Outros comuns (url, dest)
    for param in ["url", "dest"]:
        if param in qs and qs[param][0].startswith("http"):
            return unquote(qs[param][0])
            
    return url


def resolve_url(url: str, timeout: int = 12) -> str:
    url = url.strip()
    logger.info(f"[URL_RESOLVER] Resolvendo: {url[:100]}")

    try:
        # Configuração de proxy para PythonAnywhere
        proxies = {
            "http": "http://proxy.server:3128",
            "https": "http://proxy.server:3128",
        }
        
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
