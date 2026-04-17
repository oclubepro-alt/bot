"""
affiliate_link_service.py — Serviço centralizado de geração de links de afiliado.

Lê IDs do .env, detecta a loja pela URL e injeta os parâmetros corretos.
Nunca quebra o fluxo: se a loja não for suportada, retorna URL original.

Logs obrigatórios em cada etapa.
"""
import logging
import os
import re
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse, quote

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Carregamento de IDs — com validação
# ---------------------------------------------------------------------------

_AFFILIATE_IDS = {
    "amazon":       os.getenv("AFFILIATE_ID_AMAZON", "").strip(),
    "mercadolivre": os.getenv("AFFILIATE_ID_ML", "").strip(),
    "magalu":       os.getenv("AFFILIATE_ID_MAGALU", "").strip(),
    "netshoes":     os.getenv("AFFILIATE_ID_NETSHOES", "").strip(),
    "shopee":       os.getenv("AFFILIATE_ID_SHOPEE", "").strip(),
}

# Log de configuração no startup
for store, aid in _AFFILIATE_IDS.items():
    if aid:
        logger.info(f"[AFFILIATE_SERVICE] ✅ {store}: configurado (ID={aid[:6]}...)")
    else:
        logger.warning(f"[AFFILIATE_SERVICE] ⚠️  {store}: AFFILIATE_ID não configurado no .env")


# ---------------------------------------------------------------------------
# Detecção de loja pela URL
# ---------------------------------------------------------------------------

_STORE_DOMAINS = [
    ("amazon.com.br",         "amazon"),
    ("amazon.com",            "amazon"),
    ("amzn.to",               "amazon"),
    ("amzn.com",              "amazon"),
    ("mercadolivre.com.br",   "mercadolivre"),
    ("mercadolibre.com",      "mercadolivre"),
    ("produto.mercadolivre",  "mercadolivre"),
    ("ml.tidd.ly",            "mercadolivre"),
    ("magazineluiza.com.br",  "magalu"),
    ("magalu.com",            "magalu"),
    ("netshoes.com.br",       "netshoes"),
    ("shopee.com.br",         "shopee"),
    ("shp.ee",                "shopee"),
]


def _detectar_loja(url: str) -> str:
    """Retorna a store_key pela URL."""
    url_lower = url.lower()
    for fragment, key in _STORE_DOMAINS:
        if fragment in url_lower:
            return key
    return "other"


# ---------------------------------------------------------------------------
# Injetores por loja
# ---------------------------------------------------------------------------

def _injetar_amazon(url: str, tag: str) -> str:
    """Substitui ou adiciona tag= na URL da Amazon."""
    # Remove tag existente (de qualquer afiliado)
    url = re.sub(r"[?&]tag=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")
    sep = "&" if "?" in url else "?"
    resultado = f"{url}{sep}tag={tag}"
    logger.info(f"[AFFILIATE_SERVICE] Amazon → tag={tag} injetada")
    return resultado


def _injetar_mercadolivre(url: str, id_ml: str) -> str:
    """Adiciona matt_from= para o programa de afiliados do ML."""
    url = re.sub(r"[?&](matt_from|matt_tool|matt_word)=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")
    sep = "&" if "?" in url else "?"
    resultado = f"{url}{sep}matt_from={id_ml}"
    logger.info(f"[AFFILIATE_SERVICE] Mercado Livre → matt_from={id_ml} injetado")
    return resultado


def _injetar_magalu(url: str, id_magalu: str) -> str:
    """Adiciona utm_medium=affiliate&utm_source= para Magalu."""
    url = re.sub(r"[?&]utm_(source|medium|campaign)=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")
    sep = "&" if "?" in url else "?"
    resultado = f"{url}{sep}utm_medium=affiliate&utm_source={id_magalu}"
    logger.info(f"[AFFILIATE_SERVICE] Magalu → utm_source={id_magalu} injetado")
    return resultado


def _injetar_shopee(url: str, shopee_id: str) -> str:
    """Adiciona af_id= para Shopee."""
    url = re.sub(r"[?&]af_id=[^&]*", "", url)
    sep = "&" if "?" in url else "?"
    resultado = f"{url}{sep}af_id={shopee_id}"
    logger.info(f"[AFFILIATE_SERVICE] Shopee → af_id={shopee_id} injetado")
    return resultado


def _injetar_netshoes(url: str, ns_id: str) -> str:
    """Netshoes via Rakuten LinkSynergy (suporta caracteres especiais no ID)."""
    encoded_url = quote(url, safe="")
    encoded_id = quote(ns_id, safe="")
    resultado = f"https://click.linksynergy.com/deeplink?id={encoded_id}&mid=43984&murl={encoded_url}"
    logger.info(f"[AFFILIATE_SERVICE] Netshoes → gateway Rakuten construído")
    return resultado


# ---------------------------------------------------------------------------
# Função pública central
# ---------------------------------------------------------------------------

def injetar_link_afiliado(url: str, store_key: str | None = None) -> str:
    """
    Função central de injeção de afiliado.
    
    Args:
        url:        URL do produto (já resolvida/final).
        store_key:  Loja detectada (opcional — será detectado automaticamente se ausente).
    
    Returns:
        URL com parâmetros de afiliado injetados.
        Se a loja não for suportada, retorna a URL original sem erro.
    """
    if not url or not isinstance(url, str):
        logger.warning("[AFFILIATE_SERVICE] ERRO_GERANDO_LINK_AFILIADO: URL inválida ou vazia.")
        return url

    # Limpeza preventiva de parâmetros de rastreio de terceiros
    url = re.sub(r"[?&](fbclid|gclid|aff_id|clickid|ref)=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")

    if not store_key:
        store_key = _detectar_loja(url)

    logger.info(f"[AFFILIATE_SERVICE] LOJA_DETECTADA={store_key} | URL={url[:80]}")

    affiliate_id = _AFFILIATE_IDS.get(store_key, "").strip()

    if not affiliate_id:
        if store_key != "other":
            logger.warning(f"[AFFILIATE_SERVICE] LOJA_NAO_CONFIGURADA: {store_key} — ID ausente no .env")
        else:
            logger.info(f"[AFFILIATE_SERVICE] LOJA_NAO_SUPORTADA para URL: {url[:60]}")
        return url

    try:
        if store_key == "amazon":
            return _injetar_amazon(url, affiliate_id)
        if store_key == "mercadolivre":
            return _injetar_mercadolivre(url, affiliate_id)
        if store_key == "magalu":
            return _injetar_magalu(url, affiliate_id)
        if store_key == "shopee":
            return _injetar_shopee(url, affiliate_id)
        if store_key == "netshoes":
            return _injetar_netshoes(url, affiliate_id)
    except Exception as e:
        logger.error(f"[AFFILIATE_SERVICE] ERRO_GERANDO_LINK_AFILIADO: {e} | loja={store_key} | url={url[:60]}")

    return url
