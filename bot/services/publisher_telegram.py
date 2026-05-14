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

async def publish_to_telegram(bot: Bot, message_text: str, photo_url_or_id: str | None = None, affiliate_url: str | None = None) -> bool:
    """
    Publica a mensagem no canal configurado e nos canais extras adicionados.
    Se photo_url_or_id for fornecido, tenta postar como imagem + caption.
    Se affiliate_url for fornecido, adiciona um botão no rodapé.
    """
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton
    
    # Prepara o teclado se houver link de afiliado
    reply_markup = None
    if affiliate_url:
        reply_markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 PEGAR OFERTA", url=affiliate_url)]
        ])

    # Junta o canal base com os canais extra
    raw_destinos = [TELEGRAM_CHANNEL_ID]
    for ch in get_channels():
        if ch not in raw_destinos:
            raw_destinos.append(ch)
            
    # Normaliza todos os IDs
    canais_destino = [normalize_chat_id(cid) for cid in raw_destinos if cid]
    
    sucesso_algum = False
    sent_messages = []

    for chat_id in canais_destino:
        try:
            logger.info(f"[PUBLISHER_TELEGRAM] 📡 DISPARANDO PARA: {chat_id}")
            
            msg = None
            # Tenta enviar com foto se houver URL ou ID
            if photo_url_or_id:
                try:
                    # Se for um dicionário (padrão do forward_publisher)
                    if isinstance(photo_url_or_id, dict):
                        m_type = photo_url_or_id.get("type", "photo")
                        m_id = photo_url_or_id.get("file_id")
                        if m_type == "photo" and m_id:
                            msg = await bot.send_photo(
                                chat_id=chat_id,
                                photo=m_id,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                        elif m_type == "video" and m_id:
                            msg = await bot.send_video(
                                chat_id=chat_id,
                                video=m_id,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )
                    
                    # Se for uma string
                    elif isinstance(photo_url_or_id, str):
                        # Se parece uma URL
                        if photo_url_or_id.startswith(("http://", "https://")):
                            import httpx
                            # Baixa a imagem localmente para evitar que a API do Telegram trave (timeout)
                            logger.info(f"[PUBLISHER_TELEGRAM] Baixando imagem da URL (timeout=8s): {photo_url_or_id[:60]}...")
                            async with httpx.AsyncClient() as client:
                                resp = await client.get(photo_url_or_id, timeout=8.0)
                                resp.raise_for_status()
                                photo_bytes = resp.content

                            logger.info(f"[PUBLISHER_TELEGRAM] Enviando foto baixada ao Telegram...")
                            msg = await bot.send_photo(
                                chat_id=chat_id,
                                photo=photo_bytes,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup,
                                read_timeout=15,
                                write_timeout=15,
                                connect_timeout=15
                            )
                        else:
                            # Assume que é um file_id do Telegram
                            msg = await bot.send_photo(
                                chat_id=chat_id,
                                photo=photo_url_or_id,
                                caption=message_text,
                                parse_mode=ParseMode.HTML,
                                reply_markup=reply_markup
                            )

                    if msg:
                        logger.info(f"[PUBLISHER_TELEGRAM] Mídia enviada ao canal {chat_id} com sucesso.")
                        sent_messages.append({"chat_id": chat_id, "message_id": msg.message_id})
                        sucesso_algum = True
                        continue # Próximo canal
                except Exception as photo_err:
                    logger.warning(f"[PUBLISHER_TELEGRAM] Falha ao processar mídia para {chat_id}: {photo_err}. Tentando fallback de texto...")
                    # Fallback para texto abaixo
            
            # Envio de Texto (ou fallback se a foto falhou)
            msg = await bot.send_message(
                chat_id=chat_id,
                text=message_text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=False
            )
            logger.info(f"[PUBLISHER_TELEGRAM] Mensagem (texto) enviada ao canal {chat_id} com sucesso.")
            sent_messages.append({"chat_id": chat_id, "message_id": msg.message_id})
            sucesso_algum = True
            
        except Exception as e:
            err_msg = f"Falha crítica ao enviar para o canal {chat_id}: {str(e)}"
            logger.error(f"[PUBLISHER_TELEGRAM] {err_msg}")
            # Não engole o erro se for o único destino
            if len(canais_destino) == 1:
                raise Exception(err_msg)
            
    if not sucesso_algum:
        raise Exception(f"Falha ao publicar no Telegram em todos os destinos: {canais_destino}")
        
    return sent_messages
