"""
affiliate_injector.py — Injeção de parâmetros de afiliado por loja.

Regras:
  AMAZON      → adiciona ?tag=ID ou &tag=ID à URL resolvida.
  MERCADO LIVRE → anexa ?utm_source=afiliado&utm_medium=referral&utm_campaign=ID.
  MAGALU      → converte para padrão MagazineVocê:
                https://www.magazinevoce.com.br/magazineID/p/SLUG/PRODID/
  NETSHOES    → anexa ?campaign=afiliados&utm_source=c_afiliados&utm_medium=ID.

Os IDs são lidos do .env via configuração centralizada ou recebidos diretamente.

Usage:
    from bot.services.affiliate_injector import inject_affiliate
    url_afiliado = inject_affiliate(url_resolvida, store_key)
"""
import re
import logging
import os
from urllib.parse import urlparse, urlencode, parse_qs, urljoin

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IDs de afiliado lidos do ambiente (com fallback para os defaults do .env.example)
# ---------------------------------------------------------------------------
_IDS: dict[str, str] = {
    "amazon":       os.getenv("AFFILIATE_ID_AMAZON", "").strip(),
    "mercadolivre": os.getenv("AFFILIATE_ID_ML", "").strip(),
    "magalu":       os.getenv("AFFILIATE_ID_MAGALU", "").strip(),
    "netshoes":     os.getenv("AFFILIATE_ID_NETSHOES", "").strip(),
}


# ---------------------------------------------------------------------------
# Helpers de URL
# ---------------------------------------------------------------------------

def _has_query(url: str) -> bool:
    return "?" in url


def _append_params(url: str, params: dict) -> str:
    """Adiciona query params à URL respeitando os existentes."""
    sep = "&" if _has_query(url) else "?"
    return url + sep + urlencode(params)


# ---------------------------------------------------------------------------
# Regras por loja
# ---------------------------------------------------------------------------

def _inject_amazon(url: str, tag: str) -> str:
    """
    Amazon: adiciona tag de afiliado.
    Remove qualquer tag existente antes de adicionar a nova.
    """
    # Remove tag anterior se já existir
    url = re.sub(r"[?&]tag=[^&]*", "", url)
    # Limpa '?' ou '&&' que pode ter sobrado
    url = re.sub(r"\?&", "?", url).rstrip("?&")
    sep = "&" if _has_query(url) else "?"
    result = f"{url}{sep}tag={tag}"
    logger.info(f"[INJECTOR][Amazon] Tag '{tag}' injetada.")
    return result


def _inject_mercadolivre(url: str, matt_tool: str) -> str:
    """
    Mercado Livre: adiciona parâmetros matt_tool e af.
    """
    params = {
        "matt_tool": matt_tool,
        "matt_word": "desconteca"
    }
    result = _append_params(url, params)
    logger.info(f"[INJECTOR][ML] matt_tool='{matt_tool}' injetado.")
    return result


def _inject_magalu(url: str, id_magalu: str) -> str:
    """
    Magalu: suporta tanto promoter_id (numérico) quanto loja ID (string)
    """
    # Se o ID for apenas números, injetamos via promoter_id via querystring
    if id_magalu.isdigit():
        params = {
            "promoter_id": id_magalu,
            "partner_id": "3440" # partner_id padrão Magalu Afiliados
        }
        result = _append_params(url, params)
        logger.info(f"[INJECTOR][Magalu] promoter_id='{id_magalu}' injetado.")
        return result

    # Caso contrário, formato MagazineVoce
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    m = re.search(r"/p/([^/]+)/([A-Z0-9]{6,10})", path)
    if m:
        slug = m.group(1)
        prod_id = m.group(2)
        result = (
            f"https://www.magazinevoce.com.br/magazine{id_magalu}"
            f"/p/{slug}/{prod_id}/"
        )
        logger.info(f"[INJECTOR][Magalu] Convertido para MagazineVocê → {result[:80]}")
        return result

    m2 = re.search(r"/p/([A-Z0-9]{6,10})", path)
    if m2:
        prod_id = m2.group(1)
        result = (
            f"https://www.magazinevoce.com.br/magazine{id_magalu}"
            f"/p/produto/{prod_id}/"
        )
        logger.info(f"[INJECTOR][Magalu] Convertido (fallback s/ slug) → {result[:80]}")
        return result

    return f"https://www.magazinevoce.com.br/magazine{id_magalu}/"


