"""
affiliate_link_service.py — Serviço centralizado de geração de links de afiliado.

Injeção via urllib.parse (à prova de falha).
Logs obrigatórios: LINK_AFILIADO_GERADO, LOJA_NAO_SUPORTADA, LOJA_NAO_CONFIGURADA.
"""
import logging
import os
import re
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse, quote

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# Global para fácil acesso e exportação
_AFFILIATE_IDS = {
    "amazon":       os.getenv("AFFILIATE_ID_AMAZON", "").strip(),
    "mercadolivre": os.getenv("AFFILIATE_ID_ML", "").strip(),
    "magalu":       os.getenv("AFFILIATE_ID_MAGALU", "").strip(),
    "netshoes":     os.getenv("AFFILIATE_ID_NETSHOES", "").strip(),
    "shopee":       os.getenv("AFFILIATE_ID_SHOPEE", "").strip(),
}

def log_config_status():
    """Útil para diagnóstico no console."""
    logger.info("─── AFILIADOS: STATUS DA CONFIGURAÇÃO ───")
    for store, aid in _AFFILIATE_IDS.items():
        if aid:
            masked = aid[:4] + "***" + aid[-4:] if len(aid) > 8 else aid
            logger.info(f"✅ {store.upper()}: Conectado ({masked})")
        else:
            logger.warning(f"❌ {store.upper()}: ID ausente no .env (não funcionará)")

# Executa log no startup
log_config_status()


# ---------------------------------------------------------------------------
# Detecção de loja pela URL
# ---------------------------------------------------------------------------

_STORE_DOMAINS = [
    ("amazon.com.br",        "amazon"),
    ("amazon.com",           "amazon"),
    ("amzn.to",              "amazon"),
    ("amzn.com",             "amazon"),
    ("mercadolivre.com.br",  "mercadolivre"),
    ("mercadolibre.com",     "mercadolivre"),
    ("produto.mercadolivre", "mercadolivre"),
    ("ml.tidd.ly",           "mercadolivre"),
    ("magazineluiza.com.br", "magalu"),
    ("magalu.com",           "magalu"),
    ("netshoes.com.br",      "netshoes"),
    ("shopee.com.br",        "shopee"),
    ("shp.ee",               "shopee"),
]


def _detectar_loja(url: str) -> str:
    url_lower = url.lower()
    for fragment, key in _STORE_DOMAINS:
        if fragment in url_lower:
            return key
    return "other"


# ---------------------------------------------------------------------------
# Injetores por loja — usando urllib.parse
# ---------------------------------------------------------------------------

def _injetar_amazon(url: str, tag: str) -> str:
    """
    Substitui ou adiciona tag= usando urllib.parse.
    Garante que a tag correta sempre esteja presente.
    """
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["tag"] = [tag]  # Substitui qualquer tag existente
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Amazon | tag={tag} | URL={resultado[:100]}")
    return resultado


def _injetar_mercadolivre(url: str, id_ml: str) -> str:
    """Adiciona matt_from= para o programa de afiliados do ML."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    # Remove parâmetros anteriores do ML
    for key in list(params.keys()):
        if key.startswith("matt_"):
            del params[key]
    params["matt_from"] = [id_ml]
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Mercado Livre | matt_from={id_ml} | URL={resultado[:100]}")
    return resultado


def _injetar_magalu(url: str, id_magalu: str) -> str:
    """Adiciona utm_medium=affiliate&utm_source= para Magalu."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["utm_medium"] = ["affiliate"]
    params["utm_source"]  = [id_magalu]
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Magalu | utm_source={id_magalu} | URL={resultado[:100]}")
    return resultado


