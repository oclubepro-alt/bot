"""
scheduler_queue_service.py - Gerencia a fila de postagens agendadas.
Permite enfileirar ofertas para postagem automática com intervalo controlado.
"""
import json
import logging
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_QUEUE_PATH = Path(__file__).resolve().parents[2] / "data" / "scheduled_queue.json"

def _load_queue() -> list:
    try:
        if _QUEUE_PATH.exists():
            return json.loads(_QUEUE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[SCHEDULE_QUEUE] Erro ao carregar: {e}")
    return []

def _save_queue(data: list) -> None:
    try:
        _QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _QUEUE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"[SCHEDULE_QUEUE] Erro ao salvar: {e}")

def add_to_queue(offer_data: dict) -> int:
    """Adiciona uma oferta à fila de agendamento. Retorna a posição."""
    queue = _load_queue()
    queue.append({
        "offer": offer_data,
        "added_at": datetime.datetime.now().isoformat()
    })
    _save_queue(queue)
    return len(queue)

def get_next_from_queue() -> dict | None:
    """Retorna e remove o próximo item da fila."""
    queue = _load_queue()
    if not queue:
        return None
    
    item = queue.pop(0)
    _save_queue(queue)
    return item["offer"]

def get_queue_size() -> int:
    return len(_load_queue())
