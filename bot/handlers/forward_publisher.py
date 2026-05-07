import logging
import asyncio
import re

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.services.affiliate_link_service import injetar_link_afiliado, _detectar_loja
from bot.utils.channel_store import get_channels
from bot.utils.config import TELEGRAM_CHANNEL_ID
from bot.utils.telegram_utils import normalize_chat_id
from bot.services.copy_builder import build_copy

logger = logging.getLogger(__name__)

CB_PROCESSAR_TUDO = "encam_processar_tudo"
CB_CANCELAR_ENCAM = "encam_cancelar"

async def capturar_midia(message) -> dict:
    midia = {"tipo": None, "file_id": None}
    if message.photo:
        midia = {"tipo": "photo", "file_id": message.photo[-1].file_id}
    elif message.document and getattr(message.document, "mime_type", "") and message.document.mime_type.startswith("image/"):
        midia = {"tipo": "photo", "file_id": message.document.file_id}
    elif message.video:
        midia = {"tipo": "video", "file_id": message.video.file_id}
    elif message.animation:
        midia = {"tipo": "animation", "file_id": message.animation.file_id}
    return midia

async def enviar_com_midia(bot, chat_id, midia, texto, keyboard=None):
    tipo = midia.get("tipo")
    file_id = midia.get("file_id")
    try:
        if tipo == "photo" and file_id:
            await bot.send_photo(chat_id=chat_id, photo=file_id,
                caption=texto, parse_mode="HTML", reply_markup=keyboard)
        elif tipo == "video" and file_id:
            await bot.send_video(chat_id=chat_id, video=file_id,
                caption=texto, parse_mode="HTML", reply_markup=keyboard)
        elif tipo == "animation" and file_id:
            await bot.send_animation(chat_id=chat_id, animation=file_id,
                caption=texto, parse_mode="HTML", reply_markup=keyboard)
        else:
            await bot.send_message(chat_id=chat_id, text=texto,
                parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        print(f"[ENVIO] ❌ Erro: {e}")
        await bot.send_message(chat_id=chat_id, text=texto,
            parse_mode="HTML", reply_markup=keyboard)

async def start_forward_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["modo_encaminhamento"] = True
    context.user_data["fila_encaminhamentos"] = []

    keyboard = [
        [InlineKeyboardButton("⚙️ Processar Tudo", callback_data=CB_PROCESSAR_TUDO)],
        [InlineKeyboardButton("✏️ Corrigir", callback_data="frev_corrigir")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_ENCAM)]
    ]

    text = (
        "📩 <b>Encaminhe as ofertas que você quer postar.</b>\n\n"
        "Pode enviar várias — eu organizo tudo pra você.\n\n"
        "📊 Aguardando mensagens... <b>0/20</b>"
    )

    msg = await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data["msg_contador_id"] = msg.message_id
    context.user_data["chat_contador_id"] = msg.chat_id

async def receive_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("modo_encaminhamento"):
        return
    if context.user_data.get("estado_correcao"):
        return

    fila = context.user_data.get("fila_encaminhamentos", [])
    if len(fila) >= 20:
        return

    msg = update.message
    if not msg:
        return

    midia = await capturar_midia(msg)
    texto = msg.text or msg.caption or ""

    if not texto and not midia.get("file_id"):
        return

    fila.append({
        "midia": midia,
        "texto_original": texto,
        "processado": False
    })
    
    context.user_data["fila_encaminhamentos"] = fila
    qtd = len(fila)

    # Cancelar job anterior se existir
    job_key = f"batch_{update.effective_user.id}"
    current_jobs = context.job_queue.get_jobs_by_name(job_key)
    for job in current_jobs:
        job.schedule_removal()

    # Se chegou a 20, finaliza na hora
    if qtd >= 20:
        await finalizar_lote_encaminhamento(context, update.effective_chat.id, update.effective_user.id)
    else:
        # Agenda finalização do lote em 4 segundos
        if not context.job_queue:
            logger.error("[ENCAM] JobQueue não disponível!")
            await finalizar_lote_encaminhamento(context, update.effective_chat.id, update.effective_user.id)
            return

        context.job_queue.run_once(
            callback=lote_timer_callback,
            when=4,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            name=job_key,
            data={"user_id": update.effective_user.id}
        )
        
        # Feedback visual rápido (opcional, mas bom para UX)
        # Para evitar spam de edit, só editamos a cada 2 mensagens ou se for a primeira
        if qtd == 1 or qtd % 3 == 0:
            await atualizar_status_coleta(context, update.effective_chat.id, qtd)

async def lote_timer_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    await finalizar_lote_encaminhamento(context, job.chat_id, job.data["user_id"])