def _injetar_shopee(url: str, shopee_id: str) -> str:
    """Adiciona af_id= para Shopee."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["af_id"] = [shopee_id]
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Shopee | af_id={shopee_id} | URL={resultado[:100]}")
    return resultado


def _injetar_netshoes(url: str, ns_id: str) -> str:
    """Netshoes via Rakuten. O * no ID é URL-encoded como %2A."""
    encoded_url = quote(url, safe="")
    encoded_id  = quote(ns_id, safe="")  # Codifica o * → %2A
    resultado = f"https://click.linksynergy.com/deeplink?id={encoded_id}&mid=43984&murl={encoded_url}"
    logger.info(f"[AFFILIATE_SERVICE] Netshoes | gateway Rakuten | ID={ns_id[:8]}...")
    return resultado


# ---------------------------------------------------------------------------
# Função pública central
# ---------------------------------------------------------------------------

def injetar_link_afiliado(url: str, store_key: str | None = None) -> str:
    """
    Injeta o link de afiliado correto por loja.

    IMPORTANTE: Deve ser chamada DEPOIS de resolve_url(), nunca antes.

    Args:
        url:        URL final/resolvida do produto.
        store_key:  Loja (detectada automaticamente se None).

    Returns:
        URL com parâmetros de afiliado corretos.
        Se loja não suportada: retorna URL original sem erro.
    """
    if not url or not isinstance(url, str):
        logger.warning("[AFFILIATE_SERVICE] ERRO_GERANDO_LINK_AFILIADO: URL inválida.")
        return url or ""

    # Limpeza preventiva de rastreadores de terceiros
    for param in ["fbclid", "gclid", "aff_id", "clickid"]:
        url = re.sub(rf"[?&]{param}=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")

    if not store_key:
        store_key = _detectar_loja(url)

    logger.info(f"[AFFILIATE_SERVICE] Iniciando injeção | loja={store_key} | url={url[:80]}")

    affiliate_id = _AFFILIATE_IDS.get(store_key, "").strip()

    if not affiliate_id:
        if store_key != "other":
            logger.warning(
                f"[AFFILIATE_SERVICE] LOJA_NAO_CONFIGURADA: {store_key} "
                f"— verifique AFFILIATE_ID_{store_key.upper()} no .env"
            )
        else:
            logger.info(f"[AFFILIATE_SERVICE] LOJA_NAO_SUPORTADA | url={url[:60]}")
        return url

    try:
        if store_key == "amazon":
            resultado = _injetar_amazon(url, affiliate_id)
        elif store_key == "mercadolivre":
            resultado = _injetar_mercadolivre(url, affiliate_id)
        elif store_key == "magalu":
            resultado = _injetar_magalu(url, affiliate_id)
        elif store_key == "shopee":
            resultado = _injetar_shopee(url, affiliate_id)
        elif store_key == "netshoes":
            resultado = _injetar_netshoes(url, affiliate_id)
        else:
            return url

        print(f"[LINK_AFILIADO_GERADO] Loja: {store_key} | URL: {resultado}")
        return resultado

    except Exception as e:
        logger.error(f"[AFFILIATE_SERVICE] ERRO_GERANDO_LINK_AFILIADO: {e} | loja={store_key}")
        return url


# ---------------------------------------------------------------------------
# Resolver via Playwright (para shorteners que bloqueiam requests.get)
# ---------------------------------------------------------------------------

async def resolve_url_playwright(url: str) -> str:
    """
    Resolve URLs curtas (amzn.to, shope.ee, ml.tidd.ly, etc.) via Playwright.

    Abre o link num browser headless, aguarda todos os redirecionamentos JS
    e retorna page.url — a URL final real, com todos os parâmetros.

    SÓ usa Playwright quando requests falha (domínios que bloqueiam bots).

    Args:
        url: URL curta ou com redirecionamento JS.

    Returns:
        URL final após redirecionamentos. Retorna a original em caso de falha.
    """
    try:
        from playwright.async_api import async_playwright
        import os

        logger.info(f"[AFFILIATE_SERVICE] Playwright resolver iniciando: {url[:80]}")

        async with async_playwright() as pw:
            proxy_config = None
            http_proxy = os.getenv("HTTP_PROXY", "").strip()
            if http_proxy and http_proxy.lower() not in ("none", "null", "undefined"):
                proxy_config = {"server": http_proxy}

            browser = await pw.chromium.launch(
                headless=True,
                proxy=proxy_config,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            page = await browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="pt-BR",
            )
            # domcontentloaded é suficiente para capturar a URL final
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Aguarda 2s para redirecionamentos JS lentos
            await page.wait_for_timeout(2000)
            final_url = page.url
            await browser.close()

        if final_url and final_url != url:
            logger.info(f"[AFFILIATE_SERVICE] Playwright resolveu: {final_url[:100]}")
        else:
            logger.info("[AFFILIATE_SERVICE] Playwright: URL não redirecionada (já é final).")
            final_url = url

        return final_url

    except ImportError:
        logger.warning("[AFFILIATE_SERVICE] Playwright não instalado. Usando URL original.")
        return url
    except Exception as e:
        logger.warning(f"[AFFILIATE_SERVICE] Playwright resolver falhou ({e}). Usando URL original.")
        return url
