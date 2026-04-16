"""
scheduler_service.py - Scheduler da Fase 3.

Usa o JobQueue nativo do python-telegram-bot (APScheduler embutido)
para varrer as fontes periodicamente e enviar prévias de aprovação
para todos os admins cadastrados.
"""
import logging
import uuid

from telegram.ext import Application
from telegram.constants import ParseMode
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils.config import ADMIN_IDS, MONITOR_INTERVAL_MINUTES, AUTO_APPROVE
from bot.services.source_monitor import scan_sources
from bot.services.product_extractor import extract_product_data
from bot.services.ai_writer import generate_caption
from bot.services.affiliate_links import get_final_link
from bot.services.dedup_store import is_seen, mark_seen
from bot.services.affiliate_links import resolve_final_url
from bot.utils.formatter import build_offer_message, build_preview_message, escape_html

logger = logging.getLogger(__name__)

async def _run_scan(context) -> None:
    """
    Job executado pelo scheduler: varre fontes, extrai dados,
    gera copy e envia prévias aos admins para aprovação.
    """
    logger.info("[SCHEDULER] Iniciando varredura das fontes...")
    
    if not ADMIN_IDS:
        logger.warning("[SCHEDULER] ADMIN_IDS vazio — ninguém receberá prévias.")
        return

    new_items = scan_sources()

    if not new_items:
        logger.info("[SCHEDULER] Nenhum item novo encontrado nesta rodada.")
        return

    # Limita a exatamente 5 itens por rodada para evitar excesso (Requisito do Usuário)
    new_items = new_items[:5]
    logger.info(f"[SCHEDULER] Processando top {len(new_items)} item(ns) novo(s).")

    for item in new_items:
        product_url: str = item["url"]
        source_name: str = item.get("source_name", "—")

        # Dupla checagem de dedup antes de extrair
        if is_seen(product_url):
            logger.debug(f"[SCHEDULER] Ignorado (visto): {product_url[:80]}")
            continue

        logger.info(f"[SCHEDULER] Extraindo dados de: {product_url[:60]}")
        # Resolve redirects — URL final usada para extração, original mantida para publicação
        resolved_url = resolve_final_url(product_url)
        dados = extract_product_data(resolved_url)

        # Se não tiver nem nome, pula (dados insuficientes)
        if not dados.get("nome"):
            logger.warning(f"[SCHEDULER] Dados insuficientes para {product_url[:80]}, pulando.")
            mark_seen(product_url)  # Marca para não tentar de novo
            continue

        nome = dados["nome"]
        preco = dados.get("preco") or "Preço não informado"
        loja = dados.get("loja") or "Desconhecida"
        imagem = dados.get("imagem")

        # Gera copy com IA
        logger.info(f"[SCHEDULER] Gerando copy para: '{nome[:40]}'")
        copy_ia = await generate_caption(
            nome=nome, preco=preco, loja=loja, descricao=dados.get("descricao")
        )

        # Link final: sem afiliado automático na Fase 3, usa o original
        final_link = get_final_link(product_url)

        mensagem = build_offer_message(
            nome=nome, preco=preco, loja=loja, link=final_link, legenda_ia=copy_ia
        )

        # Modo AUTO_APPROVE: publica direto (Fase 4 preparada)
        if AUTO_APPROVE:
            logger.info(f"[SCHEDULER] AUTO_APPROVE ativo — publicando direto: '{nome[:40]}'")
            from bot.services.publisher_router import publish_offer
            try:
                await publish_offer(context.bot, mensagem, imagem)
                mark_seen(product_url)
            except Exception as e:
                logger.error(f"[SCHEDULER] Erro ao publicar automaticamente: {e}")
            continue

        # Modo manual: envia prévia para cada admin e armazena na fila
        offer_id = uuid.uuid4().hex[:12]

        if "pending_offers" not in context.bot_data:
            context.bot_data["pending_offers"] = {}

        context.bot_data["pending_offers"][offer_id] = {
            "product_url": product_url,
            "mensagem": mensagem,
            "imagem": imagem,
            "nome": nome,
            "source_name": source_name,
        }

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Aprovar e Publicar",
                    callback_data=f"review_aprovar:{offer_id}"
                ),
                InlineKeyboardButton(
                    "❌ Rejeitar",
                    callback_data=f"review_rejeitar:{offer_id}"
                ),
            ]
        ])

        preview_text = (
            f"🔍 <b>Nova oferta encontrada automaticamente!</b>\n"
            f"📌 Fonte: <i>{escape_html(source_name)}</i>\n\n"
            + build_preview_message(mensagem)
        )

        for admin_id in ADMIN_IDS:
            try:
                if imagem:
                    await context.bot.send_photo(
                        chat_id=admin_id,
                        photo=imagem,
                        caption=preview_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                else:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=preview_text,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                        disable_web_page_preview=True,
                    )
                logger.info(
                    f"[SCHEDULER] Prévia enviada ao admin {admin_id} — oferta: '{nome[:40]}'"
                )
            except Exception as e:
                logger.error(f"[SCHEDULER] Erro ao notificar admin {admin_id}: {e}")


def is_monitor_active(app: Application) -> bool:
    """Verifica se o job de monitoramento está rodando."""
    jobs = app.job_queue.get_jobs_by_name("source_scan")
    return len(jobs) > 0


def stop_monitor(app: Application) -> bool:
    """Para o monitoramento se estiver rodando."""
    jobs = app.job_queue.get_jobs_by_name("source_scan")
    if not jobs:
        return False
    for job in jobs:
        job.schedule_removal()
    logger.info("[SCHEDULER] Monitoramento parado via comando.")
    return True


def start_monitor(app: Application) -> bool:
    """Inicia o monitoramento se não estiver rodando."""
    if is_monitor_active(app):
        return False
        
    interval_seconds = MONITOR_INTERVAL_MINUTES * 60
    app.job_queue.run_repeating(
        _run_scan,
        interval=interval_seconds,
        first=10,  # Começa em 10s para resposta rápida
        name="source_scan",
    )
    logger.info(f"[SCHEDULER] Monitoramento iniciado — intervalo: {MONITOR_INTERVAL_MINUTES} min.")
    return True


def setup_scheduler(app: Application) -> None:
    """
    Setup inicial. Agora NÃO inicia automaticamente.
    Apenas garante que as variáveis estão prontas.
    """
    logger.info("[SCHEDULER] Sistema pronto para ser ativado via menu.")
