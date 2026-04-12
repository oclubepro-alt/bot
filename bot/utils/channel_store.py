"""
channel_store.py - Persistência para canais do Telegram
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_CHANNELS_FILE = _DATA_DIR / "channels.json"

def _ensure_file():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _CHANNELS_FILE.exists():
        _CHANNELS_FILE.write_text("[]", encoding="utf-8")

def get_channels() -> list[str]:
    _ensure_file()
    try:
        with open(_CHANNELS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[CHANNEL_STORE] Erro ao carregar canais: {e}. Usando lista vazia.")
        return []

def add_channel(channel_id: str) -> bool:
    channels = get_channels()
    if channel_id in channels:
        return False
    channels.append(channel_id)
    try:
        with open(_CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(channels, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"[CHANNEL_STORE] Erro ao salvar: {e}")
        return False

def remove_channel(channel_id: str) -> bool:
    channels = get_channels()
    if channel_id not in channels:
        return False
    channels.remove(channel_id)
    try:
        with open(_CHANNELS_FILE, "w", encoding="utf-8") as f:
            json.dump(channels, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"[CHANNEL_STORE] Erro ao salvar: {e}")
        return False
