"""
expiration_service.py - Monitora ofertas publicadas para detectar expiracao ou mudanca de preco.
"""
import json
import logging
import datetime
import asyncio
from pathlib import Path
from telegram import Bot
from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "published_offers.json"

def _load_db() -> list:
    try:
        if _DB_PATH.exists():
            return json.loads(_DB_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[EXPIRATION] Erro ao carregar: {e}")
    return []

def _save_db(data: list) -> None:
    try:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Mantem apenas os ultimos 500 itens para nao crescer infinitamente
        _DB_PATH.write_text(json.dumps(data[-500:], indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"[EXPIRATION] Erro ao salvar: {e}")

def register_published_offer(url: str, messages: list) -> None:
    """
    Registra uma oferta publicada para monitoramento futuro.
    messages: lista de {"chat_id": id, "message_id": id}
    """
    db = _load_db()
    db.append({
        "url": url,
        "messages": messages,
        "timestamp": datetime.datetime.now().isoformat(),
        "expired": False
    })
    _save_db(db)

async def check_expirations(bot: Bot) -> None:
    """
    Varre as ofertas das ultimas 24h e verifica se expiraram.
    Se expirou, edita a mensagem no canal.
    """
    from bot.services.product_extractor_v2 import extract_product_data_v2 as extract_product_data
    
    db = _load_db()
    now = datetime.datetime.now()
    updated = False
    
    # Verifica apenas ofertas nao expiradas das ultimas 24h
    for item in db:
        if item.get("expired"):
            continue
            
        ts = datetime.datetime.fromisoformat(item["timestamp"])
        if (now - ts).total_seconds() > 86400: # 24h
            continue
            
        logger.info(f"[EXPIRATION] Verificando URL: {item['url'][:50]}...")
        
        try:
            # Tenta extrair dados atuais
            data = await extract_product_data(item["url"])
            
            is_expired = False
            reason = ""
            
            if not data:
                is_expired = True
                reason = "Produto nao encontrado ou removido."
            elif not data.get("price"):
                is_expired = True
                reason = "Preco nao disponivel ou indisponivel."
            # Opcional: comparar preco? 
            # Se subir mais de 20%, podemos considerar "encerrada" se for promocao relâmpago
            
            if is_expired:
                logger.warning(f"[EXPIRATION] Oferta expirada detectada! {reason}")
                item["expired"] = True
                updated = True
                
                # Avisar no Telegram
                for msg_info in item["messages"]:
                    try:
                        # Edita a mensagem original para adicionar o aviso
                        # Nota: Se for foto, o caption e editado. Se for texto, o text.
                        # Buscamos a mensagem original primeiro? Nao precisa, edit_message_caption resolve.
                        
                        warning_text = "\n\n❌ <b>PROMOCAO ENCERRADA</b> ❌"
                        
                        try:
                            # Tenta editar caption (se for foto)
                            await bot.edit_message_caption(
                                chat_id=msg_info["chat_id"],
                                message_id=msg_info["message_id"],
                                caption=f"⚠️ <b>ESTA OFERTA JA EXPIROU</b> ⚠️\n{reason}{warning_text}",
                                parse_mode=ParseMode.HTML
                            )
                        except Exception:
                            # Se falhar, tenta editar texto
                            await bot.edit_message_text(
                                chat_id=msg_info["chat_id"],
                                message_id=msg_info["message_id"],
                                text=f"⚠️ <b>ESTA OFERTA JA EXPIROU</b> ⚠️\n{reason}{warning_text}",
                                parse_mode=ParseMode.HTML
                            )
                            
                        logger.info(f"[EXPIRATION] Mensagem {msg_info['message_id']} marcada como expirada.")
                    except Exception as e:
                        logger.error(f"[EXPIRATION] Erro ao editar mensagem {msg_info['message_id']}: {e}")
            
            # Pequeno delay entre verificacoes para nao ser bloqueado pela loja
            await asyncio.sleep(5)
            
        except Exception as e:
            logger.error(f"[EXPIRATION] Erro ao verificar URL {item['url']}: {e}")
            
    if updated:
        _save_db(db)
