"""
dedup_store.py - Controle de links já vistos para evitar postagens duplicadas.
Armazena em data/seen_links.json (lista de URLs).
"""
import json
import logging
import os
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


def is_seen(url: str) -> bool:
    """Retorna True se o link já foi processado antes."""
    return url in _load()


def mark_seen(url: str) -> None:
    """Marca um link como já visto."""
    seen = _load()
    if url not in seen:
        seen.add(url)
        _save(seen)
        logger.info(f"[DEDUP] Link marcado como visto: {url[:80]}")


def clear_all() -> None:
    """Limpa todos os links vistos. Útil para manutenção/reset."""
    _save(set())
    logger.warning("[DEDUP] Todos os links vistos foram limpos.")
