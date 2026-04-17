"""
publisher_whatsapp.py - Responsável por enviar mensagens para o WhatsApp (via API externa)
Suporta Evolution API, Uazapi ou similares que usem requisições POST JSON.
"""
import logging
import os
import requests
from bot.utils.whatsapp_store import get_whatsapp_channels

logger = logging.getLogger(__name__)

# Configurações da API de WhatsApp (Evolution API / Uazapi)
WPP_API_URL = os.getenv("WPP_API_URL", "").strip().rstrip("/")
WPP_API_KEY = os.getenv("WPP_API_KEY", "").strip()
WPP_INSTANCE = os.getenv("WPP_INSTANCE", "achadinhos").strip()

async def publish_to_whatsapp(message_text: str, photo_url: str | None = None) -> bool:
    """
    Envia a oferta para todos os destinos WhatsApp cadastrados.
    """
    if not WPP_API_URL or not WPP_API_KEY:
        logger.warning("[PUBLISHER_WPP] API de WhatsApp não configurada no .env. Pulando.")
        return False

    destinos = get_whatsapp_channels()
    if not destinos:
        logger.info("[PUBLISHER_WPP] Nenhum destino cadastrado no banco de WhatsApp.")
        return False

    sucesso_total = True
    
    for dest in destinos:
        if not dest.get("active", True):
            continue
            
        jid = dest["jid"]
        logger.info(f"[PUBLISHER_WPP] Enviando para {dest['name']} ({jid})...")
        
        try:
            # Endpoint padrão para envio de texto ou imagem (Evolution API style)
            if photo_url:
                endpoint = f"{WPP_API_URL}/message/sendMedia/{WPP_INSTANCE}"
                payload = {
                    "number": jid,
                    "media": photo_url,
                    "mediaType": "image",
                    "caption": message_text,
                    "delay": 1200
                }
            else:
                endpoint = f"{WPP_API_URL}/message/sendText/{WPP_INSTANCE}"
                payload = {
                    "number": jid,
                    "text": message_text,
                    "delay": 1200
                }

            headers = {
                "Content-Type": "application/json",
                "apikey": WPP_API_KEY
            }

            import asyncio
            resp = await asyncio.to_thread(
                requests.post, endpoint, json=payload, headers=headers, timeout=15
            )
            
            if resp.status_code in (200, 201):
                logger.info(f"[PUBLISHER_WPP] Sucesso ao enviar para {jid}")
            else:
                logger.error(f"[PUBLISHER_WPP] Erro ({resp.status_code}) ao enviar para {jid}: {resp.text}")
                sucesso_total = False
                
        except Exception as e:
            logger.error(f"[PUBLISHER_WPP] Exceção ao enviar para {jid}: {e}")
            sucesso_total = False

    return sucesso_total
