"""
channels.py - Handler para adicionar e remover canais de publicação.
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from bot.permissions import is_admin
from bot.utils.channel_store import get_channels, add_channel, remove_channel
from bot.utils.constants import CB_GERENCIAR_CANAIS

logger = logging.getLogger(__name__)

AGUARDAR_NOVO_CANAL = 30

async def menu_canais(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not is_admin(user.id):
        await query.edit_message_text("⛔ Sem permissão.")
        return ConversationHandler.END

    canais = get_channels()
    texto = "📢 <b>CANAIS CADASTRADOS</b>\n\n"
    if not canais:
        texto += "Nenhum canal extra cadastrado.\n<i>(O canal base do .env é usado por padrão).</i>"
    else:
        for idx, ch in enumerate(canais, 1):
            texto += f"{idx}. <code>{ch}</code>\n"
    
    keyboard = []
    if canais:
        # Cria botão de remoção para cada canal
        for ch in canais:
            keyboard.append([InlineKeyboardButton(f"🗑️ Remover {ch}", callback_data=f"remove_chan|{ch}")])
            
    keyboard.append([InlineKeyboardButton("➕ Adicionar Novo Canal", callback_data="add_chan")])
    keyboard.append([InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="menu_principal")])

    if query:
        await query.edit_message_text(texto, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(texto, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
        
    return AGUARDAR_NOVO_CANAL

async def btn_add_canal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    texto = (
        "Envie o ID do canal ou Username (ex: `@meucanal` ou `-100123...`).\n"
        "Certifique-se que o Bot já é administrador desse canal antes de adicioná-lo."
    )
    # Mostra botão de cancelar local
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="menu_principal")]])
    await query.edit_message_text(texto, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    return AGUARDAR_NOVO_CANAL

async def receber_novo_canal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    novo = update.message.text.strip()
    
    if add_channel(novo):
        msg = f"✅ Canal {novo} adicionado com sucesso!"
    else:
        msg = f"ℹ️ O canal {novo} já está na lista."
        
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar aos Canais", callback_data=CB_GERENCIAR_CANAIS)]])
    await update.message.reply_text(msg, reply_markup=kb)
    return ConversationHandler.END

async def btn_remover_canal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    # query.data: 'remove_chan|@canal'
    ch = query.data.split("|")[1]
    
    if remove_channel(ch):
        msg = f"✅ Canal {ch} removido com sucesso."
    else:
        msg = f"❌ Canal {ch} não encontrado."
        
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar aos Canais", callback_data=CB_GERENCIAR_CANAIS)]])
    await query.edit_message_text(msg, reply_markup=kb)
    return ConversationHandler.END
