"""
offer.py - Handler para criar ofertas de forma 100% manual.
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from bot.permissions import is_admin
from bot.utils.constants import (
    LOJAS, CB_PUBLICAR_MANUAL, CB_CONFIRMAR, CB_CANCELAR_OFERTA
)
from bot.services.ai_writer import generate_caption
from bot.services.publisher_router import publish_offer
from bot.services.copy_builder import build_copy, _detect_emoji

logger = logging.getLogger(__name__)

NOME, PRECO, LOJA, LINK, IMAGEM, DESCRICAO, CONFIRMAR = range(7)

async def start_offer_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    
    if not is_admin(user.id):
        logger.warning(f"[ACESSO NEGADO] {user.id} tentou acessar publicar manual.")
        await query.edit_message_text("⛔ Você não tem permissão para publicar.")
        return ConversationHandler.END

    logger.info(f"[OFERTA MANUAL] Admin {user.id} iniciou.")
    context.user_data.clear()

    await query.edit_message_text(
        "💎 <b>OFERTA MANUAL — Passo 1/6</b>\n\n"
        "📝 Qual é o <b>nome do produto</b>?\n"
        "<i>Ex: iPhone 15 Pro Max 256GB</i>",
        parse_mode=ParseMode.HTML,
    )
    return NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome = update.message.text.strip()
    context.user_data["nome"] = nome
    await update.message.reply_text(
        f"✅ Produto: <b>{nome}</b>\n\n"
        "💰 <b>Passo 2/6</b> — Qual é o <b>preço</b>?\n"
        "<i>Ex: R$ 7.499,00</i>",
        parse_mode=ParseMode.HTML,
    )
    return PRECO

async def receber_preco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    preco = update.message.text.strip()
    context.user_data["preco"] = preco
    keyboard = [[InlineKeyboardButton(loja, callback_data=f"loja_{loja}")] for loja in LOJAS]
    await update.message.reply_text(
        f"✅ Preço: <b>{preco}</b>\n\n🏪 <b>Passo 3/6</b> — Escolha a <b>loja</b>:",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return LOJA

async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    loja = query.data.replace("loja_", "")
    context.user_data["loja"] = loja
    await query.edit_message_text(
        f"✅ Loja: <b>{loja}</b>\n\n🔗 <b>Passo 4/6</b> — Cole o <b>link do produto/afiliado</b>:",
        parse_mode=ParseMode.HTML,
    )
    return LINK

async def receber_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link = update.message.text.strip()
    context.user_data["link"] = link
    await update.message.reply_text(
        "✅ Link salvo!\n\n📸 <b>Passo 5/6</b> — Envie uma <b>imagem</b> (ou envie /pular):",
        parse_mode=ParseMode.HTML,
    )
    return IMAGEM

async def receber_imagem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["foto_id"] = update.message.photo[-1].file_id
    await _pedir_descricao(update)
    return DESCRICAO

async def pular_imagem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["foto_id"] = None
    await update.message.reply_text("⚠️ Nenhuma imagem adicionada.")
    await _pedir_descricao(update)
    return DESCRICAO

async def _pedir_descricao(update: Update):
    await update.message.reply_text(
        "📝 <b>Passo 6/6</b> — Alguma <b>descrição adicional</b>? (opcional — /pular para ignorar)",
        parse_mode=ParseMode.HTML,
    )

async def receber_descricao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["descricao"] = update.message.text.strip()
    return await _processar_e_exibir_previa(update, context)

async def pular_descricao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["descricao"] = None
    return await _processar_e_exibir_previa(update, context)

async def _processar_e_exibir_previa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dados = context.user_data
    aguardo = await update.message.reply_text("⏳ <b>Refinando sua oferta com IA...</b>", parse_mode=ParseMode.HTML)

    legenda = await generate_caption(
        nome=dados["nome"],
        preco=dados["preco"],
        loja=dados["loja"],
        descricao=dados.get("descricao"),
    )
    
    # Usa o construtor centralizado
    copy_dict = build_copy(
        nome=dados["nome"],
        preco=dados["preco"],
        loja=dados["loja"],
        store_key=dados["loja"].lower(),
        short_url=dados["link"],
        legenda_ia=legenda
    )
    
    context.user_data["mensagem_final"] = copy_dict["telegram"]
    context.user_data["copy_dict"] = copy_dict

    await aguardo.delete()

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar Envio", callback_data=CB_CONFIRMAR),
            InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_OFERTA),
        ],
        [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_VOLTAR_MENU)]
    ]

    preview_text = (
        "💎 <b>PRÉVIA — Confirme os detalhes</b>\n\n"
        f"{context.user_data['mensagem_final']}\n\n"
        "━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Link de conferência:</b>\n"
        f"<code>{dados['link']}</code>"
    )

    if dados.get("foto_id"):
        await update.message.reply_photo(
            photo=dados["foto_id"],
            caption=preview_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(
            preview_text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True,
        )
    return CONFIRMAR

async def confirmar_envio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="monitor_voltar")
    ]])

    if query.data == CB_CANCELAR_OFERTA:
        context.user_data.clear()
        await query.edit_message_text(
            "❌ Oferta cancelada.",
            reply_markup=back_keyboard
        )
        return ConversationHandler.END

    mensagem = context.user_data.get("mensagem_final", "")
    foto_id = context.user_data.get("foto_id")

    # Garante que passamos um dict p/ o publisher_router
    copy_dict = context.user_data.get("copy_dict", {
        "telegram": context.user_data.get("mensagem_final", ""),
        "whatsapp": context.user_data.get("mensagem_final", "")
    })

    try:
        await publish_offer(context.bot, copies, foto_id)
        msg_sucesso = "🎉 <b>Oferta manual publicada com sucesso!</b>"
        try: # Try editing message if possible, else reply.
            if foto_id:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, 
                    text=msg_sucesso, 
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard
                )
            else:
                await query.edit_message_text(
                    msg_sucesso, 
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard
                )
        except:
            pass
    except Exception as e:
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=f"❌ Erro ao enviar: {e}",
            reply_markup=back_keyboard
        )

    context.user_data.clear()
    return ConversationHandler.END
