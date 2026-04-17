"""
app.py - Ponto de entrada do Bot de Achadinhos
Configura logging, registra handlers e inicia o polling.
"""
import logging
import sys

from telegram.ext import ApplicationBuilder, CommandHandler, ConversationHandler, CallbackQueryHandler, MessageHandler, filters

from bot.utils.config import TELEGRAM_BOT_TOKEN, HTTP_PROXY
from bot.utils.constants import CB_MENU_PRINCIPAL
from bot.handlers import build_main_handler, build_review_queue_handler
from bot.services.scheduler_service import setup_scheduler

# Garante saída no Windows com utf-8
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
# Silencia logs verbosos de bibliotecas externas
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("=" * 60)
    logger.info(" 🛒 BOT DE ACHADINHOS — Iniciando (Fase 3)...")
    logger.info("=" * 60)

    if not TELEGRAM_BOT_TOKEN:
        logger.error("[ERRO] TELEGRAM_BOT_TOKEN não encontrado!")
        sys.exit(1)

    app_builder = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN)
    
    if HTTP_PROXY:
        try:
            logger.info(f"[PROXY] Configurando proxy: {HTTP_PROXY}")
            # Cortesia para evitar erros de conexão se o proxy for inválido
            app_builder.proxy(HTTP_PROXY).get_updates_proxy(HTTP_PROXY)
        except Exception as e:
            logger.error(f"[PROXY] Erro ao configurar proxy: {e}")
    else:
        logger.info("[PROXY] Nenhum proxy configurado. Usando conexão direta.")
        
    app = app_builder.build()

    logger.info("Bot construído com sucesso. Registrando handlers...")

    # Handlers básicos explícitos para garantir resposta (Requisito de Estabilidade)
    from bot.handlers.start import start_command
    from bot.handlers.cancel import cancel_command
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("cancel", cancel_command))

    # Handler de conversão principal (Fases 1 e 2)
    app.add_handler(build_main_handler())

    # Handler de aprovação manual das ofertas automáticas (Fase 3)
    # Registrado FORA do ConversationHandler para funcionar a qualquer momento
    app.add_handler(build_review_queue_handler())

    # Handler do fluxo de configuração de afiliados
    from bot.handlers.affiliate_config import (
        start_config_afiliado, receber_selecao_loja, receber_credencial, cancelar_config,
        SELECIONAR_LOJA, DIGITAR_CREDENCIAL, CB_CANCELAR_CONFIG
    )

    config_handler = ConversationHandler(
        entry_points=[
            CommandHandler("config_afiliado", start_config_afiliado),
            CallbackQueryHandler(start_config_afiliado, pattern=rf"^menu_config_afiliado$")
        ],
        states={
            SELECIONAR_LOJA: [CallbackQueryHandler(receber_selecao_loja, pattern=rf"^(config_afiliado_|{CB_CANCELAR_CONFIG}|{CB_MENU_PRINCIPAL})")],
            DIGITAR_CREDENCIAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_credencial),
                CommandHandler("cancelar", cancelar_config)
            ],
        },
        fallbacks=[CommandHandler("cancelar", cancelar_config)],
    )
    app.add_handler(config_handler)

    # Registra o scheduler de varredura automática (Fase 3) - PAUSADO TEMPORARIAMENTE
    # setup_scheduler(app)

    # AUTO-START: Inicia monitoramento na inicialização - PAUSADO TEMPORARIAMENTE
    # from bot.services.scheduler_service import start_monitor
    # start_monitor(app)

    logger.info("[APP] Handlers e scheduler registrados. Bot em execução... (Ctrl+C para parar)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
