"""
whatsapp_store.py - Persistência para canais do WhatsApp
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_WHATSAPP_FILE = _DATA_DIR / "whatsapp_channels.json"

def _ensure_file():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _WHATSAPP_FILE.exists():
        _WHATSAPP_FILE.write_text("[]", encoding="utf-8")

def get_whatsapp_channels() -> list[dict]:
    """
    Retorna lista de canais/grupos do WhatsApp.
    Cada item: {"name": "Bot Achadinhos", "jid": "120363... @g.us", "active": True}
    """
    _ensure_file()
    try:
        with open(_WHATSAPP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[WHATSAPP_STORE] Erro ao carregar: {e}")
        return []

def add_whatsapp_channel(name: str, jid: str) -> bool:
    channels = get_whatsapp_channels()
    if any(c["jid"] == jid for c in channels):
        return False
    channels.append({"name": name, "jid": jid, "active": True})
    try:
        with open(_WHATSAPP_FILE, "w", encoding="utf-8") as f:
            json.dump(channels, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[WHATSAPP_STORE] Erro ao salvar: {e}")
        return False

def remove_whatsapp_channel(jid: str) -> bool:
    channels = get_whatsapp_channels()
    new_channels = [c for c in channels if c["jid"] != jid]
    if len(new_channels) == len(channels):
        return False
    try:
        with open(_WHATSAPP_FILE, "w", encoding="utf-8") as f:
            json.dump(new_channels, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"[WHATSAPP_STORE] Erro ao salvar: {e}")
        return False
