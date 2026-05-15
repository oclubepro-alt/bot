"""
config.py - Carrega e valida variaveis de ambiente do .env
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ID Unico desta execucao para detectar conflitos de instâncias duplicadas
import random
import string
from datetime import datetime
_rand = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
INSTANCE_ID = f"BOT-{_rand}-{datetime.now().strftime('%H%M')}"
BOOT_TIME = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

AFFILIATE_ID_AMAZON: str = os.getenv("AFFILIATE_ID_AMAZON", "").strip()
AMAZON_CREATORS_CLIENT_ID: str = os.getenv("AMAZON_CREATORS_CLIENT_ID", "").strip()
AMAZON_CREATORS_CLIENT_SECRET: str = os.getenv("AMAZON_CREATORS_CLIENT_SECRET", "").strip()
AMAZON_API_VERSION: str = os.getenv("AMAZON_API_VERSION", "v1").strip()

# Mercado Livre
ML_APP_ID: str = os.getenv("ML_APP_ID", "").strip()
ML_CLIENT_SECRET: str = os.getenv("ML_CLIENT_SECRET", "").strip()
ML_TG_TOKEN: str = os.getenv("ML_TG_TOKEN", "").strip() # Token inicial/Grant
ML_ACCESS_TOKEN: str = os.getenv("ML_ACCESS_TOKEN", "").strip()
ML_REFRESH_TOKEN: str = os.getenv("ML_REFRESH_TOKEN", "").strip()

def _require(var: str) -> str:
    """Lê variavel obrigatoria ou lanca erro claro."""
    value = os.getenv(var, "").strip()
    if not value:
        raise EnvironmentError(
            f"[CONFIG] Variavel obrigatoria '{var}' nao encontrada no .env"
        )
    return value


def _parse_admin_ids(raw: str) -> list[int]:
    """Converte string de IDs separados por virgula em lista de inteiros."""
    ids = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            try:
                ids.append(int(part))
            except ValueError:
                logger.warning(f"[CONFIG] ADMIN_IDS: valor invalido ignorado → '{part}'")
    return ids


# ── Variaveis publicas ──────────────────────────────────────────────────────

_raw_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
# Remove aspas se o usuario colou com aspas por engano no Railway
if (_raw_token.startswith('"') and _raw_token.endswith('"')) or \
   (_raw_token.startswith("'") and _raw_token.endswith("'")):
    TELEGRAM_BOT_TOKEN = _raw_token[1:-1].strip()
else:
    TELEGRAM_BOT_TOKEN = _raw_token

if not TELEGRAM_BOT_TOKEN:
    raise EnvironmentError("[CONFIG] TELEGRAM_BOT_TOKEN nao encontrado!")
TELEGRAM_CHANNEL_ID: str = _require("TELEGRAM_CHANNEL_ID")
OPENAI_API_KEY: str = _require("OPENAI_API_KEY")
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "").strip()
_raw_proxy = os.getenv("HTTP_PROXY", "").strip()
if _raw_proxy.lower() in ("none", "null", "undefined", ""):
    HTTP_PROXY = ""
else:
    HTTP_PROXY = _raw_proxy


_raw_admins = os.getenv("ADMIN_IDS", "").strip()
ADMIN_IDS: list[int] = _parse_admin_ids(_raw_admins) if _raw_admins else []

if not ADMIN_IDS:
    logger.warning(
        "[CONFIG] ADMIN_IDS esta vazio! Nenhum usuario podera publicar ofertas."
    )
else:
    logger.info(f"[CONFIG] Admins carregados: {ADMIN_IDS}")

logger.info(f"[CONFIG] Canal de publicacao: {TELEGRAM_CHANNEL_ID}")
logger.info(f"[CONFIG] Modelo OpenAI: {OPENAI_MODEL}")

# ── Fase 3: Scheduler e aprovacao ───────────────────────────────────────────
# Intervalo em minutos para varredura automatica de fontes
_raw_interval = os.getenv("MONITOR_INTERVAL_MINUTES", "60").strip()
try:
    MONITOR_INTERVAL_MINUTES: int = int(_raw_interval)
except ValueError:
    MONITOR_INTERVAL_MINUTES = 60
    logger.warning("[CONFIG] MONITOR_INTERVAL_MINUTES invalido, usando 60 minutos.")

# Se True, publica automaticamente sem aguardar aprovacao do admin. (Fase 4)
# PADRAO DE SEGURANCA: false — admin revisa cada oferta antes de publicar
# Para mudar: defina AUTO_APPROVE=true no Railway (ou .env)
_raw_auto = os.getenv("AUTO_APPROVE", "false").strip().lower()
AUTO_APPROVE: bool = _raw_auto in ("1", "true", "yes")

SCRAPINGDOG_API_KEY: str = os.getenv("SCRAPINGDOG_API_KEY", "").strip()



if AUTO_APPROVE:
    logger.warning(
        "[CONFIG] ⚠️  AUTO_APPROVE=true — ATENCAO: as ofertas do monitoramento "
        "serao publicadas AUTOMATICAMENTE no canal SEM revisao do admin! "
        "Para revisao manual, defina AUTO_APPROVE=false no Railway."
    )
else:
    logger.info("[CONFIG] ✅ AUTO_APPROVE=false — todas as ofertas passarao pela revisao do admin.")

logger.info(f"[CONFIG] Scheduler: a cada {MONITOR_INTERVAL_MINUTES} min | Auto-approve: {AUTO_APPROVE}")
