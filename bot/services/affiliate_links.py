"""
affiliate_links.py - Regras de composicao do link final de publicacao.

Prioridade do link na publicacao:
  1. Afiliado automatico da loja (affiliate_config.json)
  2. Afiliado manual informado pelo admin no fluxo
  3. Link original enviado pelo admin

Nunca usa a URL tecnica resolvida como link final padrao.

Mantem compatibilidade total com o fluxo existente (resolve_final_url importado
aqui por compatibilidade reversa -- agora delegado ao url_resolver).
"""
import logging

from bot.utils.url_resolver import resolve_url
from bot.utils.detect_store import detect_store
from bot.utils.affiliate_store import build_affiliate_link

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Compat: resolve_final_url mantido para nao quebrar imports existentes
# ---------------------------------------------------------------------------

def resolve_final_url(url: str) -> str:
    """
    Compat alias: resolve a URL encurtada e retorna a URL final.
    Delega para bot.utils.url_resolver.resolve_url.
    """
    return resolve_url(url)


# ---------------------------------------------------------------------------
# Link final de publicacao
# ---------------------------------------------------------------------------

def get_final_link(
    original_url: str,
    affiliate_url: str | None = None,
    resolved_url: str | None = None,
) -> str:
    """
    Determina o link de publicacao final, seguindo esta prioridade:

    1. Afiliado automatico da loja (a partir da URL resolvida + config JSON)
    2. Afiliado manual fornecido pelo admin no fluxo
    3. Link original (encurtado ou nao) enviado pelo admin

    Args:
        original_url: URL que o admin colou (link original / encurtado)
        affiliate_url: Link de afiliado manual digitado pelo admin (opcional)
        resolved_url: URL final apos resolucao de redirects — usada para
                      detectar a loja e construir o afiliado automatico.
                      Se None, usa o original_url para deteccao.

    Returns:
        URL final para publicacao.
    """
    # Qual URL usar para detectar a loja
    url_for_detection = (resolved_url or original_url or "").strip()
    _, store_key = detect_store(url_for_detection)

    logger.info(
        f"[AFFILIATE] ── Composicao do link final ──────────────────\n"
        f"[AFFILIATE] Original  : {(original_url or '')[:80]}\n"
        f"[AFFILIATE] Resolvida : {(resolved_url or '')[:80]}\n"
        f"[AFFILIATE] Loja      : {store_key}\n"
        f"[AFFILIATE] Afiliado manual: {(affiliate_url or 'nenhum')[:60]}"
    )

    # --- 1. Afiliado automatico ---
    # Para Amazon: usa a URL resolvida para montar o link com tag
    auto_url = url_for_detection if store_key == "amazon" else original_url
    auto_link = build_affiliate_link(auto_url, store_key)
    if auto_link:
        logger.info(f"[AFFILIATE] ✅ Usando afiliado AUTOMATICO: {auto_link[:80]}")
        return auto_link

    # --- 2. Afiliado manual ---
    if affiliate_url and affiliate_url.strip():
        logger.info(f"[AFFILIATE] ✅ Usando afiliado MANUAL: {affiliate_url[:80]}")
        return affiliate_url.strip()

    # --- 3. Link original ---
    final = (original_url or resolved_url or "").strip()
    logger.info(f"[AFFILIATE] ℹ️ Usando link ORIGINAL: {final[:80]}")
    return final
