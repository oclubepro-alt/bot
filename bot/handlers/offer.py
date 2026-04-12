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
from bot.utils.formatter import build_offer_message, build_preview_message

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
        "📦 *Passo 1/6* — Qual é o *nome do produto*?",
        parse_mode=ParseMode.MARKDOWN,
    )
    return NOME

async def receber_nome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome = update.message.text.strip()
    context.user_data["nome"] = nome
    await update.message.reply_text(
        f"✅ Produto: *{nome}*\n\n💰 *Passo 2/6* — Qual é o *preço*? (ex: R$ 49,90)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return PRECO

async def receber_preco(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    preco = update.message.text.strip()
    context.user_data["preco"] = preco
    keyboard = [[InlineKeyboardButton(loja, callback_data=f"loja_{loja}")] for loja in LOJAS]
    await update.message.reply_text(
        f"✅ Preço: *{preco}*\n\n🏪 *Passo 3/6* — Escolha a *loja*:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return LOJA

async def receber_loja(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    loja = query.data.replace("loja_", "")
    context.user_data["loja"] = loja
    await query.edit_message_text(
        f"✅ Loja: *{loja}*\n\n🔗 *Passo 4/6* — Cole o *link do produto/afiliado*:",
        parse_mode=ParseMode.MARKDOWN,
    )
    return LINK

async def receber_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link = update.message.text.strip()
    context.user_data["link"] = link
    await update.message.reply_text(
        "✅ Link salvo!\n\n📸 *Passo 5/6* — Envie uma *imagem* (ou envie /pular):",
        parse_mode=ParseMode.MARKDOWN,
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
        "📝 *Passo 6/6* — Alguma *descrição adicional*? (opcional — /pular para ignorar)",
        parse_mode=ParseMode.MARKDOWN,
    )

async def receber_descricao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["descricao"] = update.message.text.strip()
    return await _processar_e_exibir_previa(update, context)

async def pular_descricao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["descricao"] = None
    return await _processar_e_exibir_previa(update, context)

async def _processar_e_exibir_previa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dados = context.user_data
    aguardo = await update.message.reply_text("⏳ Gerando legenda com IA... aguarde!")

    legenda = await generate_caption(
        nome=dados["nome"],
        preco=dados["preco"],
        loja=dados["loja"],
        descricao=dados.get("descricao"),
    )
    
    mensagem_final = build_offer_message(
        nome=dados["nome"], preco=dados["preco"],
        loja=dados["loja"], link=dados["link"], legenda_ia=legenda
    )
    context.user_data["mensagem_final"] = mensagem_final

    await aguardo.delete()

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar Envio", callback_data=CB_CONFIRMAR),
            InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_OFERTA),
        ],
        [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_VOLTAR_MENU)]
    ]

    if dados.get("foto_id"):
        await update.message.reply_photo(
            photo=dados["foto_id"],
            caption=build_preview_message(mensagem_final),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    else:
        await update.message.reply_text(
            build_preview_message(mensagem_final),
            parse_mode=ParseMode.MARKDOWN,
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

    try:
        await publish_offer(context.bot, mensagem, foto_id)
        msg_sucesso = "🎉 *Oferta manual publicada com sucesso!*"
        try: # Try editing message if possible, else reply.
            if foto_id:
                await query.message.delete()
                await context.bot.send_message(
                    chat_id=update.effective_chat.id, 
                    text=msg_sucesso, 
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=back_keyboard
                )
            else:
                await query.edit_message_text(
                    msg_sucesso, 
                    parse_mode=ParseMode.MARKDOWN,
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
