"""
monitor.py - Handler para controle manual do scheduler (Fase 3)
Permite ligar, desligar e voltar ao menu.
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.utils.constants import (
    CB_MONITOR_MENU, CB_MONITOR_START, CB_MONITOR_STOP, CB_VOLTAR_MENU, CB_MENU_PRINCIPAL
)
from bot.services.scheduler_service import is_monitor_active, start_monitor, stop_monitor

logger = logging.getLogger(__name__)


async def monitor_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu de controle do monitoramento automático."""
    query = update.callback_query
    if query:
        await query.answer()
    
    active = is_monitor_active(context.application)
    status_text = "🟢 *ATIVO*" if active else "🔴 *PARADO*"
    
    texto = (
        f"⚙️ *Controle de Monitoramento (Fase 3)*\n\n"
        f"Status atual: {status_text}\n\n"
        "O monitor varre as fontes em busca de novos produtos. "
        "Você receberá uma notificação para aprovar cada achado."
    )
    
    keyboard = []
    if not active:
        keyboard.append([InlineKeyboardButton("🚀 Iniciar Monitoramento", callback_data=CB_MONITOR_START)])
    else:
        keyboard.append([InlineKeyboardButton("🛑 Parar Monitoramento", callback_data=CB_MONITOR_STOP)])
        
    keyboard.append([InlineKeyboardButton("🔙 Voltar ao Menu Principal", callback_data=CB_MENU_PRINCIPAL)])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(texto, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(texto, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)


async def monitor_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Executa a ação de ligar ou desligar o monitor."""
    query = update.callback_query
    await query.answer()
    
    action = query.data
    
    if action == CB_MONITOR_START:
        start_monitor(context.application)
    elif action == CB_MONITOR_STOP:
        stop_monitor(context.application)
    
    # Atualiza o menu com o novo status
    await monitor_menu_handler(update, context)


async def voltar_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Retorna ao menu principal (/start)."""
    from bot.handlers.start import start_command
    query = update.callback_query
    await query.answer()
    
    # Como o start_command usa update.message, precisamos adaptar 
    # se viermos de um callback_query
    if query:
        # Remove a mensagem do menu do monitor para mostrar o principal
        await query.message.delete()
        
    # Chama o start_command (que envia uma nova mensagem)
    # Mockamos o update para que o start_command funcione
    await start_command(update, context)
