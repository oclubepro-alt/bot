from telegram.ext import (
    ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
)

from bot.handlers.start import start_command, check_config_command, test_link_command
from bot.handlers.cancel import cancel_command, cancel_menu_callback
from bot.handlers.offer import (
    start_offer_manual, receber_nome, receber_preco, receber_loja, receber_link, receber_imagem,
    pular_imagem, receber_descricao, pular_descricao, confirmar_envio,
    NOME, PRECO, LOJA, LINK, IMAGEM, DESCRICAO, CONFIRMAR
)
from bot.handlers.offer_by_link import (
    # Handlers de entrada e fluxo base
    start_offer_by_link,
    receber_link_produto,
    preencher_nome_faltante,
    preencher_preco_faltante,
    receber_link_afiliado,
    pular_link_afiliado,
    confirmar_envio_link,
    # Cupom (NOVO)
    receber_cupom,
    btn_sem_cupom,
    # Prévia e edição
    btn_editar_oferta,
    escolher_campo_edicao,
    salvar_edicao,
    salvar_edicao_texto,
    voltar_previa_handler,
    regen_ia_callback,
    # Estados
    LINK_PRODUTO,
    PREENCHER_NOME_FALTANTE,
    PREENCHER_PRECO_FALTANTE,
    LINK_AFILIADO,
    CONFIRMAR_LINK,
    EDITAR_CAMPOS,
    AGUARDAR_CUPOM,           # NOVO
    AGUARDAR_EDICAO_TEXTO,    # NOVO
    # Callbacks
    CB_CONFIRMAR_LINK,
    CB_CANCELAR_OFERTA_LINK,
    CB_SEM_CUPOM,             # NOVO
    CB_EDIT_PRECO,            # NOVO
    CB_EDIT_COPY,             # NOVO
    CB_EDIT_LINK,             # NOVO
    CB_EDIT_CUPOM,            # NOVO
    CB_VOLTAR_PREVIA,         # NOVO
)
from bot.handlers.review_queue import handle_review_callback, handle_review_bulk_callback
from bot.handlers.monitor import monitor_menu_handler, monitor_action_handler, voltar_menu_handler
from bot.utils.constants import (
    CB_PUBLICAR_MANUAL, CB_PUBLICAR_LINK, CB_CANCELAR_MENU,
    CB_CONFIRMAR, CB_REVIEW_APPROVE, CB_REVIEW_REJECT,
    CB_MONITOR_MENU, CB_MONITOR_START, CB_MONITOR_STOP, CB_VOLTAR_MENU, CB_GERENCIAR_CANAIS,
    CB_GERENCIAR_WHATS, CB_MENU_PRINCIPAL
)
from bot.utils.constants import CB_CANCELAR_OFERTA as CB_CANCELAR_OFERTA_MANUAL

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
            CommandHandler("check_config", check_config_command),
            CommandHandler("test_link", test_link_command),
            CallbackQueryHandler(start_command, pattern=f"^({CB_VOLTAR_MENU}|{CB_MENU_PRINCIPAL})$"),
            CallbackQueryHandler(start_offer_manual,   pattern=f"^{CB_PUBLICAR_MANUAL}$"),
            CallbackQueryHandler(start_offer_by_link,  pattern=f"^{CB_PUBLICAR_LINK}$"),
            CallbackQueryHandler(monitor_menu_handler,  pattern=f"^{CB_MONITOR_MENU}$"),
            CallbackQueryHandler(monitor_action_handler, pattern=r"^monitor_(start|stop|scrape_now)$"),
            CallbackQueryHandler(menu_canais,           pattern=f"^{CB_GERENCIAR_CANAIS}$"),
            CallbackQueryHandler(btn_add_canal,         pattern=r"^add_chan$"),
            CallbackQueryHandler(btn_remover_canal,     pattern=r"^remove_chan\|"),
            CallbackQueryHandler(menu_whatsapp,         pattern=f"^{CB_GERENCIAR_WHATS}$"),
            CallbackQueryHandler(btn_add_whatsapp,      pattern=r"^add_wpp$"),
            CallbackQueryHandler(btn_remover_whatsapp,  pattern=r"^del_wpp\|"),
            CallbackQueryHandler(cancel_menu_callback,  pattern=f"^{CB_CANCELAR_MENU}$"),
        ],
        states={
            # ── Canais e WhatsApp ─────────────────────────────────────────────
            AGUARDAR_NOVO_CANAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_novo_canal),
            ],
            AGUARDAR_JID_WHATS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_jid_whatsapp),
            ],

            # ── Fluxo Manual (offer.py) ───────────────────────────────────────
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
                CallbackQueryHandler(confirmar_envio, pattern=f"^{CB_CANCELAR_OFERTA_MANUAL}$"),
                CallbackQueryHandler(start_command,   pattern=f"^({CB_VOLTAR_MENU}|{CB_MENU_PRINCIPAL})$"),
            ],

            # ── Fluxo por Link (offer_by_link.py) ────────────────────────────

            # Estado 1: recebe o link do produto
            LINK_PRODUTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link_produto),
            ],

            # Estado 2/3: preenche nome ou preço quando extração falhou
            PREENCHER_NOME_FALTANTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, preencher_nome_faltante),
            ],
            PREENCHER_PRECO_FALTANTE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, preencher_preco_faltante),
            ],

            # Estado NOVO: pergunta e recebe cupom de desconto
            AGUARDAR_CUPOM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_cupom),
                CallbackQueryHandler(btn_sem_cupom, pattern=f"^{CB_SEM_CUPOM}$"),
            ],

            # Fallback: link afiliado manual (mantido por compatibilidade)
            LINK_AFILIADO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receber_link_afiliado),
                CommandHandler("pular", pular_link_afiliado),
            ],

            # Estado 4: prévia exibida — aguarda Confirmar / Corrigir / Cancelar
            CONFIRMAR_LINK: [
                CallbackQueryHandler(confirmar_envio_link, pattern=f"^{CB_CONFIRMAR_LINK}$"),
                CallbackQueryHandler(confirmar_envio_link, pattern=f"^{CB_CANCELAR_OFERTA_LINK}$"),
                CallbackQueryHandler(btn_editar_oferta,    pattern=r"^editar_oferta$"),
                CallbackQueryHandler(regen_ia_callback,    pattern=r"^regen_ia$"),
                CallbackQueryHandler(start_command,        pattern=f"^({CB_VOLTAR_MENU}|{CB_MENU_PRINCIPAL})$"),
            ],

            # Estado 5: submenu de edição — mostra botões Preço/Copy/Link/Cupom/Voltar
            EDITAR_CAMPOS: [
                CallbackQueryHandler(
                    escolher_campo_edicao,
                    pattern=f"^({CB_EDIT_PRECO}|{CB_EDIT_COPY}|{CB_EDIT_LINK}|{CB_EDIT_CUPOM})$",
                ),
                CallbackQueryHandler(voltar_previa_handler, pattern=f"^{CB_VOLTAR_PREVIA}$"),
            ],

            # Estado NOVO: recebe o texto do campo a ser corrigido
            AGUARDAR_EDICAO_TEXTO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, salvar_edicao_texto),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_command),
            CommandHandler("start", start_command),
        ],
        allow_reentry=True,
    )


def build_review_queue_handler() -> CallbackQueryHandler:
    """Handler único para callbacks da fila de aprovação."""
    return CallbackQueryHandler(
        handle_review_callback,
        pattern=r"^review_(aprovar|rejeitar|bulk):"
    )
