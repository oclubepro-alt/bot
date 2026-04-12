"""
publisher_telegram.py - Responsável por enviar mensagens para o canal do Telegram
"""
import logging
from telegram import Bot
from telegram.constants import ParseMode
from bot.utils.config import TELEGRAM_CHANNEL_ID
from bot.utils.channel_store import get_channels

logger = logging.getLogger(__name__)

async def publish_to_telegram(bot: Bot, message_text: str, photo_url_or_id: str | None = None) -> bool:
    """
    Publica a mensagem no canal configurado e nos canais extras adicionados.
    Se photo_url_or_id for fornecido, tenta postar como imagem + caption.
    Senão, posta apenas como texto.
    """
    # Junta o canal base com os canais extra
    canais_destino = [TELEGRAM_CHANNEL_ID]
    for ch in get_channels():
        if ch not in canais_destino:
            canais_destino.append(ch)
            
    sucesso_algum = False

    for chat_id in canais_destino:
        try:
            if photo_url_or_id:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_url_or_id,
                    caption=message_text,
                    parse_mode=ParseMode.MARKDOWN
                )
            else:
                await bot.send_message(
                    chat_id=chat_id,
                    text=message_text,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
            logger.info(f"[PUBLISHER_TELEGRAM] Oferta enviada ao canal {chat_id} com sucesso.")
            sucesso_algum = True
        except Exception as e:
            logger.error(f"[PUBLISHER_TELEGRAM] Falha ao enviar para o canal {chat_id}: {e}")
            
    if not sucesso_algum:
        raise Exception("Falha em todos os canais de destino")
    return True
