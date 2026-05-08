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
from bot.services.scheduler_service import is_monitor_active, start_monitor, stop_monitor, _run_scan

async def monitor_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe o menu de controle do monitoramento automático."""
    query = update.callback_query
    if query:
        await query.answer()
    
    active = is_monitor_active(context.application)
    status_text = "🟢 <b>ATIVO</b>" if active else "🔴 <b>PARADO</b>"
    
    texto = (
        "🔍 <b>Monitoramento Automático</b>\n\n"
        f"Status: {status_text}\n\n"
        "O monitor busca novas ofertas automaticamente nas fontes configuradas. "
        "Você pode iniciar o ciclo ou fazer uma busca manual agora."
    )
    
    keyboard = []
    # Botão de Varredura Imediata
    keyboard.append([InlineKeyboardButton("⚡ Buscar 10 Ofertas Agora", callback_data="monitor_scrape_now")])

    if not active:
        keyboard.append([InlineKeyboardButton("🚀 Iniciar Ciclo de Varredura", callback_data=CB_MONITOR_START)])
    else:
        keyboard.append([InlineKeyboardButton("🛑 Parar Ciclo de Varredura", callback_data=CB_MONITOR_STOP)])
        
    keyboard.append([InlineKeyboardButton("🏠 Voltar ao Menu Principal", callback_data=CB_MENU_PRINCIPAL)])

    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if query:
        await query.edit_message_text(texto, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
    else:
        await update.message.reply_text(texto, parse_mode=ParseMode.HTML, reply_markup=reply_markup)


async def monitor_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Executa a ação de ligar, desligar ou varrer agora."""
    query = update.callback_query
    action = query.data
    
    if action == "monitor_scrape_now":
        await query.answer("🚀 Iniciando busca de 10 ofertas... Veja o canal em instantes!", show_alert=True)
        try:
            # Alterado para manual=True para que o scheduler envie o feedback visual ao admin
            await _run_scan(context, limit=10, manual=True, trigger_user_id=query.from_user.id)
        except Exception as e:
            logger.error(f"[MONITOR] Erro manual scan: {e}")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"❌ Erro ao processar sua busca: {e}"
            )
        return

    await query.answer()
    
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
