"""
publisher_telegram.py - Responsável por enviar mensagens para o canal do Telegram
"""
import logging
from telegram import Bot
from telegram.constants import ParseMode
from bot.utils.config import TELEGRAM_CHANNEL_ID
from bot.utils.channel_store import get_channels

from bot.utils.telegram_utils import normalize_chat_id

logger = logging.getLogger(__name__)

async def publish_to_telegram(bot: Bot, message_text: str, photo_url_or_id: str | None = None) -> bool:
    """
    Publica a mensagem no canal configurado e nos canais extras adicionados.
    Se photo_url_or_id for fornecido, tenta postar como imagem + caption.
    Senão, posta apenas como texto.
    """
    # Junta o canal base com os canais extra
    raw_destinos = [TELEGRAM_CHANNEL_ID]
    for ch in get_channels():
        if ch not in raw_destinos:
            raw_destinos.append(ch)
            
    # Normaliza todos os IDs
    canais_destino = [normalize_chat_id(cid) for cid in raw_destinos if cid]
    
    sucesso_algum = False

    for chat_id in canais_destino:
        try:
            logger.info(f"[PUBLISHER_TELEGRAM] 📡 DISPARANDO PARA: {chat_id}")
            
            # Tenta enviar com foto se houver URL
            if photo_url_or_id:
                try:
                    import httpx
                    # Baixa a imagem localmente para evitar que a API do Telegram trave (timeout)
                    logger.info(f"[PUBLISHER_TELEGRAM] Baixando imagem da URL (timeout=8s): {photo_url_or_id[:60]}...")
                    async with httpx.AsyncClient() as client:
                        resp = await client.get(photo_url_or_id, timeout=8.0)
                        resp.raise_for_status()
                        photo_bytes = resp.content

                    logger.info(f"[PUBLISHER_TELEGRAM] Enviando foto baixada ao Telegram...")
                    await bot.send_photo(
                        chat_id=chat_id,
                        photo=photo_bytes,
                        caption=message_text,
                        parse_mode=ParseMode.HTML,
                        read_timeout=15,
                        write_timeout=15,
                        connect_timeout=15
                    )
                    logger.info(f"[PUBLISHER_TELEGRAM] Foto enviada ao canal {chat_id} com sucesso.")
                    sucesso_algum = True
                    continue # Próximo canal
                except Exception as photo_err:
                    logger.warning(f"[PUBLISHER_TELEGRAM] Falha ao processar foto para {chat_id}: {photo_err}. Tentando fallback de texto...")
                    # Fallback para texto abaixo
            
            # Envio de Texto (ou fallback se a foto falhou)
            await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=False # Deixa preview para mostrar a imagem do link se o bot falhou na foto
            )
            logger.info(f"[PUBLISHER_TELEGRAM] Mensagem (texto) enviada ao canal {chat_id} com sucesso.")
            sucesso_algum = True
            
        except Exception as e:
            err_msg = f"Falha crítica ao enviar para o canal {chat_id}: {str(e)}"
            logger.error(f"[PUBLISHER_TELEGRAM] {err_msg}")
            # Não engole o erro se for o único destino
            if len(canais_destino) == 1:
                raise Exception(err_msg)
            
    if not sucesso_algum:
        raise Exception(f"Falha ao publicar no Telegram em todos os destinos: {canais_destino}")
        
    return True
