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
    ("amazon.",          "Amazon",        "amazon"),
    ("amzn.",            "Amazon",        "amazon"),
    ("mercadolivre.",    "Mercado Livre", "mercadolivre"),
    ("mercadolibre.",    "Mercado Livre", "mercadolivre"),
    ("mli.",             "Mercado Livre", "mercadolivre"),
    ("magazineluiza.",   "Magalu",        "magalu"),
    ("magalu.",          "Magalu",        "magalu"),
    ("netshoes.",        "Netshoes",      "netshoes"),
    ("shopee.",          "Shopee",        "shopee"),
    ("shp.ee",           "Shopee",        "shopee"),
    ("aliexpress.",      "AliExpress",    "aliexpress"),
    ("casasbahia.",      "Casas Bahia",   "casasbahia"),
    ("pontofrio.",       "Ponto Frio",    "pontofrio"),
    ("extra.com.br",     "Extra",         "extra"),
    ("kabum.",           "KaBuM!",        "kabum"),
    ("americanas.",      "Americanas",    "americanas"),
    ("submarino.",       "Submarino",     "submarino"),
    ("shoptime.",        "Shoptime",      "shoptime"),
    ("zattini.",         "Zattini",       "zattini"),
    ("centauro.",        "Centauro",      "centauro"),
    ("renner.",          "Renner",        "renner"),
    ("riachuelo.",       "Riachuelo",     "riachuelo"),
    ("cea.com",          "C&A",           "cea"),
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
        if fragment in netloc or fragment in url.lower():
            logger.info(f"[DETECT_STORE] '{fragment}' encontrado → {display}")
            return display, key

    logger.info(f"[DETECT_STORE] Loja não identificada para '{netloc or url[:40]}' → Outra")
    return "Outra", "other"
