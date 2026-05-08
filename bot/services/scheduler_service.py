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
from bot.services.product_extractor_v2 import extract_product_data_v2
from bot.services.ai_writer import generate_caption
from bot.services.affiliate_link_service import injetar_link_afiliado
from bot.services.dedup_store import is_seen, mark_seen
from bot.services.affiliate_links import resolve_final_url
from bot.utils.formatter import escape_html

logger = logging.getLogger(__name__)

import asyncio
from bot.services.affiliate_injector import get_affiliate_url
from bot.services.link_shortener import shorten_for_publication
from bot.services.publisher_router import publish_offer

async def _run_scan(context, limit: int = 10, manual: bool = False, trigger_user_id: int = None) -> int:
    """
    Job executado pelo scheduler ou manualmente via botão: varre fontes, extrai dados,
    gera copy e publica ou envia prévias.
    Retorna o total de itens processados com sucesso.
    """
    logger.info(f"[SCHEDULER] Iniciando varredura das fontes (limite pedido: {limit})...")
    if AUTO_APPROVE:
        logger.warning("[SCHEDULER] ⚠️  MODO AUTO-APPROVE: ofertas irão DIRETO ao canal sem revisão!")
    else:
        logger.info("[SCHEDULER] ✅ MODO REVISÃO: ofertas aguardarão aprovação do admin.")
    
    # Feedback inicial para o usuário no modo manual
    if trigger_user_id:
        try:
            await context.bot.send_message(
                chat_id=trigger_user_id,
                text="🔎 <b>Iniciando varredura (V6.5 Sniper)...</b>\nIsso pode levar alguns instantes dependendo da resposta das fontes.",
                parse_mode=ParseMode.HTML
            )
        except Exception: pass

    if not ADMIN_IDS and not manual:
        logger.warning("[SCHEDULER] ADMIN_IDS vazio — ninguém receberá prévias.")
        return 0

    try:
        # A varredura agora é assíncrona e usa pipeline robusto para Amazon
        all_found_items = await scan_sources()
    except Exception as e:
        logger.error(f"[SCHEDULER] Erro ao escanear fontes: {e}")
        if trigger_user_id:
            await context.bot.send_message(chat_id=trigger_user_id, text=f"❌ Erro ao escanear fontes: {e}")
        return 0

    if not all_found_items:
        logger.info("[SCHEDULER] Nenhum item novo encontrado nesta rodada.")
        if trigger_user_id:
            await context.bot.send_message(chat_id=trigger_user_id, text="ℹ️ Nenhuma oferta nova encontrada nas fontes cadastradas.")
        return 0

    logger.info(f"[SCHEDULER] {len(all_found_items)} novos itens encontrados. Aplicando limite de {limit} e processando.")

    count = 0
    for item in all_found_items:
        if count >= limit:
            logger.info(f"[SCHEDULER] Limite de {limit} itens atingido. Parando loop.")
            break

        product_url: str = item["url"]
        source_name: str = item.get("source_name", "—")

        if is_seen(product_url):
            continue

        try:
            logger.info(f"--- [PROCESSO {count+1}/{limit}] ---")
            logger.info(f"[SCHEDULER] Extraindo: {product_url[:60]}")
            
            # 1. Extração Mestra V2 (Já é async)
            dados = await extract_product_data_v2(product_url)

            titulo_extraido = dados.get("titulo", "")
            if not titulo_extraido or titulo_extraido in ["Produto", "Produto Disponível"]:
                logger.warning(f"[SCHEDULER] Falha ao extrair título para {product_url}. Pulando.")
                continue
            
            # Padronização de nomes para o resto do pipeline
            dados["title"] = dados.get("titulo")
            dados["image_url"] = dados.get("imagem")
            dados["loja"] = dados.get("store", "Loja")

            # 2. Injeção de Afiliado (NUNCA encurtar aqui — link longo preserva tag)
            store_key = dados.get("store_key", "other")
            affiliate_url = await injetar_link_afiliado(
                url=dados.get("final_url", product_url),
                store_key=store_key
            )
            # IMPORTANTE: encurtamento ocorre SOMENTE na publicação final
            # Aqui guardamos o link longo para garantir rastreabilidade da tag
            logger.info(f"[SCHEDULER] Link afiliado gerado (longo): {affiliate_url[:80]}")

            # 3. Geração de Copy IA (Já é async)
            copy_ia = await generate_caption(
                nome=dados["title"], 
                preco=dados.get("preco", "Preço não disponível"), 
                loja=dados.get("loja", "Loja"), 
                descricao=dados.get("descricao")
            )

            # 4. Publicação ou Fila de Revisão
            # AUTO_APPROVE=true → publica direto (encurta aqui)
            # AUTO_APPROVE=false → manda para o admin aprovar (NÃO encurta ainda)
            if AUTO_APPROVE:
                logger.info(f"[SCHEDULER] AUTO_APPROVE ativo — publicando direto: '{dados['title'][:40]}'")
                
                # Encurta APENAS aqui, na publicação direta
                final_link = await asyncio.to_thread(shorten_for_publication, affiliate_url)
                
                from bot.services.copy_builder import build_copy
                copies = build_copy(
                    nome=dados["title"],
                    preco=dados.get("preco", "Preço não disponível"),
                    loja=dados.get("loja", "Loja"),
                    store_key=store_key,
                    short_url=final_link,
                    legenda_ia=copy_ia,
                    preco_original=dados.get("preco_original"),
                    cupom=dados.get("cupom")
                )

                await publish_offer(context.bot, copies, dados.get("image_url"))
                mark_seen(product_url)
                count += 1
                
                logger.info("[SCHEDULER] Aguardando 3s para evitar rate limit...")
                await asyncio.sleep(3)

            else:
                # ── MODO DE APROVAÇÃO MANUAL ─────────────────────────────────
                # O link afiliado LONGO (com tag) é guardado na fila.
                # O encurtamento OCORRE SOMENTE quando o admin clica Aprovar.
                offer_id = uuid.uuid4().hex[:12]
                if "pending_offers" not in context.bot_data:
                    context.bot_data["pending_offers"] = {}

                # Copy de prévia usa o link longo (para o admin auditar a tag)
                from bot.services.copy_builder import build_copy
                copies_preview = build_copy(
                    nome=dados["title"],
                    preco=dados.get("preco", "Preço não disponível"),
                    loja=dados.get("loja", "Loja"),
                    store_key=store_key,
                    short_url=affiliate_url,   # ← link longo na prévia
                    legenda_ia=copy_ia,
                    preco_original=dados.get("preco_original"),
                    cupom=dados.get("cupom")
                )

                context.bot_data["pending_offers"][offer_id] = {
                    "product_url":   product_url,          # URL da fonte (para dedup)
                    "original_url":  dados.get("final_url", product_url),  # URL canônica Amazon
                    "mensagem":      copies_preview["telegram"],
                    "copies":        copies_preview,
                    "imagem":        dados.get("image_url"),
                    "nome":          dados["title"],
                    "affiliate_url": affiliate_url,        # link longo COM tag
                    "store_key":     store_key,
                    "cupom":         dados.get("cupom"),
                    "copy_ia":       copy_ia,
                    "dados_produto": {
                        "titulo":        dados["title"],
                        "preco":         dados.get("preco", "Preço não disponível"),
                        "preco_original":dados.get("preco_original"),
                        "imagem":        dados.get("image_url"),
                        "store":         dados.get("loja", "Amazon"),
                    },
                }

                # Salva na fila persistente
                from bot.utils.review_store import save_review_queue
                save_review_queue(context.bot_data["pending_offers"])

                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Aprovar",  callback_data=f"review_aprovar:{offer_id}"),
                        InlineKeyboardButton("❌ Rejeitar", callback_data=f"review_rejeitar:{offer_id}"),
                    ],
                    [InlineKeyboardButton("✏️ Corrigir",   callback_data=f"review_corrigir:{offer_id}")],
                ])

                # Prévia enviada AO ADMIN — mostra AMBOS os links para auditoria
                original_url = dados.get("final_url", product_url)
                preview_text = (
                    f"🔎 <b>OFERTA ENCONTRADA</b> — <i>{escape_html(source_name)}</i>\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📦 <b>{escape_html(dados['title'])}</b>\n"
                    f"💰 <b>Preço:</b> {escape_html(dados.get('preco', '—'))}"
                    + (f"  <s>{escape_html(dados.get('preco_original', ''))}</s>" if dados.get('preco_original') else "") + "\n"
                    + (f"🎟️ <b>Cupom:</b> <code>{escape_html(dados.get('cupom', ''))}</code>\n" if dados.get('cupom') else "")
                    + "\n"
                    f"🌐 <b>Link original do produto:</b>\n"
                    f"<code>{escape_html(original_url)}</code>\n\n"
                    f"🔗 <b>Seu link (com a tag):</b>\n"
                    f"<code>{escape_html(affiliate_url)}</code>\n\n"
                    "⚠️ <i>O link será encurtado apenas ao publicar no canal.</i>"
                )

                for admin_id in ADMIN_IDS:
                    try:
                        if dados.get("image_url"):
                            await context.bot.send_photo(
                                chat_id=admin_id,
                                photo=dados["image_url"],
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
                            )
                    except Exception as e:
                        logger.warning(f"[SCHEDULER] Falha ao notificar admin {admin_id}: {e}")

                # NOTA: mark_seen é chamado APENAS após aprovação (em review_queue.py)
                # Aqui NÃO marcamos como visto para permitir reprocessamento se rejeitado
                count += 1
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"[SCHEDULER] Falha crítica ao processar item {product_url}: {e}", exc_info=True)

    if trigger_user_id:
        pending_count = len(context.bot_data.get("pending_offers", {}))
        keyboard = None
        
        if AUTO_APPROVE:
            status_msg = f"✅ <b>Varredura concluída!</b>\n{count} ofertas publicadas automaticamente."
        else:
            status_msg = f"✅ <b>Varredura concluída!</b>\n{count} novas ofertas aguardando aprovação."
            if pending_count > 0:
                status_msg += f"\n\nTotal na fila de revisão: <b>{pending_count}</b>"
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ Aprovar Todas", callback_data="review_bulk:approve_all")],
                    [InlineKeyboardButton("🚫 Limpar Fila", callback_data="review_bulk:clear_all")],
                    [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="monitor_voltar")]
                ])

        if count == 0 and pending_count == 0:
            status_msg = "ℹ️ A varredura não encontrou novos itens ou todos já foram processados."
            keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data="monitor_voltar")]])
            
        await context.bot.send_message(
            chat_id=trigger_user_id, 
            text=status_msg, 
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard
        )


    logger.info(f"[SCHEDULER] Varredura finalizada. Total processado: {count}/{limit}")
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
    Setup inicial. Inicia o monitoramento automaticamente no boot.
    """
    logger.info('[SCHEDULER] Iniciando monitoramento automático.')
    start_monitor(app)
