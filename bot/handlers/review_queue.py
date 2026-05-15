"""
review_queue.py - Handler de aprovacao manual das ofertas descobertas
automaticamente pelo scheduler.

Recebe callbacks dos botoes "Aprovar" / "Rejeitar" que o scheduler
envia para os admins e executa a publicacao (ou descarte) da oferta.
"""
import logging
import asyncio

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from html import escape as escape_html
from bot.utils.constants import (
    CB_MENU_PRINCIPAL, CB_REVIEW_APPROVE, CB_REVIEW_REJECT, CB_REVIEW_SCHEDULE, CB_REVIEW_BULK
)
from bot.services.dedup_store import mark_seen
from bot.services.publisher_router import publish_offer
from bot.utils.review_store import save_review_queue
from bot.services.link_shortener import shorten_for_publication
from bot.services.copy_builder import build_copy
from bot.services.metrics_service import log_event
from bot.services.expiration_service import register_published_offer

logger = logging.getLogger(__name__)


async def show_next_review_item(update: Update, context: ContextTypes.DEFAULT_TYPE, index: int = 0) -> None:
    """Mostra um item especifico da fila de revisao para o admin (sistema de paginas)."""
    pending: dict = context.bot_data.get("pending_offers", {})
    
    if not pending:
        msg = "✅ <b>Fila de revisao vazia!</b>\nNao ha ofertas pendentes no momento."
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏠 Menu Principal", callback_data=CB_MENU_PRINCIPAL)
        ]])
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)
            except:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        else:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # Garante que o index esta dentro dos limites
    count = len(pending)
    if index >= count: index = 0
    if index < 0: index = count - 1

    # Pega o item pelo index
    offer_id = list(pending.keys())[index]
    offer = pending[offer_id]
    
    # Prepara a previa
    nome = offer.get("nome", "Produto")
    imagem = offer.get("imagem")
    affiliate_url = offer.get("affiliate_url", "")
    original_url = offer.get("original_url", offer.get("product_url", ""))
    dados = offer.get("dados_produto", {})
    
    is_fidelity = offer.get("preserve_fidelity", False)
    
    if is_fidelity:
        preview_text = (
            f"📋 <b>REVISAO DE FILA (FORWARD)</b> (Pagina {index + 1} de {count})\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"✨ <b>MODO FIDELIDADE ABSOLUTA</b>\n\n"
            f"{offer.get('copy', 'Sem texto')}\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔗 <b>Link Original:</b> {escape_html(original_url[:50])}...\n"
            f"🔗 <b>Seu Link:</b> {escape_html(affiliate_url[:50])}..."
        )
    else:
        preview_text = (
            f"📋 <b>REVISAO DE FILA</b> (Pagina {index + 1} de {count})\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"📦 <b>{escape_html(nome)}</b>\n"
            f"💰 <b>Preco:</b> {escape_html(dados.get('preco', '—'))}"
            + (f"  <s>{escape_html(dados.get('preco_original', ''))}</s>" if dados.get('preco_original') else "") + "\n\n"
            f"🌐 <b>Link original:</b>\n<code>{escape_html(original_url)}</code>\n\n"
            f"🔗 <b>Seu link:</b>\n<code>{escape_html(affiliate_url)}</code>\n\n"
            "⚠️ <i>O link sera encurtado ao publicar.</i>"
        )

    nav_row = []
    if count > 1:
        nav_row = [
            InlineKeyboardButton("⬅️ Anterior", callback_data=f"review_view:{index - 1}"),
            InlineKeyboardButton("Proxima ➡️",    callback_data=f"review_view:{index + 1}"),
        ]

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Aprovar",  callback_data=f"{CB_REVIEW_APPROVE}:{offer_id}"),
            InlineKeyboardButton("⏰ Agendar",  callback_data=f"{CB_REVIEW_SCHEDULE}:{offer_id}"),
            InlineKeyboardButton("❌ Rejeitar", callback_data=f"{CB_REVIEW_REJECT}:{offer_id}"),
        ],
        [InlineKeyboardButton("✏️ Corrigir",   callback_data=f"review_corrigir:{offer_id}")],
        nav_row if nav_row else [],
        [
            InlineKeyboardButton("✅ Aprovar Tudo", callback_data="review_bulk:approve_all"),
            InlineKeyboardButton("🚫 Limpar Fila",  callback_data="review_bulk:clear_all"),
        ],
        [InlineKeyboardButton("🏠 Menu Principal", callback_data=CB_MENU_PRINCIPAL)]
    ])

    chat_id = update.effective_chat.id
    # Se veio de um callback_query (exceto o inicial), tentamos editar a mensagem/foto
    if update.callback_query:
        query = update.callback_query
        try:
            if imagem and query.message.photo:
                # Se ja tem foto e o novo item tem foto, editamos a media
                from telegram import InputMediaPhoto
                await query.edit_message_media(
                    media=InputMediaPhoto(media=imagem, caption=preview_text, parse_mode=ParseMode.HTML),
                    reply_markup=keyboard
                )
                return
            else:
                # Se mudou de 'com foto' para 'sem foto' (ou vice versa), deletamos e enviamos nova
                await query.message.delete()
        except Exception:
            pass

    # Envio normal
    if imagem:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=imagem,
            caption=preview_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=preview_text,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )


async def start_review_queue(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando /revisar ou clique no menu."""
    if update.callback_query:
        await update.callback_query.answer()
    
    # Se veio de callback (ex: menu), limpa a mensagem anterior se possivel
    # Mas como show_next_review envia fotos/mensagens novas, apenas chamamos
    await show_next_review_item(update, context)


async def handle_review_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Processa o clique em Aprovar, Rejeitar ou Bulk de uma oferta da fila automatica.
    """
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    parts = callback_data.split(":", 1)
    action = parts[0]
    offer_id = parts[1] if len(parts) > 1 else None

    if action == "review_bulk":
        return await handle_review_bulk_callback(update, context)

    if action == "review_view":
        index = int(offer_id) if offer_id else 0
        return await show_next_review_item(update, context, index=index)

    if action == "review_corrigir":
        from bot.handlers.offer_by_link import review_corrigir_starter
        return await review_corrigir_starter(update, context)

    if not offer_id:
        await query.edit_message_text("⚠️ Nao foi possivel identificar a oferta.")
        return

    # Recupera a oferta armazenada temporariamente no bot_data
    pending: dict = context.bot_data.get("pending_offers", {})
    offer = pending.get(offer_id)

    if not offer:
        await query.edit_message_text(
            "⚠️ Esta oferta ja foi processada ou expirou."
        )
        return

    product_url: str = offer.get("product_url", "")
    imagem: str | None = offer.get("imagem")
    nome: str = offer.get("nome", "produto")
    affiliate_url: str = offer.get("affiliate_url", "")

    if action == CB_REVIEW_APPROVE:
        logger.info(f"[REVIEW] Admin {query.from_user.id} APROVOU oferta: '{nome}'")
        try:
            # Encurta o link AGORA (apenas no momento da publicacao no canal)
            logger.info(f"[REVIEW] Encurtando link: {affiliate_url[:60]}")
            short_url = await asyncio.to_thread(shorten_for_publication, affiliate_url)
            logger.info(f"[REVIEW] Link encurtado: {short_url}")

            # Reconstroi a copy com o link curto para o canal
            if offer.get("preserve_fidelity"):
                # Se for fidelidade absoluta, usamos a copy original (ja processada)
                # O encurtamento do link principal no botao e feito pelo publish_offer
                copies_final = offer.get("copy", "Sem legenda")
            else:
                dados = offer.get("dados_produto", {})
                store_key = offer.get("store_key", "amazon")
                copy_ia   = offer.get("copy_ia")
                copies_final = build_copy(
                    nome=dados.get("titulo", nome),
                    preco=dados.get("preco", "Preco nao disponivel"),
                    loja=dados.get("store", "Loja"),
                    store_key=store_key,
                    short_url=short_url,
                    legenda_ia=copy_ia,
                    preco_original=dados.get("preco_original"),
                    cupom=offer.get("cupom"),
                    product_url=product_url,
                )

            sent_msgs = await publish_offer(context.bot, copies_final, imagem, short_url)
            if sent_msgs and isinstance(sent_msgs, list):
                register_published_offer(product_url, sent_msgs)
            mark_seen(product_url)

            # Feedback temporario de sucesso removido para mostrar o PROXIMO item imediatamente
            if imagem:
                await query.message.delete()
            else:
                await query.edit_message_text("✅ Processado.")
            
            # Chama o proximo automaticamente
            log_event("approved")
            await show_next_review_item(update, context)

        except Exception as e:
            logger.error(f"[REVIEW] Erro ao publicar: {e}", exc_info=True)
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Erro ao publicar: {e}",
            )

    elif action == CB_REVIEW_REJECT:
        logger.info(f"[REVIEW] Admin {query.from_user.id} REJEITOU oferta: '{nome}'")
        mark_seen(product_url)
        
        if imagem:
            await query.message.delete()
        else:
            await query.edit_message_text("❌ Rejeitado.")
        
        # Chama o proximo automaticamente
        log_event("rejected")
        await show_next_review_item(update, context)

    elif action == CB_REVIEW_SCHEDULE:
        logger.info(f"[REVIEW] Admin {query.from_user.id} AGENDOU oferta: '{nome}'")
        from bot.services.scheduler_queue_service import add_to_queue
        pos = add_to_queue(offer)
        
        await query.answer(f"⏰ Agendado! Posicao na fila: {pos}", show_alert=True)
        
        if imagem:
            try:
                await query.message.delete()
            except Exception:
                pass
        else:
            await query.edit_message_text("⏰ Agendado.")
        
        # Chama o proximo automaticamente
        await show_next_review_item(update, context)

    # Remove da fila apenas se for acao individual
    if action in [CB_REVIEW_APPROVE, CB_REVIEW_REJECT, CB_REVIEW_SCHEDULE]:
        pending.pop(offer_id, None)
        context.bot_data["pending_offers"] = pending
        save_review_queue(pending)


