"""
detect_store.py - Detecta a loja pelo domínio da URL final resolvida.

Regras (ordem de prioridade):
  - "amazon."                        → Amazon
  - "mercadolivre." / "mercadolibre." → Mercado Livre
  - "magazineluiza." / "magalu."      → Magalu
  - "netshoes."                       → Netshoes
  - demais                            → Outra
"""
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# (substring_no_netloc, nome_exibição, chave_interna)
_STORE_MAP: list[tuple[str, str, str]] = [
    ("amazon.",         "Amazon",        "amazon"),
    ("mercadolivre.",   "Mercado Livre", "mercadolivre"),
    ("mercadolibre.",   "Mercado Livre", "mercadolivre"),
    ("magazineluiza.",  "Magalu",        "magalu"),
    ("magalu.",         "Magalu",        "magalu"),
    ("netshoes.",       "Netshoes",      "netshoes"),
    ("shopee.",         "Shopee",        "shopee"),
    ("aliexpress.",     "AliExpress",    "aliexpress"),
]


def detect_store(url: str) -> tuple[str, str]:
    """
    Detecta a loja pela URL.

    Returns:
        (store_display_name, store_key)
        Onde store_key é a chave usada em affiliate_config.json.
        Ex.: ("Amazon", "amazon") ou ("Magalu", "magalu") ou ("Outra", "other")
    """
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        netloc = url.lower()

    for fragment, display, key in _STORE_MAP:
        if fragment in netloc:
            logger.info(f"[DETECT_STORE] '{fragment}' encontrado em '{netloc}' → {display}")
            return display, key

    logger.info(f"[DETECT_STORE] Loja não identificada para netloc='{netloc}' → Outra")
    return "Outra", "other"