async def atualizar_status_coleta(context: ContextTypes.DEFAULT_TYPE, chat_id: int, qtd: int):
    msg_id = context.user_data.get("msg_contador_id")
    if not msg_id: return
    
    text = (
        f"📊 <b>Mensagens recebidas: {qtd}/20</b>\n\n"
        "Continuando a coletar...\n"
        "Encaminhe mais ou aguarde para processar."
    )
    
    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            parse_mode="HTML"
        )
    except: pass

async def finalizar_lote_encaminhamento(context, chat_id, user_id):
    # Força a recuperação do user_data correto da aplicação
    user_data = context.application.user_data.get(user_id, {})
    fila = user_data.get("fila_encaminhamentos", [])
    
    if not fila:
        return

    qtd = len(fila)
    msg_id = user_data.get("msg_contador_id")
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Processar Tudo", callback_data=CB_PROCESSAR_TUDO)],
        [InlineKeyboardButton("✏️ Corrigir", callback_data="frev_corrigir")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_ENCAM)]
    ]

    if qtd >= 20:
        user_data["modo_encaminhamento"] = False
        text = (
            "⚠️ <b>Limite de 20 mensagens atingido!</b>\n\n"
            f"✅ <b>{qtd} mensagens prontas para processar.</b>\n"
            "Clique abaixo para transformar tudo em ofertas."
        )
    else:
        linhas = []
        for i, item in enumerate(fila):
            txt_primeira = item["texto_original"].split('\n')[0][:25].strip() if item["texto_original"] else "Sem texto"
            linhas.append(f"✅ Mensagem {i+1}: {txt_primeira}...")
            
        mensagens_texto = "\n".join(linhas)
        text = (
            f"📊 <b>Mensagens recebidas: {qtd}/20</b>\n\n"
            f"{mensagens_texto}\n\n"
            f"Tudo pronto! Clique em ⚙️ <b>Processar Tudo</b>."
        )

    try:
        if msg_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception as e:
        logger.error(f"Erro ao finalizar lote: {e}")

async def cancel_forward_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data["modo_encaminhamento"] = False
    context.user_data["fila_encaminhamentos"] = []
    
    from bot.handlers.start import start_command
    await start_command(update, context)

def barra_progresso(atual: float, total: int) -> str:
    if total == 0:
        return f"[{'░' * 20}] 0%"
    # Ensure current is not more than total
    atual = min(atual, total)
    preenchido = int((atual / total) * 20)
    vazio = 20 - preenchido
    porcentagem = int((atual / total) * 100)
    barra = "█" * preenchido + "░" * vazio
    return f"[{barra}] {porcentagem}%"

def gerar_copy(titulo: str, preco: str, loja: str, link: str, cupom: str = None) -> str:
    # Prepara legenda básica se houver cupom
    legenda = None
    if cupom:
        legenda = f"🎟️ Use o cupom: <b>{cupom}</b>\n\n✅ Produto original\n✅ Melhor preço do dia"
    
    # Usa o construtor centralizado para garantir o estilo "OFERTA IMPERDÍVEL"
    copy_dict = build_copy(
        nome=titulo,
        preco=preco,
        loja=loja,
        store_key=loja.lower(),
        short_url=link,
        legenda_ia=legenda
    )
    return copy_dict["telegram"]

