"""
config.py - Carrega e valida variáveis de ambiente do .env
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def _require(var: str) -> str:
    """Lê variável obrigatória ou lança erro claro."""
    value = os.getenv(var, "").strip()
    if not value:
        raise EnvironmentError(
            f"[CONFIG] Variável obrigatória '{var}' não encontrada no .env"
        )
    return value


def _parse_admin_ids(raw: str) -> list[int]:
    """Converte string de IDs separados por vírgula em lista de inteiros."""
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                logger.warning(f"[CONFIG] ADMIN_IDS: valor inválido ignorado → '{part}'")
    return ids


# ── Variáveis públicas ──────────────────────────────────────────────────────

TELEGRAM_BOT_TOKEN: str = _require("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID: str = _require("TELEGRAM_CHANNEL_ID")
OPENAI_API_KEY: str = _require("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "").strip()
HTTP_PROXY: str = os.getenv("HTTP_PROXY", "").strip()


_raw_admins = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: list[int] = _parse_admin_ids(_raw_admins) if _raw_admins else []

if not ADMIN_IDS:
    logger.warning(
        "[CONFIG] ADMIN_IDS está vazio! Nenhum usuário poderá publicar ofertas."
    )
else:
    logger.info(f"[CONFIG] Admins carregados: {ADMIN_IDS}")

logger.info(f"[CONFIG] Canal de publicação: {TELEGRAM_CHANNEL_ID}")
logger.info(f"[CONFIG] Modelo OpenAI: {OPENAI_MODEL}")

# ── Fase 3: Scheduler e aprovação ───────────────────────────────────────────
# Intervalo em minutos para varredura automática de fontes
_raw_interval = os.getenv("MONITOR_INTERVAL_MINUTES", "60").strip()
try:
    MONITOR_INTERVAL_MINUTES: int = int(_raw_interval)
except ValueError:
    MONITOR_INTERVAL_MINUTES = 60
    logger.warning("[CONFIG] MONITOR_INTERVAL_MINUTES inválido, usando 60 minutos.")

# Se True, publica automaticamente sem aguardar aprovação do admin. (Fase 4)
_raw_auto = os.getenv("AUTO_APPROVE", "false").strip().lower()
AUTO_APPROVE: bool = _raw_auto in ("1", "true", "yes")

logger.info(f"[CONFIG] Scheduler: a cada {MONITOR_INTERVAL_MINUTES} min | Auto-approve: {AUTO_APPROVE}")
