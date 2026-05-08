"""
dedup_store.py - Controle de links já vistos para evitar postagens duplicadas.
Armazena em data/seen_links.json (lista de URLs).
"""
import json
import logging
import uuid
import random
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "seen_links.json"


def _load() -> set[str]:
    """Carrega o conjunto de links já vistos do arquivo JSON."""
    try:
        if _DATA_PATH.exists():
            data = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
            return set(data) if isinstance(data, list) else set()
    except Exception as e:
        logger.error(f"[DEDUP] Erro ao carregar seen_links.json: {e}")
    return set()


def _save(seen: set[str]) -> None:
    """Persiste o conjunto de links no arquivo JSON."""
    try:
        _DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DATA_PATH.write_text(
            json.dumps(sorted(seen), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as e:
        logger.error(f"[DEDUP] Erro ao salvar seen_links.json: {e}")


def normalize_url(url: str) -> str:
    """Normaliza a URL para comparação (remove UTMs, mobile prefixes, etc)."""
    if not url: return ""
    try:
        # Lowercase, remove excesso de espaços
        url = url.strip().lower()

        # Especial para Amazon: Extrair o ASIN (B0...)
        # Ex: amazon.com.br/dp/B0FLKLFMQZ/... -> b0flklfmqz
        asin_match = re.search(r"/(?:dp|gp/product)/([a-z0-9]{10})", url)
        if asin_match:
            return f"amazon:{asin_match.group(1)}"

        # Remove prefixos mobile conhecidos
        url = url.replace("https://m.", "https://").replace("https://mobile.", "https://")
        # Remove fragmentos (#...)
        url = url.split("#")[0]
        # Remove query strings comuns de rastreio (utm, gclid, fbclid, etc)
        url = re.sub(r"[?&](utm_[^&]+|fbclid|gclid|aff_id|clickid|ref|linkcode|linkid)=[^&]*", "", url)
        # Limpa '?' ou '&' sobrando no final
        url = url.rstrip("?&")
        return url
    except Exception:
        return url

def is_seen(url: str) -> bool:
    """Retorna True se o link (normalizado) já foi processado antes."""
    norm = normalize_url(url)
    return norm in _load()


def mark_seen(url: str) -> None:
    """Marca um link como já visto (usando forma normalizada)."""
    norm = normalize_url(url)
    seen = _load()
    if norm not in seen:
        seen.add(norm)
        _save(seen)
        logger.info(f"[DEDUP] Link marcado como visto (norm): {norm[:80]}")


def clear_all() -> None:
    """Limpa todos os links vistos."""
    _save(set())
    logger.warning("[DEDUP] Todos os links vistos foram limpos.")
