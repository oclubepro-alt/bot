import logging
from telegram import Bot
from bot.services.publisher_telegram import publish_to_telegram
from bot.services.publisher_whatsapp import publish_to_whatsapp
from bot.services.affiliate_injector import aplicar_link_afiliado

logger = logging.getLogger(__name__)

async def publish_offer(bot: Bot, copies: str | dict, photo: str | None = None, affiliate_url: str | None = None) -> None:
    """
    Roteador responsavel por aplicar o link de afiliado final e publicar.
    Sempre passa as copias pela funcao aplicar_link_afiliado antes do disparo.
    """
    logger.info("[PUBLISHER_ROUTER] Iniciando rotina de publicacao...")
    
    # Normaliza para dict se for string
    if isinstance(copies, str):
        copies = {"telegram": copies, "whatsapp": None}

    # Se nao veio o link explicitamente, tenta pegar do dicionario de copias
    if not affiliate_url and isinstance(copies, dict):
        affiliate_url = copies.get("short_url")

    logger.info(f"[PUBLISHER_ROUTER] Preparando envio (URL={affiliate_url[:50] if affiliate_url else 'N/A'})...")

    res = []
    # 2. Publica no Telegram
    text_telegram = copies.get("telegram")
    if text_telegram:
        try:
            res = await publish_to_telegram(bot, text_telegram, photo, affiliate_url)
        except Exception as e:
            logger.error(f"[PUBLISHER_ROUTER] Erro Telegram: {e}")
            raise e

    # 3. Publica no WhatsApp (Futuro)
    
    from bot.services.metrics_service import log_event
    log_event("published")
    logger.info("[PUBLISHER_ROUTER] Rotina de publicacao concluida.")
    return res
