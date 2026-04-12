"""
source_monitor.py - Monitora fontes cadastradas em data/sources.json,
coleta links de produtos encontrados e retorna os novos (não vistos).
"""
import logging
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from bot.services.dedup_store import is_seen

logger = logging.getLogger(__name__)

_SOURCES_PATH = Path(__file__).resolve().parents[2] / "data" / "sources.json"

# Padrões de URL que sugerem uma página de produto individual
_PRODUCT_URL_PATTERNS = re.compile(
    r"(/produto|/p/|/item/|/pd/|/product|/oferta|/-/|/dp/|/gp/|jm/|[?&]id=)",
    re.IGNORECASE
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}


def load_sources() -> list[dict]:
    """Carrega a lista de fontes de data/sources.json."""
    try:
        if _SOURCES_PATH.exists():
            return json.loads(_SOURCES_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[MONITOR] Erro ao carregar sources.json: {e}")
    return []


def _is_product_link(url: str) -> bool:
    """Heurística simples para identificar links de produto vs links de navegação."""
    return bool(_PRODUCT_URL_PATTERNS.search(url))


def _collect_links_from_page(source_url: str) -> list[str]:
    """
    Visita uma URL de fonte e coleta todos os links que parecem ser de produto.
    Retorna lista de URLs absolutas únicas.
    """
    collected = []
    base = f"{urlparse(source_url).scheme}://{urlparse(source_url).netloc}"

    try:
        resp = requests.get(source_url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        seen_hrefs: set[str] = set()
        for tag in soup.find_all("a", href=True):
            href = tag["href"].strip()
            if not href or href.startswith("#") or href.startswith("javascript"):
                continue

            # Converte para URL absoluta
            full_url = urljoin(base, href)

            # Remove query strings e fragmentos para deduplicar
            clean = full_url.split("#")[0].split("?")[0]

            if clean in seen_hrefs:
                continue
            seen_hrefs.add(clean)

            if _is_product_link(full_url):
                collected.append(full_url)

        logger.info(
            f"[MONITOR] Fonte '{source_url}': {len(collected)} links de produto encontrados."
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"[MONITOR] Falha ao acessar fonte '{source_url}': {e}")
    except Exception as e:
        logger.error(f"[MONITOR] Erro inesperado na fonte '{source_url}': {e}")

    return collected


def scan_sources() -> list[dict]:
    """
    Verifica todas as fontes ativas.
    Retorna lista de dicts {url, source_name} com links NOVOS (não vistos antes).
    """
    sources = load_sources()
    active = [s for s in sources if s.get("active", False)]

    if not active:
        logger.info("[MONITOR] Nenhuma fonte ativa encontrada. Configure data/sources.json.")
        return []

    logger.info(f"[MONITOR] Iniciando varredura de {len(active)} fonte(s) ativa(s)...")
    new_items = []

    for source in active:
        source_name = source.get("name", source["url"])
        logger.info(f"[MONITOR] Verificando fonte: {source_name}")

        links = _collect_links_from_page(source["url"])

        for link in links:
            if is_seen(link):
                logger.debug(f"[MONITOR] Ignorado (já visto): {link[:80]}")
                continue
            new_items.append({"url": link, "source_name": source_name})

    logger.info(f"[MONITOR] Varredura concluída. {len(new_items)} novos item(ns) encontrado(s).")
    return new_items
