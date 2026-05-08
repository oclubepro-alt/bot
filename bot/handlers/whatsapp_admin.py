"""
whatsapp_admin.py - Gerenciamento de destinos do WhatsApp
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode

from bot.permissions import is_admin
from bot.utils.whatsapp_store import get_whatsapp_channels, add_whatsapp_channel, remove_whatsapp_channel
from bot.utils.constants import CB_GERENCIAR_WHATS

logger = logging.getLogger(__name__)

# Estados
AGUARDAR_JID_WHATS = 40

async def menu_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
    
    user = update.effective_user
    if not is_admin(user.id):
        return ConversationHandler.END

    channels = get_whatsapp_channels()
    
    texto = "🟢 <b>GERENCIAR WHATSAPP</b>\n\n"
    if not channels:
        texto += "Nenhum destino (grupo/canal) cadastrado."
    else:
        for idx, c in enumerate(channels, 1):
            texto += f"{idx}. <b>{c['name']}</b>\n<code>{c['jid']}</code>\n\n"

    keyboard = []
    if channels:
        for c in channels:
            keyboard.append([InlineKeyboardButton(f"🗑️ Remover {c['name']}", callback_data=f"del_wpp|{c['jid']}")])
    
    keyboard.append([InlineKeyboardButton("➕ Adicionar Novo Destino", callback_data="add_wpp")])
    keyboard.append([InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="menu_principal")])

    if query:
        await query.edit_message_text(texto, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(texto, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))

    return AGUARDAR_JID_WHATS

async def btn_add_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    texto = (
        "✍️ *Adicionar Destino WhatsApp*\n\n"
        "Envie o nome e o JID do grupo/canal no formato:\n"
        "`Nome | JID`\n\n"
        "Exemplo:\n"
        "`Promoções TOP | 1203632948102@g.us`"
    )
    keyboard = [[InlineKeyboardButton("❌ Cancelar", callback_data=CB_GERENCIAR_WHATS)]]
    await query.edit_message_text(texto, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(keyboard))
    return AGUARDAR_JID_WHATS

async def receber_jid_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if "|" not in text:
        await update.message.reply_text("❌ Formato inválido. Use: `Nome | JID`")
        return AGUARDAR_JID_WHATS

    nome, jid = [x.strip() for x in text.split("|", 1)]
    
    if add_whatsapp_channel(nome, jid):
        await update.message.reply_text(f"✅ Destino *{nome}* adicionado!")
    else:
        await update.message.reply_text("ℹ️ Este JID já está cadastrado.")

    # Volta pro menu
    return await menu_whatsapp(update, context)

async def btn_remover_whatsapp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    jid = query.data.split("|")[1]
    if remove_whatsapp_channel(jid):
        await query.answer("Removido com sucesso!")
    else:
        await query.answer("Erro ao remover.")
    
    return await menu_whatsapp(update, context)
