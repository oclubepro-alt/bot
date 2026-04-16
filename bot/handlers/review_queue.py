"""
review_queue.py - Handler de aprovação manual das ofertas descobertas
automaticamente pelo scheduler.

Recebe callbacks dos botões "Aprovar" / "Rejeitar" que o scheduler
envia para os admins e executa a publicação (ou descarte) da oferta.
"""
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.utils.constants import CB_REVIEW_APPROVE, CB_REVIEW_REJECT, CB_MENU_PRINCIPAL
from bot.services.dedup_store import mark_seen
from bot.services.publisher_router import publish_offer

logger = logging.getLogger(__name__)


async def handle_review_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Processa o clique em Aprovar ou Rejeitar de uma oferta da fila automática.
    O dado da oferta é carregado a partir do bot_data (preenchido pelo scheduler).
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data  # ex: "review_aprovar:abc123" ou "review_rejeitar:abc123"
    parts = callback_data.split(":", 1)
    action = parts[0]
    offer_id = parts[1] if len(parts) > 1 else None

    if not offer_id:
        await query.edit_message_text("⚠️ Não foi possível identificar a oferta.")
        return

    # Recupera a oferta armazenada temporariamente no bot_data
    pending: dict = context.bot_data.get("pending_offers", {})
    offer = pending.get(offer_id)

    if not offer:
        await query.edit_message_text(
            "⚠️ Esta oferta já foi processada ou expirou."
        )
        return

    product_url: str = offer.get("product_url", "")
    mensagem: str = offer.get("mensagem", "")
    imagem: str | None = offer.get("imagem")
    nome: str = offer.get("nome", "produto")
    source_name: str = offer.get("source_name", "—")

    if action == CB_REVIEW_APPROVE:
        logger.info(f"[REVIEW] Admin {query.from_user.id} APROVOU oferta: '{nome}' | fonte: {source_name}")
        try:
            await publish_offer(context.bot, mensagem, imagem)
            mark_seen(product_url)  # Marca como visto apenas ao confirmar publicação

            success_text = (
                f"✅ <b>Oferta publicada no canal!</b>\n\n"
                f"🔹 <b>Produto:</b> {nome}\n"
                f"🔹 <b>Fonte:</b> {source_name}"
            )
            back_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)
            ]])
            try:
                if imagem:
                    await query.message.delete()
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=success_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=back_keyboard
                    )
                else:
                    await query.edit_message_text(
                        success_text, 
                        parse_mode=ParseMode.HTML,
                        reply_markup=back_keyboard
                    )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"[REVIEW] Erro ao publicar oferta aprovada: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Erro ao publicar: <code>{e}</code>",
                parse_mode=ParseMode.HTML,
            )

    elif action == CB_REVIEW_REJECT:
        logger.info(f"[REVIEW] Admin {query.from_user.id} REJEITOU oferta: '{nome}' | fonte: {source_name}")
        mark_seen(product_url)  # Rejeitar também marca como visto para não reaparecer
        try:
            reject_text = f"❌ <b>Oferta rejeitada.</b> <code>{nome}</code> não será publicada."
            back_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)
            ]])
            if imagem:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=reject_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_keyboard
                )
            else:
                await query.edit_message_text(
                    reject_text, 
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_keyboard
                )
        except Exception:
            pass

    # Remove da fila
    pending.pop(offer_id, None)
    context.bot_data["pending_offers"] = pending
