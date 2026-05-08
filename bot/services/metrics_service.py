"""
metrics_service.py - Sistema de rastreamento de performance do bot.
Registra descobertas, aprovações e publicações.
"""
import json
import logging
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_METRICS_PATH = Path(__file__).resolve().parents[2] / "data" / "metrics.json"

def _load_metrics() -> dict:
    try:
        if _METRICS_PATH.exists():
            return json.loads(_METRICS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[METRICS] Erro ao carregar: {e}")
    return {"daily": {}, "total": {"scanned": 0, "approved": 0, "published": 0, "rejected": 0}}

def _save_metrics(data: dict) -> None:
    try:
        _METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _METRICS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"[METRICS] Erro ao salvar: {e}")

def log_event(event_type: str) -> None:
    """
    Registra um evento: 'scanned', 'approved', 'published', 'rejected'.
    """
    data = _load_metrics()
    today = datetime.date.today().isoformat()
    
    # Inicia dia se não existir
    if today not in data["daily"]:
        data["daily"][today] = {"scanned": 0, "approved": 0, "published": 0, "rejected": 0}
    
    # Incrementa dia
    if event_type in data["daily"][today]:
        data["daily"][today][event_type] += 1
    
    # Incrementa total
    if event_type in data["total"]:
        data["total"][event_type] += 1
        
    _save_metrics(data)

def get_stats() -> dict:
    """Retorna estatísticas formatadas."""
    data = _load_metrics()
    today = datetime.date.today().isoformat()
    return {
        "today": data["daily"].get(today, {"scanned": 0, "approved": 0, "published": 0, "rejected": 0}),
        "total": data["total"]
    }
