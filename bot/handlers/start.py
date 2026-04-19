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


async def check_config_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Comando de diagnóstico para verificar IDs de afiliado (Apenas Admin)."""
    from bot.permissions import is_admin
    from bot.services.affiliate_link_service import _AFFILIATE_IDS

    if not is_admin(update.effective_user.id):
        return

    msg = ["🛠️ <b>DIAGNÓSTICO DE CONFIGURAÇÃO</b>\n"]
    
    # 1. Verificar IDs de Afiliado
    msg.append("<b>🔗 Afiliados:</b>")
    for store, aid in _AFFILIATE_IDS.items():
        if aid:
            # Mascarar por segurança (mostra só as pontas)
            masked = aid[:4] + "*" * (len(aid)-6) + aid[-2:] if len(aid) > 6 else aid
            msg.append(f"✅ {store.upper()}: <code>{masked}</code>")
        else:
            msg.append(f"❌ {store.upper()}: <i>Não configurado</i>")

    # 2. Outras Configurações
    import os
    from bot.utils.config import TELEGRAM_CHANNEL_ID
    
    msg.append("\n<b>📡 Sistema:</b>")
    msg.append(f"📌 Canal: <code>{TELEGRAM_CHANNEL_ID}</code>")
    msg.append(f"✂️ Encurtador: <code>{os.getenv('SHORTENER_BACKEND', 'tinyurl')}</code>")
    
    # 3. Verificação de Arquivo .env (no cloud ele costuma não existir)
    has_env = os.path.exists(".env")
    msg.append(f"📄 Arquivo .env existe: {'✅' if has_env else '❌ (Railway usa Variables tab)'}")

    await update.message.reply_text("\n".join(msg), parse_mode=ParseMode.HTML)


async def test_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Passo a passo da transformação de um link (Apenas Admin)."""
    from bot.permissions import is_admin
    from bot.services.affiliate_link_service import injetar_link_afiliado, _detectar_loja
    from bot.utils.url_resolver import resolve_url
    import asyncio

    if not is_admin(update.effective_user.id):
        return

    args = context.args
    if not args:
        await update.message.reply_text("❌ Uso: `/test_link [url]`", parse_mode=ParseMode.HTML)
        return

    original_url = args[0]
    msg_wait = await update.message.reply_text("⏳ <b>Analisando link...</b>", parse_mode=ParseMode.HTML)
    
    logs = [f"📥 <b>Original:</b> <code>{original_url}</code>"]
    
    # 1. Resolver encurtador básico
    resolved = await asyncio.to_thread(resolve_url, original_url)
    if resolved != original_url:
        logs.append(f"🔍 <b>Resolvido:</b> <code>{resolved[:100]}...</code>")
    
    # 2. Injetar (isso vai disparar o Playwright se for shortener e o injetar_link_afiliado for async)
    final_affiliate = await injetar_link_afiliado(resolved)
    
    store_key = _detectar_loja(final_affiliate)
    logs.append(f"🏪 <b>Loja Detectada:</b> <code>{store_key}</code>")
    
    # 3. Resultado
    logs.append(f"\n✅ <b>Link Final Gerado:</b>\n<code>{final_affiliate}</code>")
    
    # Verificar TAG (ajustado para detectar Netshoes/Rakuten e Shopee tbm)
    has_tag = any(x in final_affiliate.lower() for x in [
        "tag=", "matt_from=", "utm_source=", "af_id=", "id=", "subid="
    ])
    
    if has_tag:
        logs.append("\n🎯 <b>Status:</b> Tag de afiliado injetada com sucesso!")
    else:
        logs.append("\n⚠️ <b>Status:</b> Nenhuma tag detectada no link final.")

    await msg_wait.edit_text("\n".join(logs), parse_mode=ParseMode.HTML)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verifica a saúde do bot e a versão atual para detectar conflitos (Apenas Admin)."""
    from bot.permissions import is_admin
    from bot.utils.config import INSTANCE_ID, BOOT_TIME, TELEGRAM_CHANNEL_ID
    import os
    import sys
    
    if not is_admin(update.effective_user.id):
        return

    msg = (
        "📊 <b>STATUS DO SISTEMA</b>\n\n"
        f"🏷️ <b>Versão:</b> <code>V5 (Bypass Radware)</code>\n"
        f"🆔 <b>Instância ID:</b> <code>{INSTANCE_ID}</code>\n"
        f"🕒 <b>Ligado em:</b> <code>{BOOT_TIME}</code>\n"
        f"🐍 <b>Python:</b> <code>{sys.version.split()[0]}</code>\n"
        f"🖥️ <b>Plataforma:</b> <code>{sys.platform}</code>\n"
        f"📡 <b>Canal:</b> <code>{TELEGRAM_CHANNEL_ID}</code>\n"
        f"🛠️ <b>Modo:</b> <code>{'PRODUÇÃO' if os.getenv('RAILWAY_STATIC_URL') else 'DESENVOLVIMENTO'}</code>\n\n"
        "⚠️ <b>COMO DETECTAR CONFLITO:</b>\n"
        "Se você receber **DUAS** respostas com IDs diferentes, delete o deploy antigo no Railway!"
    )
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
