"""
publisher_router.py - Roteador de publicações (preparado para multi-plataformas)
"""
import logging
from telegram import Bot
from bot.services.publisher_telegram import publish_to_telegram
from bot.services.publisher_whatsapp import publish_to_whatsapp

logger = logging.getLogger(__name__)

async def publish_offer(bot: Bot, copies: dict, photo: str | None = None) -> None:
    """
    Roteador responsável por coordenar a publicação nas plataformas suportadas.
    'copies' deve ser o dict retornado por build_copy: {"telegram": "...", "whatsapp": "..."}
    """
    logger.info("[PUBLISHER_ROUTER] Iniciando rotina de publicação...")
    
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
