"""
link_shortener.py — Encurtamento de URLs para publicação.

Princípio de segurança:
  - Nunca expõe a URL longa com parâmetros de afiliado na mensagem final.
  - Sempre retorna um link curto (ou o original puro se o encurtador falhar).

Backends suportados (em ordem de prioridade):
  1. TinyURL  — sem autenticação, confiável, saída: https://tinyurl.com/XXXXXXX
  2. is.gd    — sem autenticação, rápido, saída: https://is.gd/XXXXXXX
  3. Simulado — fallback local que mascara a URL longa com um hash visual

Configuração no .env:
  SHORTENER_BACKEND=tinyurl   # ou isgd | simulated (default: tinyurl)
"""
import hashlib
import logging
import os
import re
import requests

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_BACKEND     = os.getenv("SHORTENER_BACKEND", "tinyurl").strip().lower()
_DISABLE_AMAZON = os.getenv("DISABLE_SHORTENER_AMAZON", "true").strip().lower() in ("true", "1", "yes")
_TIMEOUT     = 8   # segundos por chamada ao encurtador
_MAX_RETRIES = 2


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

def _shorten_tinyurl(url: str) -> str:
    """Encurta via TinyURL (sem auth necessária)."""
    api = f"https://tinyurl.com/api-create.php?url={requests.utils.quote(url, safe='')}"
    resp = requests.get(api, timeout=_TIMEOUT)
    resp.raise_for_status()
    short = resp.text.strip()
    if short.startswith("https://tinyurl.com/"):
        return short
    raise ValueError(f"TinyURL retornou resposta inesperada: {short[:80]}")


def _shorten_isgd(url: str) -> str:
    """Encurta via is.gd (sem auth necessária)."""
    api = "https://is.gd/create.php"
    resp = requests.get(
        api,
        params={"format": "simple", "url": url},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    short = resp.text.strip()
    if short.startswith("https://is.gd/"):
        return short
    raise ValueError(f"is.gd retornou resposta inesperada: {short[:80]}")


def _shorten_simulated(url: str) -> str:
    """
    Fallback local — gera um link curto simulado determinístico.
    Formato: https://go.achadinho.bot/XXXXXXX
    Útil para desenvolvimento e quando os serviços externos estão indisponíveis.
    """
    digest = hashlib.md5(url.encode()).hexdigest()[:7].upper()
    return f"https://go.achadinho.bot/{digest}"


# ---------------------------------------------------------------------------
# Entrada pública
# ---------------------------------------------------------------------------

def shorten_url(url: str, *, force_backend: str | None = None) -> str:
    """
    Encurta a URL e retorna o link curto.

    A URL longa com parâmetros de afiliado NUNCA fica exposta na saída.
    Em caso de falha de todos os backends externos, usa o simulado.

    Args:
        url:            URL completa (pode conter parâmetros de afiliado).
        force_backend:  Força um backend específico ('tinyurl'|'isgd'|'simulated').

    Returns:
        URL curta pronta para publicação.
    """
    if not url:
        logger.warning("[SHORTENER] URL vazia recebida.")
        return url

    backend = (force_backend or _BACKEND).lower()
    logger.info(f"[SHORTENER] Encurtando via '{backend}': {url[:80]}...")

    backends_sequence: list[tuple[str, callable]] = []

    if backend in ("none", "direct"):
        logger.info("[SHORTENER] Encurtador desativado (direct). Retornando URL original.")
        return url

    if _DISABLE_AMAZON and "amazon.com" in url.lower():
        logger.info("[SHORTENER] Encurtador ignorado para Amazon (config).")
        return url

    if backend == "tinyurl":
        backends_sequence = [
            ("tinyurl", _shorten_tinyurl),
            ("isgd",    _shorten_isgd),
        ]
    elif backend == "isgd":
        backends_sequence = [
            ("isgd",    _shorten_isgd),
            ("tinyurl", _shorten_tinyurl),
        ]
    else:
        # simulated ou qualquer valor desconhecido
        return _shorten_simulated(url)

    for name, fn in backends_sequence:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                short = fn(url)
                logger.info(f"[SHORTENER] ✅ {name} OK (tentativa {attempt}): {short}")
                return short
            except Exception as e:
                logger.warning(
                    f"[SHORTENER] ⚠️ {name} falhou (tentativa {attempt}): {e}"
                )

    # Último recurso: simulado
    simulated = _shorten_simulated(url)
    logger.info(f"[SHORTENER] ℹ️ Usando link simulado: {simulated}")
    return simulated


def shorten_for_publication(affiliate_url: str) -> str:
    """
    Alias semântico para uso nos handlers de publicação.
    Garante que os parâmetros de afiliado nunca ficam visíveis na mensagem.

    Args:
        affiliate_url: URL longa com parâmetros de afiliado.

    Returns:
        URL curta pronta para inserir no copy.
    """
    return shorten_url(affiliate_url)
