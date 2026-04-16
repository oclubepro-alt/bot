"""
publisher_router.py - Roteador de publicações (preparado para multi-plataformas)
"""
import logging
from telegram import Bot
from bot.services.publisher_telegram import publish_to_telegram
from bot.services.publisher_whatsapp import publish_to_whatsapp

logger = logging.getLogger(__name__)

async def publish_offer(bot: Bot, copies: str | dict, photo: str | None = None) -> None:
    """
    Roteador responsável por coordenar a publicação nas plataformas suportadas.
    'copies' pode ser um dict {"telegram": "...", "whatsapp": "..."} ou uma string (apenas Telegram).
    """
    logger.info("[PUBLISHER_ROUTER] Iniciando rotina de publicação...")
    
    # Normaliza para dict se for string
    if isinstance(copies, str):
        copies = {"telegram": copies, "whatsapp": None}

    # 1. Publica no Telegram (pode enviar para múltiplos canais)
    text_telegram = copies.get("telegram")
    if text_telegram:
        try:
            await publish_to_telegram(bot, text_telegram, photo)
        except Exception as e:
            logger.error(f"[PUBLISHER_ROUTER] Erro Telegram: {e}")

    # 2. Publica no WhatsApp (pode enviar para múltiplos destinos)
    text_whatsapp = copies.get("whatsapp")
    if text_whatsapp:
        try:
            await publish_to_whatsapp(text_whatsapp, photo)
        except Exception as e:
            logger.error(f"[PUBLISHER_ROUTER] Erro WhatsApp: {e}")
    
    logger.info("[PUBLISHER_ROUTER] Rotina de publicação concluída.")
