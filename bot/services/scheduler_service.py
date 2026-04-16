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

import asyncio
from bot.services.affiliate_injector import get_affiliate_url
from bot.services.link_shortener import shorten_for_publication
from bot.services.publisher_router import publish_offer

async def _run_scan(context, limit: int = 10, manual: bool = False) -> int:
    """
    Job executado pelo scheduler ou manualmente via botão: varre fontes, extrai dados,
    gera copy e publica ou envia prévias.
    Retorna o total de itens publicados/enviados.
    """
    logger.info(f"[SCHEDULER] Iniciando varredura das fontes (limite: {limit})...")
    
    if not ADMIN_IDS:
        logger.warning("[SCHEDULER] ADMIN_IDS vazio — ninguém receberá prévias.")
        if not manual: return 0

    new_items = scan_sources()

    if not new_items:
        logger.info("[SCHEDULER] Nenhum item novo encontrado nesta rodada.")
        return 0

    # Limita rigorosamente ao pedido (10 itens)
    items_to_process = new_items[:limit]
    logger.info(f"[SCHEDULER] Processando {len(items_to_process)} novos itens.")

    count = 0
    for item in items_to_process:
        product_url: str = item["url"]
        source_name: str = item.get("source_name", "—")

        if is_seen(product_url):
            continue

        try:
            logger.info(f"[SCHEDULER] [{count+1}/{len(items_to_process)}] Extraindo: {product_url[:60]}")
            
            # Resolve URL e extrai dados
            resolved_url = resolve_final_url(product_url)
            dados = extract_product_data(resolved_url)

            if not dados.get("nome"):
                mark_seen(product_url)
                continue

            # 1. Injeção de Afiliado e Encurtamento (RESOLVE PROBLEMA 2 NO SCRAPER)
            store_key = dados.get("store_key", "other")
            affiliate_url = get_affiliate_url(
                original_url=product_url,
                resolved_url=resolved_url,
                store_key=store_key
            )
            final_link = shorten_for_publication(affiliate_url)

            # 2. Geração de Copy
            copy_ia = await generate_caption(
                nome=dados["nome"], 
                preco=dados.get("preco", "Consulte"), 
                loja=dados.get("loja", "Loja"), 
                descricao=dados.get("descricao")
            )

            mensagem = build_offer_message(
                nome=dados["nome"], 
                preco=dados.get("preco", "Consulte"), 
                loja=dados.get("loja", "Loja"), 
                link=final_link, 
                legenda_ia=copy_ia
            )

            # 3. DESTINO: Se manual ou AUTO_APPROVE, vai direto pro canal (RESOLVE PROBLEMA 3)
            if manual or AUTO_APPROVE:
                logger.info(f"[SCHEDULER] Publicando direto no canal: '{dados['nome'][:40]}'")
                # Formata para o router (Telegram/WhatsApp)
                copies = {"telegram": mensagem, "whatsapp": mensagem}
                await publish_offer(context.bot, copies, dados.get("imagem"))
                mark_seen(product_url)
                count += 1
                
                # SLEEP PARA EVITAR RATE LIMIT (Requisito Problema 3)
                if count < len(items_to_process):
                    await asyncio.sleep(3) 
                continue

            # Modo de Aprovação Manual (Padrão do Scheduler)
            offer_id = uuid.uuid4().hex[:12]
            if "pending_offers" not in context.bot_data:
                context.bot_data["pending_offers"] = {}

            context.bot_data["pending_offers"][offer_id] = {
                "product_url": product_url,
                "mensagem": mensagem,
                "imagem": dados.get("imagem"),
                "nome": dados["nome"],
            }

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Aprovar", callback_data=f"review_aprovar:{offer_id}"),
                 InlineKeyboardButton("❌ Rejeitar", callback_data=f"review_rejeitar:{offer_id}")]
            ])

            preview_text = f"🔍 <b>Oferta Automática ({source_name})</b>\n\n" + build_preview_message(mensagem)

            for admin_id in ADMIN_IDS:
                try:
                    if dados.get("imagem"):
                        await context.bot.send_photo(chat_id=admin_id, photo=dados["imagem"], caption=preview_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                    else:
                        await context.bot.send_message(chat_id=admin_id, text=preview_text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
                except Exception: pass
            
            count += 1
            await asyncio.sleep(1) # Delay menor para prévias aos admins

        except Exception as e:
            logger.error(f"[SCHEDULER] Falha ao processar item {product_url}: {e}")

    return count


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