async def handle_review_bulk_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Processa acoes em massa na fila de revisao."""
    query = update.callback_query
    await query.answer()

    action = query.data.split(":", 1)[1]
    pending: dict = context.bot_data.get("pending_offers", {})

    # Botao de volta consistente
    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="monitor_voltar")
    ]])

    if action == "clear_all":
        count = len(pending)
        # Marca todos como vistos para nao reaparecerem
        for offer in pending.values():
            try:
                mark_seen(offer.get("product_url", ""))
            except: pass
        
        context.bot_data["pending_offers"] = {}
        save_review_queue({})
        
        texto_sucesso = f"🚫 <b>Fila limpa!</b>\n{count} ofertas foram descartadas."
        
        try:
            # Se a mensagem original tem foto, nao podemos usar edit_message_text
            if query.message.photo:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=texto_sucesso,
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard
                )
            else:
                await query.edit_message_text(
                    texto_sucesso,
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard
                )
        except Exception as e:
            logger.error(f"[REVIEW] Erro ao editar msg de limpeza: {e}")
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=texto_sucesso,
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard
            )
        
        logger.warning(f"[REVIEW] Fila de revisao limpa pelo admin {query.from_user.id}.")
        log_event("rejected") # Bulk clear counts as rejected for metrics

    elif action == "approve_all":
        count = len(pending)
        try:
            if query.message.photo:
                await query.message.edit_caption(f"⏳ <b>Aprovando {count} ofertas...</b>\nPode levar alguns segundos.", parse_mode=ParseMode.HTML)
            else:
                await query.edit_message_text(f"⏳ <b>Aprovando {count} ofertas...</b>\nPode levar alguns segundos.", parse_mode=ParseMode.HTML)
        except: pass
        
        success_count = 0
        offer_ids = list(pending.keys())
        
        for oid in offer_ids:
            offer = pending.get(oid)
            if not offer: continue
            
            try:
                aff_url = offer.get("affiliate_url", "")
                short_url = await asyncio.to_thread(shorten_for_publication, aff_url) if aff_url else ""

                if offer.get("preserve_fidelity"):
                    copies_final = offer.get("copy", "Sem legenda")
                else:
                    dados     = offer.get("dados_produto", {})
                    store_key = offer.get("store_key", "amazon")
                    copy_ia   = offer.get("copy_ia")
                    nome_offer = offer.get("nome", "produto")

                    copies_final = build_copy(
                        nome=dados.get("titulo", nome_offer),
                        preco=dados.get("preco", "Preco nao disponivel"),
                        loja=dados.get("store", "Loja"),
                        store_key=store_key,
                        short_url=short_url or aff_url,
                        legenda_ia=copy_ia,
                        preco_original=dados.get("preco_original"),
                        cupom=offer.get("cupom"),
                    )

                sent_msgs = await publish_offer(context.bot, copies_final, offer.get("imagem"), short_url)
                if sent_msgs and isinstance(sent_msgs, list):
                    from bot.services.expiration_service import register_published_offer
                    register_published_offer(offer.get("product_url", ""), sent_msgs)
                
                mark_seen(offer.get("product_url", ""))
                success_count += 1
                if success_count % 3 == 0:
                    await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"[REVIEW] Falha ao aprovar em massa item {oid}: {e}")

        context.bot_data["pending_offers"] = {}
        save_review_queue({})

        texto_final = f"✅ <b>Sucesso!</b>\n{success_count} ofertas publicadas no canal."
        
        try:
            if query.message.photo:
                await query.message.delete()
            
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=texto_final,
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard
            )
        except:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=texto_final,
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard
            )
            
        log_event("approved")
        logger.info(f"[REVIEW] Aprovacao em massa concluida: {success_count}/{count} por admin {query.from_user.id}.")

import asyncio # Ensure asyncio is available for sleep
