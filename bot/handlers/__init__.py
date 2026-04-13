from telegram.ext import (
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

from bot.handlers.start import start_command
from bot.handlers.cancel import cancel_command, cancel_menu_callback
from bot.handlers.offer import (
    start_offer_manual, receber_nome, receber_preco, receber_loja, receber_link, receber_imagem,
    pular_imagem, receber_descricao, pular_descricao, confirmar_envio,
    NOME, PRECO, LOJA, LINK, IMAGEM, DESCRICAO, CONFIRMAR
)
from bot.handlers.offer_by_link import (
    start_offer_by_link, receber_link_produto, preencher_nome_faltante, preencher_preco_faltante,
    receber_link_afiliado, pular_link_afiliado, confirmar_envio_link,
    btn_editar_oferta, escolher_campo_edicao, salvar_edicao,
    LINK_PRODUTO, PREENCHER_NOME_FALTANTE, PREENCHER_PRECO_FALTANTE, LINK_AFILIADO, CONFIRMAR_LINK,
    EDITAR_CAMPOS, CB_CONFIRMAR_LINK
)
from bot.handlers.review_queue import handle_review_callback
from bot.handlers.monitor import monitor_menu_handler, monitor_action_handler, voltar_menu_handler
from bot.utils.constants import (
    CB_PUBLICAR_MANUAL, CB_PUBLICAR_LINK, CB_CANCELAR_MENU, CB_CANCELAR_OFERTA,
    CB_CONFIRMAR, CB_REVIEW_APPROVE, CB_REVIEW_REJECT,
    CB_MONITOR_MENU, CB_MONITOR_START, CB_MONITOR_STOP, CB_VOLTAR_MENU, CB_GERENCIAR_CANAIS,
    CB_GERENCIAR_WHATS, CB_MENU_PRINCIPAL
)

from bot.handlers.channels import (
    menu_canais, btn_add_canal, btn_remover_canal, receber_novo_canal, AGUARDAR_NOVO_CANAL
)

from bot.handlers.whatsapp_admin import (
    menu_whatsapp, btn_add_whatsapp, btn_remover_whatsapp, receber_jid_whatsapp, AGUARDAR_JID_WHATS
)

from bot.handlers.affiliate_config import (
    start_config_afiliado, receber_selecao_loja, receber_credencial, cancelar_config,
    SELECIONAR_LOJA, DIGITAR_CREDENCIAL, CB_CANCELAR_CONFIG
)

def build_main_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("start", start_command),
            CallbackQueryHandler(start_command, pattern=f"^({CB_VOLTAR_MENU}|{CB_MENU_PRINCIPAL})$"),
            CallbackQueryHandler(start_offer_manual, pattern=f"^{CB_PUBLICAR_MANUAL}$"),
            CallbackQueryHandler(start_offer_by_link, pattern=f"^{CB_PUBLICAR_LINK}$"),
            CallbackQueryHandler(monitor_menu_handler, pattern=f"^{CB_MONITOR_MENU}$"),
            CallbackQueryHandler(monitor_action_handler, pattern=f"^monitor_(start|stop)$"),
            CallbackQueryHandler(menu_canais, pattern=f"^{CB_GERENCIAR_CANAIS}$"),
            CallbackQueryHandler(btn_add_canal, pattern=f"^add_chan$"),
            CallbackQueryHandler(btn_remover_canal, pattern=f"^remove_chan\\|"),
            CallbackQueryHandler(menu_whatsapp, pattern=f"^{CB_GERENCIAR_WHATS}$"),
            CallbackQueryHandler(btn_add_whatsapp, pattern=f"^add_wpp$"),
            CallbackQueryHandler(btn_remover_whatsapp, pattern=f"^del_wpp\\|"),
            CallbackQueryHandler(start_command, pattern=f"^({CB_VOLTAR_MENU}|{CB_MENU_PRINCIPAL})$"),
            CallbackQueryHandler(cancel_menu_callback, pattern=f"^{CB_CANCELAR_MENU}$"),
        ],
        states={
            # --- Canais ---
            AGUARDAR_NOVO_CANAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_canal)],
            AGUARDAR_JID_WHATS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_jid_whatsapp)],
            
            # --- Estados Manuais ---
            NOME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_nome)],
            PRECO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_preco)],
            LOJA: [CallbackQueryHandler(receber_loja, pattern=r"^loja_")],
            LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link)],
            IMAGEM: [
                MessageHandler(filters.PHOTO, receber_imagem),
                CommandHandler("pular", pular_imagem),
            ],
            DESCRICAO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_descricao),
                CommandHandler("pular", pular_descricao),
            ],
            CONFIRMAR: [
                CallbackQueryHandler(confirmar_envio, pattern=f"^{CB_CONFIRMAR}$"),
                CallbackQueryHandler(confirmar_envio, pattern=f"^{CB_CANCELAR_OFERTA}$"),
                CallbackQueryHandler(start_command, pattern=f"^({CB_VOLTAR_MENU}|{CB_MENU_PRINCIPAL})$"),
            ],
            
            # --- Estados por Link ---
            LINK_PRODUTO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link_produto)],
            PREENCHER_NOME_FALTANTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, preencher_nome_faltante)],
            PREENCHER_PRECO_FALTANTE: [MessageHandler(filters.TEXT & ~filters.COMMAND, preencher_preco_faltante)],
            LINK_AFILIADO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link_afiliado),
                CommandHandler("pular", pular_link_afiliado),
            ],
            CONFIRMAR_LINK: [
                CallbackQueryHandler(confirmar_envio_link, pattern=f"^{CB_CONFIRMAR_LINK}$"),
                CallbackQueryHandler(confirmar_envio_link, pattern=f"^{CB_CANCELAR_OFERTA}$"),
                CallbackQueryHandler(btn_editar_oferta, pattern=f"^editar_oferta$"),
                CallbackQueryHandler(start_command, pattern=f"^({CB_VOLTAR_MENU}|{CB_MENU_PRINCIPAL})$"),
            ],
            EDITAR_CAMPOS: [
                CallbackQueryHandler(escolher_campo_edicao, pattern=f"^(edit_|cancel_edit)"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, salvar_edicao),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("start", start_command),
        ],
        allow_reentry=True,
    )


def build_review_queue_handler() -> CallbackQueryHandler:
    """Handler separado para callbacks da fila de aprovação — fora do ConversationHandler."""
    return CallbackQueryHandler(
        handle_review_callback,
        pattern=r"^(review_aprovar|review_rejeitar):"
    )
