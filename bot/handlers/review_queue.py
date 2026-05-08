"""
review_queue.py - Handler de aprovação manual das ofertas descobertas
automaticamente pelo scheduler.

Recebe callbacks dos botões "Aprovar" / "Rejeitar" que o scheduler
envia para os admins e executa a publicação (ou descarte) da oferta.
"""
import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.utils.constants import CB_REVIEW_APPROVE, CB_REVIEW_REJECT, CB_MENU_PRINCIPAL
from bot.services.dedup_store import mark_seen
from bot.services.publisher_router import publish_offer
from bot.utils.review_store import save_review_queue
from bot.services.link_shortener import shorten_for_publication
from bot.services.copy_builder import build_copy

logger = logging.getLogger(__name__)


async def handle_review_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Processa o clique em Aprovar, Rejeitar ou Bulk de uma oferta da fila automática.
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    parts = callback_data.split(":", 1)
    action = parts[0]
    offer_id = parts[1] if len(parts) > 1 else None

    if action == "review_bulk":
        return await handle_review_bulk_callback(update, context)

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
    imagem: str | None = offer.get("imagem")
    nome: str = offer.get("nome", "produto")
    affiliate_url: str = offer.get("affiliate_url", "")

    if action == CB_REVIEW_APPROVE:
        logger.info(f"[REVIEW] Admin {query.from_user.id} APROVOU oferta: '{nome}'")
        try:
            # Encurta o link AGORA (apenas no momento da publicação no canal)
            logger.info(f"[REVIEW] Encurtando link: {affiliate_url[:60]}")
            short_url = await asyncio.to_thread(shorten_for_publication, affiliate_url)
            logger.info(f"[REVIEW] Link encurtado: {short_url}")

            # Reconstrói a copy com o link curto para o canal
            dados = offer.get("dados_produto", {})
            store_key = offer.get("store_key", "amazon")
            copy_ia   = offer.get("copy_ia")
            copies_final = build_copy(
                nome=dados.get("titulo", nome),
                preco=dados.get("preco", "Preço não disponível"),
                loja=dados.get("store", "Loja"),
                store_key=store_key,
                short_url=short_url,
                legenda_ia=copy_ia,
                preco_original=dados.get("preco_original"),
                cupom=offer.get("cupom"),
            )

            await publish_offer(context.bot, copies_final, imagem)
            mark_seen(product_url)

            success_text = (
                f"✅ <b>Publicado no canal!</b>\n"
                f"🔹 <b>Produto:</b> {nome}\n"
                f"🔗 <b>Link:</b> <code>{short_url}</code>"
            )
            back_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)
            ]])
            if imagem:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=success_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard,
                )
            else:
                await query.edit_message_text(
                    success_text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard,
                )

        except Exception as e:
            logger.error(f"[REVIEW] Erro ao publicar: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Erro ao publicar: {e}",
            )

    elif action == CB_REVIEW_REJECT:
        logger.info(f"[REVIEW] Admin {query.from_user.id} REJEITOU oferta: '{nome}'")
        mark_seen(product_url)  # marca como visto para não reaparecer na varredura
        reject_text = f"❌ <b>Oferta rejeitada.</b> <code>{nome}</code>"
        back_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)]])
        if imagem:
            await query.message.delete()
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=reject_text,
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard,
            )
        else:
            await query.edit_message_text(
                reject_text,
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard,
            )

    # Remove da fila apenas se for ação individual
    if action in [CB_REVIEW_APPROVE, CB_REVIEW_REJECT]:
        pending.pop(offer_id, None)
        context.bot_data["pending_offers"] = pending
        save_review_queue(pending)


async def handle_review_bulk_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Processa ações em massa na fila de revisão."""
    query = update.callback_query
    await query.answer()

    action = query.data.split(":", 1)[1]
    pending: dict = context.bot_data.get("pending_offers", {})

    if not pending:
        await query.edit_message_text("⚠️ A fila já está vazia.")
        return

    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)
    ]])

    if action == "clear_all":
        count = len(pending)
        # Marca todos como vistos para não reaparecerem
        for offer in pending.values():
            mark_seen(offer.get("product_url", ""))
        
        context.bot_data["pending_offers"] = {}
        save_review_queue({})
        await query.edit_message_text(
            f"🚫 <b>Fila limpa!</b>\n{count} ofertas foram descartadas e marcadas como vistas.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard
        )
        logger.warning(f"[REVIEW] Fila de revisão limpa pelo admin {query.from_user.id}.")

    elif action == "approve_all":
        count = len(pending)
        await query.edit_message_text(f"⏳ <b>Aprovando {count} ofertas...</b>\nPode levar alguns segundos.", parse_mode=ParseMode.HTML)
        
        success_count = 0
        # Copiamos as chaves porque vamos modificar o dict durante a iteração se fôssemos remover, 
        # mas aqui vamos apenas processar e limpar no final.
        offer_ids = list(pending.keys())
        
        for oid in offer_ids:
            offer = pending.get(oid)
            if not offer: continue
            
            try:
                # Encurta o link afiliado (longo) antes de publicar
                aff_url = offer.get("affiliate_url", "")
                short_url = await asyncio.to_thread(shorten_for_publication, aff_url) if aff_url else ""

                # Reconstrói a copy com o link curto
                dados     = offer.get("dados_produto", {})
                store_key = offer.get("store_key", "amazon")
                copy_ia   = offer.get("copy_ia")
                nome_offer = offer.get("nome", "produto")

                copies_final = build_copy(
                    nome=dados.get("titulo", nome_offer),
                    preco=dados.get("preco", "Preço não disponível"),
                    loja=dados.get("store", "Loja"),
                    store_key=store_key,
                    short_url=short_url or aff_url,
                    legenda_ia=copy_ia,
                    preco_original=dados.get("preco_original"),
                    cupom=offer.get("cupom"),
                )

                await publish_offer(context.bot, copies_final, offer.get("imagem"))
                mark_seen(offer.get("product_url", ""))
                success_count += 1
                # Pequeno delay para evitar rate limit
                if success_count % 3 == 0:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[REVIEW] Falha ao aprovar em massa item {oid}: {e}")

        context.bot_data["pending_offers"] = {}
        save_review_queue({})

        await query.message.reply_text(
            f"✅ <b>Sucesso!</b>\n{success_count} ofertas publicadas no canal de um total de {count}.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard
        )
        logger.info(f"[REVIEW] Aprovação em massa concluída: {success_count}/{count} por admin {query.from_user.id}.")

import asyncio # Ensure asyncio is available for sleep
