"""
cancel.py - Handler genérico para cancelar conversas
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from bot.utils.constants import CB_CANCELAR_MENU

logger = logging.getLogger(__name__)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela via comando /cancel."""
    context.user_data.clear()
    logger.info(f"[CANCEL] Usou /cancel.")
    await update.message.reply_text("🚫 Operação cancelada. Use /start para recomeçar.")
    return ConversationHandler.END

async def cancel_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancela via botão Cancelar do menu inline."""
    query = update.callback_query
    await query.answer()
    
    if query.data == CB_CANCELAR_MENU:
        context.user_data.clear()
        await query.edit_message_text("✅ Operação cancelada. Use /start para recomeçar.")
    
    return ConversationHandler.END