def _inject_netshoes(url: str, ns_id: str) -> str:
    """
    Netshoes: usa o gateway Rakuten (Linksynergy).
    """
    from urllib.parse import quote
    
    # Se foi passado um mid customizado, ex: "1234&mid=43984" então ignora e extrai só o ID
    if "&mid=" in ns_id:
        ns_id = ns_id.split("&")[0]

    encoded_url = quote(url, safe="")
    result = f"https://click.linksynergy.com/deeplink?id={ns_id}&mid=43984&murl={encoded_url}"
    logger.info(f"[INJECTOR][Netshoes] Link Rakuten gerado (id='{ns_id}').")
    return result


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------

def inject_affiliate(
    url: str,
    store_key: str,
    *,
    override_ids: dict | None = None,
) -> str | None:
    """
    Aplica a transformação de afiliado conforme a loja.

    Args:
        url:          URL resolvida do produto.
        store_key:    Chave da loja ('amazon', 'mercadolivre', 'magalu', 'netshoes').
        override_ids: Sobrescreve os IDs padrão do .env (útil para testes).

    Returns:
        URL com parâmetros de afiliado injetados, ou None se loja não suportada
        ou ID não configurado.
    """
    ids = {**_IDS, **(override_ids or {})}

    if not url:
        logger.warning("[INJECTOR] URL vazia recebida.")
        return None

    if store_key == "amazon":
        tag = ids.get("amazon", "")
        if not tag:
            logger.info("[INJECTOR][Amazon] AFFILIATE_ID_AMAZON não configurado.")
            return None
        return _inject_amazon(url, tag)

    if store_key == "mercadolivre":
        ml_id = ids.get("mercadolivre", "")
        if not ml_id:
            logger.info("[INJECTOR][ML] AFFILIATE_ID_ML não configurado.")
            return None
        return _inject_mercadolivre(url, ml_id)

    if store_key == "magalu":
        mgl_id = ids.get("magalu", "")
        if not mgl_id:
            logger.info("[INJECTOR][Magalu] AFFILIATE_ID_MAGALU não configurado.")
            return None
        return _inject_magalu(url, mgl_id)

    if store_key == "netshoes":
        ns_id = ids.get("netshoes", "")
        if not ns_id:
            logger.info("[INJECTOR][Netshoes] AFFILIATE_ID_NETSHOES não configurado.")
            return None
        return _inject_netshoes(url, ns_id)

    logger.info(f"[INJECTOR] Loja '{store_key}' sem regra de afiliado.")
    return None


def get_affiliate_url(
    original_url: str,
    resolved_url: str | None,
    store_key: str,
    *,
    override_ids: dict | None = None,
) -> str:
    """
    Wrapper de alto nível: tenta injetar afiliado e retorna a melhor URL disponível.

    Prioridade:
        1. URL com afiliado injetado (via inject_affiliate)
        2. URL original

    Args:
        original_url:  URL original enviada pelo admin/scraper.
        resolved_url:  URL após resolução de redirects (usada na injeção).
        store_key:     Chave da loja.
        override_ids:  IDs de override para testes.

    Returns:
        URL final para publicação.
    """
    target = (resolved_url or original_url or "").strip()
    injected = inject_affiliate(target, store_key, override_ids=override_ids)
    if injected:
        logger.info(f"[INJECTOR] ✅ Afiliado injetado: {injected[:80]}")
        return injected
    logger.info("[INJECTOR] Sem afiliado disponível — usando URL original.")
    return original_url or target
