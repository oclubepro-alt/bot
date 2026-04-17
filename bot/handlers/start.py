"""
start.py - Handler de /start e menus
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.utils.constants import (
    CB_PUBLICAR_MANUAL, CB_PUBLICAR_LINK, CB_CANCELAR_MENU, CB_MONITOR_MENU, CB_GERENCIAR_WHATS
)

logger = logging.getLogger(__name__)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exibe mensagem de boas-vindas com menu inline."""
    user = update.effective_user
    logger.info(f"[START] Usuário: {user.id} ({user.username}) abriu o menu.")

    keyboard = [
        [InlineKeyboardButton("📢 Publicar Oferta Manual", callback_data=CB_PUBLICAR_MANUAL)],
        [InlineKeyboardButton("🔗 Publicar por Link", callback_data=CB_PUBLICAR_LINK)],
        [InlineKeyboardButton("⚙️ Configurar Afiliado", callback_data="menu_config_afiliado")],
        [InlineKeyboardButton("🟢 Gerenciar WhatsApp", callback_data=CB_GERENCIAR_WHATS)],
        [InlineKeyboardButton("🤖 Configurar Monitor (Fase 3)", callback_data=CB_MONITOR_MENU)],
        [InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_MENU)],
    ]

    texto = (
        f"👋 Olá, <b>{user.first_name}</b>!\n\n"
        "Eu sou o <b>Bot de Achadinhos</b> 🛍️\n\n"
        "O que você deseja fazer?"
    )

    if update.message:
        await update.message.reply_text(
            texto,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    elif update.callback_query:
        await update.callback_query.answer()
        try:
            await update.callback_query.edit_message_text(
                texto,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception:
            # Se não conseguir editar (ex: mensagem velha), envia nova
            await update.callback_query.message.reply_text(
                texto,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

async def test_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from bot.utils.config import TELEGRAM_CHANNEL_ID
    from bot.utils.telegram_utils import normalize_chat_id
    from bot.permissions import is_admin
    
    if not is_admin(update.effective_user.id):
        return
        
    norm = normalize_chat_id(TELEGRAM_CHANNEL_ID)
    msg = (
        f"🛠️ <b>DEBUG CONFIG</b>\n\n"
        f"📌 ID Bruto: <code>{TELEGRAM_CHANNEL_ID}</code>\n"
        f"📌 ID Normalizado: <code>{norm}</code>\n\n"
        f"Tentando enviar mensagem de teste para o canal..."
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
    
    try:
        await context.bot.send_message(chat_id=norm, text="✅ Teste de conexão do Bot!")
        await update.message.reply_text("✅ Mensagem enviada com sucesso ao canal!")
    except Exception as e:
        await update.message.reply_text(f"❌ Erro ao enviar: <code>{e}</code>", parse_mode=ParseMode.HTML)
