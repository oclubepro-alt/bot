import logging
from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler
from bot.utils.config import ADMIN_IDS

logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return True
    return user_id in ADMIN_IDS

def admin_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not is_admin(user.id):
            logger.warning(
                f"[ACESSO NEGADO] Usuário {user.id} ({user.username}) "
                "tentou usar comando de admin."
            )
            await update.message.reply_text(
                "⛔ Você não tem permissão para usar este bot."
            )
            return ConversationHandler.END
        return await func(update, context)
    return wrapper
