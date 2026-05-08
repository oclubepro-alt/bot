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
    from bot.utils.config import INSTANCE_ID
    logger.info("=" * 60)
    logger.info(f" 🛒 BOT DE ACHADINHOS — #{INSTANCE_ID}")
    logger.info(" 🚀 VERSÃO: V5 — BYPASS RADWARE CARREGADO")
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
    from bot.handlers.start import (
        start_command, test_id_command, status_command, check_config_command, test_link_command
    )
    from bot.handlers.cancel import cancel_command
    from bot.handlers.offer_by_link import cmd_debug_link
    from bot.handlers.review_queue import start_review_queue
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("test_config", test_id_command))
    app.add_handler(CommandHandler("check_config", check_config_command))
    app.add_handler(CommandHandler("test_link", test_link_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("debug_link", cmd_debug_link))
    app.add_handler(CommandHandler("revisar", start_review_queue))
    app.add_handler(CallbackQueryHandler(start_review_queue, pattern=r"^menu_revisar$"))

    # Handler de conversão principal (Fases 1 e 2)
    app.add_handler(build_main_handler())

    # Handlers isolados para modo Encaminhamento
    from bot.handlers.forward_publisher import (
        start_forward_mode, receive_forwarded_message, cancel_forward_mode, process_all_forwardings,
        encam_revisar_uma, encam_aprovar_todas, frev_aprovar, frev_descartar, frev_proxima, frev_corrigir, 
        receive_correction, CB_PROCESSAR_TUDO, CB_CANCELAR_ENCAM
    )
    from bot.utils.constants import CB_PUBLICAR_ENCAMINHAMENTO

    app.add_handler(CallbackQueryHandler(start_forward_mode, pattern=f"^{CB_PUBLICAR_ENCAMINHAMENTO}$"))
    app.add_handler(CallbackQueryHandler(process_all_forwardings, pattern=f"^{CB_PROCESSAR_TUDO}$"))
    app.add_handler(CallbackQueryHandler(cancel_forward_mode, pattern=f"^{CB_CANCELAR_ENCAM}$"))
    app.add_handler(CallbackQueryHandler(encam_revisar_uma, pattern=r"^encam_revisar$"))
    app.add_handler(CallbackQueryHandler(encam_aprovar_todas, pattern=r"^encam_aprovar_todas$"))
    app.add_handler(CallbackQueryHandler(frev_aprovar, pattern=r"^frev_aprovar$"))
    app.add_handler(CallbackQueryHandler(frev_descartar, pattern=r"^frev_descartar$"))
    app.add_handler(CallbackQueryHandler(frev_proxima, pattern=r"^frev_proxima$"))
    app.add_handler(CallbackQueryHandler(frev_corrigir, pattern=r"^frev_corrigir$"))
    
    app.add_handler(MessageHandler(
        filters.FORWARDED & (
            filters.PHOTO |
            filters.TEXT |
            filters.Document.IMAGE |
            filters.VIDEO |
            filters.ANIMATION
        ),
        receive_forwarded_message
    ), group=1)
    app.add_handler(MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, receive_correction), group=2)

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
        per_message=False, # CORRIGIDO: Per-user tracking para evitar perda de estado
    )

    async def global_error_handler(update, context):
        from telegram.error import Conflict, NetworkError
        if isinstance(context.error, Conflict):
            logger.error("[CONFLITO] ❌ Instância duplicada detectada! Verifique se seu bot local está desligado.")
        elif isinstance(context.error, NetworkError):
            logger.warning(f"[REDE] Erro de rede: {context.error}")
        else:
            logger.error(f"[ERRO GERAL] Exceção não tratada: {context.error}", exc_info=context.error)

    app.add_error_handler(global_error_handler)
    app.add_handler(config_handler)

    # Iniciar o scheduler para o monitor automático rodar em background
    setup_scheduler(app)

    logger.info("[APP] Handlers e scheduler registrados. Iniciando polling...")
    
    # ── ESTABILIDADE E CONFLITOS ──────────────────────────────────────────
    # Railway pode levar alguns segundos para encerrar instâncias antigas.
    # Aumentamos o delay para 10s e adicionamos tratamento de sinais para Railway.
    import time
    import signal
    
    logger.info("[ESTABILIDADE] Aguardando 10 segundos para garantir limpeza de conexões antigas...")
    time.sleep(10)
    
    def handle_signal(sig, frame):
        logger.info(f"[SINAL] Recebido sinal {sig}. Encerrando bot...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    
    app.run_polling(drop_pending_updates=True)



if __name__ == "__main__":
    main()
