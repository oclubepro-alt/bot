import logging
from telegram import Bot
from bot.services.publisher_telegram import publish_to_telegram
from bot.services.publisher_whatsapp import publish_to_whatsapp
from bot.services.affiliate_injector import aplicar_link_afiliado

logger = logging.getLogger(__name__)

async def publish_offer(bot: Bot, copies: str | dict, photo: str | None = None) -> None:
    """
    Roteador responsável por aplicar o link de afiliado final e publicar.
    Sempre passa as cópias pela função aplicar_link_afiliado antes do disparo.
    """
    logger.info("[PUBLISHER_ROUTER] Iniciando rotina de publicação...")
    
    # Normaliza para dict se for string
    if isinstance(copies, str):
        copies = {"telegram": copies, "whatsapp": None}

    # 1. Normalização (Rede de Segurança Sniper)
    # Removido aplicar_link_afiliado aqui pois ele pode quebrar tags HTML <a href>
    # Os handlers (offer.py / offer_by_link.py) já cuidam disso.
    logger.info(f"[PUBLISHER_ROUTER] Preparando envio...")

    # 2. Publica no Telegram
    text_telegram = copies.get("telegram")
    if text_telegram:
        try:
            await publish_to_telegram(bot, text_telegram, photo)
        except Exception as e:
            logger.error(f"[PUBLISHER_ROUTER] Erro Telegram: {e}")
            raise e

    # 3. Publica no WhatsApp
    # text_whatsapp = copies.get("whatsapp")
    # if text_whatsapp:
    #     try:
    #         # await publish_to_whatsapp(text_whatsapp, photo)
    #         pass
    #     except Exception as e:
    #         logger.error(f"[PUBLISHER_ROUTER] Erro WhatsApp: {e}")
    # 
    logger.info("[PUBLISHER_ROUTER] Rotina de publicação concluída.")