async def process_all_forwardings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["modo_encaminhamento"] = False
    fila = context.user_data.get("fila_encaminhamentos", [])
    total = len(fila)

    if total == 0:
        await query.edit_message_text("⚠️ Nenhuma mensagem foi encaminhada.", parse_mode="HTML")
        await asyncio.sleep(2)
        from bot.handlers.start import start_command
        await start_command(update, context)
        return

    context.user_data["fila_revisao"] = []
    # Salva o total ANTES de processar para o contador da revisão não quebrar
    context.user_data["encam_total_processado"] = total
    # Zera a fila de encaminhamentos agora que o total foi salvo
    context.user_data["fila_encaminhamentos"] = []
    
    chat_id = query.message.chat_id
    msg_id = query.message.message_id
    
    sem_link_qtd = 0

    for index, item in enumerate(fila):
        atual = index + 1
        texto_original = item["texto_original"]
        midia = item["midia"]
        
        titulo_resumo = texto_original.split('\n')[0][:25].strip() if texto_original else "Produto"
        
        # Passo 1
        prog_texto = (
            "⚙️ <b>Processando suas ofertas...</b>\n\n"
            f"📦 Analisando item <b>{atual}/{total}</b>: {titulo_resumo}...\n"
            f"🔍 Identificando loja e links...\n\n"
            f"{barra_progresso((atual-1) + 0.1, total)}"
        )
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode="HTML")
        await asyncio.sleep(0.6)

        # Extração
        urls = re.findall(r'https?://[^\s<>"]+', texto_original)
        link_original = urls[0] if urls else None
        
        if not link_original:
            sem_link_qtd += 1
            pass 

        link_afiliado = await injetar_link_afiliado(link_original) if link_original else None
        loja_detectada = _detectar_loja(link_afiliado) if link_afiliado else "Desconhecida"
        
        # Passo 2
        prog_texto = (
            "⚙️ <b>Processando suas ofertas...</b>\n\n"
            f"📦 Processando <b>{atual}/{total}</b>: {titulo_resumo}...\n"
            f"🏪 Loja: <b>{loja_detectada.upper()}</b> ✅\n"
            f"🔑 Aplicando seu link de afiliado...\n\n"
            f"{barra_progresso((atual-1) + 0.5, total)}"
        )
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode="HTML")
        await asyncio.sleep(0.6)
        
        # Preços, Cupom e Copy
        precos = re.findall(r'R\$\s*[\d.,]+', texto_original)
        preco = precos[0] if precos else "Confira o preço"

        cupons = re.findall(r'\b[A-Z0-9]{4,15}\b', texto_original)
        # Filtra cupons muito comuns ou que sejam links truncados
        cupons = [c for c in cupons if not c.startswith('HTTP') and len(c) > 4]
        cupom = cupons[0] if cupons else None
        
        link_final = link_afiliado or link_original or "Sem link"
        
        titulo_copy = titulo_resumo
        if len(texto_original.split('\n')) > 1:
            titulo_copy = texto_original.split('\n')[0]
            
        copy_gerada = gerar_copy(titulo_copy, preco, loja_detectada, link_final, cupom)

        # Passo 3
        prog_texto = (
            "⚙️ <b>Processando suas promoções...</b>\n\n"
            f"📦 Processando <b>{atual}/{total}</b>: {titulo_resumo}...\n"
            f"🏪 Loja: {loja_detectada.capitalize()} ✅\n"
            f"🔑 Link afiliado: {link_final} ✅\n"
            f"✍️ Reescrevendo copy...\n\n"
            f"{barra_progresso((atual-1) + 0.8, total)}"
        )
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode="HTML")
        await asyncio.sleep(0.6)

        context.user_data["fila_revisao"].append({
            "midia": midia,
            "copy": copy_gerada,
            "link_afiliado": link_afiliado,
            "preco": preco,
            "loja": loja_detectada,
            "aprovado": False,
            "index": index,
            "titulo": titulo_resumo
        })
        
        # Passo 4
        if atual < total:
            prog_texto = (
                "⚙️ <b>Processando suas promoções...</b>\n\n"
                f"✅ <b>{atual}/{total} concluída</b> — {titulo_resumo}\n"
                f"⚙️ Processando <b>{atual+1}/{total}</b>...\n\n"
                f"{barra_progresso(atual, total)}"
            )
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode="HTML")
            await asyncio.sleep(0.6)
            
    # Conclusão do Processamento
    sucesso_qtd = total - sem_link_qtd
    res_texto = (
        "✅ <b>Pronto! Ofertas organizadas.</b>\n\n"
        "📊 Resultado do Processamento:\n"
        f"✅ {sucesso_qtd} promoções identificadas\n"
        f"⚠️ {sem_link_qtd} sem link detectado\n\n"
        "O que deseja fazer agora?"
    )
    
    keyboard = [
        [InlineKeyboardButton("👀 Revisar e Aprovar Uma a Uma", callback_data="encam_revisar")],
        [InlineKeyboardButton("✅ Aprovar e Publicar Todas", callback_data="encam_aprovar_todas")],
        [InlineKeyboardButton("❌ Cancelar Tudo", callback_data=CB_CANCELAR_ENCAM),
         InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="menu_principal")]
    ]
    
    await context.bot.edit_message_text(
        chat_id=chat_id,
        message_id=msg_id,
        text=res_texto,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def encam_revisar_uma(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try:
        await query.message.delete()
    except:
        pass
        
    await show_next_review(update, context)

async def show_next_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fila = context.user_data.get("fila_revisao", [])
    if not fila:
        chat_id = update.effective_chat.id
        await context.bot.send_message(
            chat_id=chat_id,
            text="🎉 <b>Revisão concluída!</b>\nTodas as promoções foram processadas.",
            parse_mode="HTML"
        )
        from bot.handlers.start import start_command
        await asyncio.sleep(2)
        await start_command(update, context)
        return

    item = fila[0]
    # Total sempre vem de encam_total_processado (salvo antes de zerar a fila)
    # Fallback: usa o tamanho atual da fila de revisão se por algum motivo não foi salvo
    total = context.user_data.get("encam_total_processado") or len(fila)
    atual = total - len(fila) + 1
    
    msg_texto = (
        f"💎 <b>PRÉVIA — {atual} de {total}</b>\n\n"
        f"{item['copy']}\n\n"
        "━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Link de conferência:</b>\n"
        f"<code>{item.get('link_afiliado') or 'Sem link'}</code>"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Aprovar e Postar", callback_data="frev_aprovar")],
        [InlineKeyboardButton("✏️ Corrigir", callback_data="frev_corrigir"),
         InlineKeyboardButton("❌ Descartar", callback_data="frev_descartar")],
        [InlineKeyboardButton("⏭️ Ver Próxima", callback_data="frev_proxima"),
         InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="menu_principal")]
    ]

    chat_id = update.effective_chat.id
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id

    await enviar_com_midia(
        bot=context.bot,
        chat_id=chat_id,
        midia=item.get("midia", {}),
        texto=msg_texto,
        keyboard=InlineKeyboardMarkup(keyboard)
    )

async def frev_aprovar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fila = context.user_data.get("fila_revisao", [])
    if not fila:
        return

    item = fila.pop(0)

    try:
        await query.message.delete()
    except:
        pass

    canais_destino = [TELEGRAM_CHANNEL_ID]
    for ch in get_channels():
        if ch not in canais_destino:
            canais_destino.append(ch)

    try:
        for ch in canais_destino:
            cid = normalize_chat_id(ch)
            await enviar_com_midia(context.bot, cid, item.get("midia", {}), item["copy"])
            await asyncio.sleep(2)
        
        context.user_data["fila_revisao"] = fila
        await asyncio.sleep(1)
        await show_next_review(update, context)
        
    except Exception as e:
        await context.bot.send_message(query.message.chat_id, f"❌ Erro ao postar: {e}")

async def frev_descartar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fila = context.user_data.get("fila_revisao", [])
    if fila:
        fila.pop(0)

    try: await query.message.delete()
    except: pass
    
    context.user_data["fila_revisao"] = fila
    await show_next_review(update, context)

async def frev_proxima(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fila = context.user_data.get("fila_revisao", [])
    if fila:
        item = fila.pop(0)
        fila.append(item)

    try: await query.message.delete()
    except: pass
    
    context.user_data["fila_revisao"] = fila
    await show_next_review(update, context)

async def frev_corrigir(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try: await query.message.delete()
    except: pass
    
    context.user_data["estado_correcao"] = "tudo"
    await context.bot.send_message(query.message.chat_id, "✍️ Envie a nova copy completa (inclua os dados alterados):")

async def receive_correction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("estado_correcao"):
        return

    texto = update.message.text
    if not texto: return

    fila = context.user_data.get("fila_revisao", [])
    if not fila:
        context.user_data["estado_correcao"] = None
        return

    fila[0]["copy"] = texto
    context.user_data["estado_correcao"] = None
    
    await update.message.reply_text("✅ Substituição concluída!")
    await show_next_review(update, context)


async def encam_aprovar_todas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fila = context.user_data.get("fila_revisao", [])
    total = len(fila)
    if total == 0:
        await query.message.reply_text("⚠️ Nenhuma promoção para publicar.")
        return

    chat_id = query.message.chat_id
    msg = await query.message.edit_text("📤 <b>Publicando todas as promoções no canal...</b>\n\n", parse_mode="HTML")
    msg_id = msg.message_id
    
    canais_destino = [TELEGRAM_CHANNEL_ID]
    for ch in get_channels():
        if ch not in canais_destino:
            canais_destino.append(ch)

    sucesso = 0
    erros = 0

    for index, item in enumerate(fila):
        atual = index + 1
        titulo = item.get("titulo", "Produto")

        prog_texto = (
            "📤 <b>Publicando todas as promoções no canal...</b>\n\n"
            f"⏳ Publicando {atual}/{total}: {titulo}\n\n"
            f"{barra_progresso(atual-1, total)}"
        )
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode="HTML")
        except: pass

        for ch in canais_destino:
            cid = normalize_chat_id(ch)
            try:
                await enviar_com_midia(context.bot, cid, item.get("midia", {}), item["copy"])
            except Exception as e:
                logger.error(f"Erro publicando: {e}")
                erros += 1

        sucesso += 1
        
        if atual < total:
            prog_texto = (
                "📤 <b>Publicando todas as promoções no canal...</b>\n\n"
                f"✅ Publicada {atual}/{total}: {titulo}\n"
                f"⏳ Aguardando anti-spam...\n\n"
                f"{barra_progresso(atual, total)}"
            )
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode="HTML")
            except: pass
            await asyncio.sleep(3)
            
    context.user_data["fila_revisao"] = []
    
    relatorio = (
        "🎉 <b>Todas as promoções foram publicadas!</b>\n\n"
        "📊 Resumo:\n"
        f"✅ {sucesso} publicadas com sucesso\n"
        f"❌ {erros} erros\n"
    )
    
    keyboard = [[InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="menu_principal")]]
    await context.bot.edit_message_text(
        chat_id=chat_id, 
        message_id=msg_id, 
        text=relatorio, 
        parse_mode="HTML", 
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
