"""
affiliate_config.py - Configurar credenciais de afiliado via comando
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from bot.permissions import is_admin
from bot.utils.affiliate_store import get_affiliate, set_affiliate
from bot.utils.constants import CB_MENU_PRINCIPAL
from bot.handlers.start import start_command

logger = logging.getLogger(__name__)

SELECIONAR_LOJA, DIGITAR_CREDENCIAL = range(20, 22)

CB_CANCELAR_CONFIG = "cancelar_config_afiliado"


async def start_config_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if not is_admin(user.id):
        if update.message:
            await update.message.reply_text("⛔ Apenas administradores podem configurar afiliados.")
        elif update.callback_query:
            await update.callback_query.message.reply_text("⛔ Apenas administradores.")
        return ConversationHandler.END

    texto = (
        "⚙️ *Configuração Automática de Afiliado*\n\n"
        "Escolha a loja que deseja configurar a sua credencial ou link-base:\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("Amazon (Tag)", callback_data="config_afiliado_amazon")],
        [InlineKeyboardButton("Magalu (Link Afiliado)", callback_data="config_afiliado_magalu")],
        [InlineKeyboardButton("Netshoes (Link Afiliado)", callback_data="config_afiliado_netshoes")],
        [InlineKeyboardButton("Mercado Livre (Link Afiliado)", callback_data="config_afiliado_mercadolivre")],
        [InlineKeyboardButton("Outra (Base link)", callback_data="config_afiliado_other")],
        [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)]
    ]

    if update.message:
        await update.message.reply_text(
            texto, 
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            texto,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    return SELECIONAR_LOJA


async def receber_selecao_loja(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == CB_MENU_PRINCIPAL:
        await start_command(update, context)
        return ConversationHandler.END

    # Extrai o "store_key" do callback. Ex: config_afiliado_amazon -> amazon
    store_key = query.data.replace("config_afiliado_", "")
    context.user_data["config_store_key"] = store_key

    current_data = get_affiliate(store_key)
    
    if store_key == "amazon":
        current_val = current_data.get("tag", "Nenhuma")
        prompt = (
            f"🛒 *Loja Selecionada:* Amazon\n"
            f"🏷️ *Tag atual:* `{current_val}`\n\n"
            "Envie a sua Tag da Amazon (ex: *seutag-20*):\n"
            "_(Ou digite /cancelar)_"
        )
    else:
        current_val = current_data.get("affiliate_url", "Nenhum")
        prompt = (
            f"🛒 *Loja Selecionada:* {store_key.capitalize()}\n"
            f"🔗 *Link Afiliado Base atual:* `{current_val}`\n\n"
            "Envie o seu link base de afiliado para esta loja:\n"
            "_(Ou digite /cancelar)_"
        )

    await query.edit_message_text(prompt, parse_mode=ParseMode.MARKDOWN)
    return DIGITAR_CREDENCIAL


async def receber_credencial(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    valor = update.message.text.strip()
    store_key = context.user_data.get("config_store_key")

    if store_key == "amazon":
        set_affiliate(store_key, {"tag": valor})
        await update.message.reply_text(f"✅ Tag Amazon salva: `{valor}`", parse_mode=ParseMode.MARKDOWN)
    else:
        set_affiliate(store_key, {"affiliate_url": valor})
        await update.message.reply_text(f"✅ Link de Afiliado para {store_key.capitalize()} salvo:\n`{valor}`", parse_mode=ParseMode.MARKDOWN)
        
    context.user_data.clear()
    await update.message.reply_text("✨ Salvo com sucesso!")
    await start_command(update, context)
    return ConversationHandler.END


async def cancelar_config(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Configuração de afiliado cancelada.")
    context.user_data.clear()
    return ConversationHandler.END
