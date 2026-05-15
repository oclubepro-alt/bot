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
CB_AGENDAR_MENU = "encam_agendar_menu"
CB_AGENDAR_EXEC = "encam_agendar_exec"
CB_AGENDAR_ESTE_MENU = "encam_agendar_este_menu"
CB_AGENDAR_ESTE_EXEC = "encam_agendar_este_exec"

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

async def enviar_com_midia(bot, chat_id, midia, texto, affiliate_url: str | None = None, reply_markup=None):
    tipo = midia.get("tipo")
    file_id = midia.get("file_id")
    
    # Se não veio o teclado pronto, mas tem link, cria o botão de oferta
    if not reply_markup and affiliate_url:
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton("🛒 PEGAR OFERTA", url=affiliate_url)
        ]])

    try:
        if tipo == "photo" and file_id:
            await bot.send_photo(chat_id=chat_id, photo=file_id,
                caption=texto, parse_mode="HTML", reply_markup=reply_markup)
        elif tipo == "video" and file_id:
            await bot.send_video(chat_id=chat_id, video=file_id,
                caption=texto, parse_mode="HTML", reply_markup=reply_markup)
        elif tipo == "animation" and file_id:
            await bot.send_animation(chat_id=chat_id, animation=file_id,
                caption=texto, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id=chat_id, text=texto,
                parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"[ENVIO] ❌ Erro: {e}")
        try:
            await bot.send_message(chat_id=chat_id, text=texto,
                parse_mode="HTML", reply_markup=reply_markup)
        except: pass

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
    texto = msg.text_html or msg.caption_html or ""

    if not texto and not midia.get("file_id"):
        return

    # Verificação de Marca d'água (Fase 1)
    if midia.get("tipo") == "photo":
        try:
            import io
            file = await context.bot.get_file(midia["file_id"])
            out = io.BytesIO()
            await file.download_to_memory(out)
            img_bytes = out.getvalue()
            
            from bot.services.vision_service import detect_watermark
            tem_marca = await detect_watermark(img_bytes)
            
            if tem_marca:
                logger.warning(f"[ENCAM] 🚫 Marca d'água detectada. Ignorando mensagem.")
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="🚫 <b>Mensagem ignorada!</b>\nDetectamos uma marca d'água ou logo de outro canal nesta imagem.",
                    parse_mode="HTML"
                )
                return
        except Exception as e:
            logger.error(f"[ENCAM] Erro ao processar visão: {e}")

    fila.append({
        "midia": midia,
        "texto_original": texto,
        "processado": False
    })
    
    context.user_data["fila_encaminhamentos"] = fila
    qtd = len(fila)

    # Gerenciamento de Lote via asyncio (Debounce)
    # Cancela timer anterior se houver
    antigo_timer = context.user_data.get("timer_lote")
    if antigo_timer:
        antigo_timer.cancel()

    async def wait_timer(ctx, c_id, u_id):
        try:
            await asyncio.sleep(4)
            await finalizar_lote_encaminhamento(ctx, c_id, u_id)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[ENCAM] Erro no timer: {e}")

    if qtd >= 20:
        await finalizar_lote_encaminhamento(context, update.effective_chat.id, update.effective_user.id)
    else:
        # Agenda o novo timer
        context.user_data["timer_lote"] = asyncio.create_task(
            wait_timer(context, update.effective_chat.id, update.effective_user.id)
        )
        
        # Feedback visual rápido
        if qtd == 1 or qtd % 3 == 0:
            await atualizar_status_coleta(context, update.effective_chat.id, qtd)

async def atualizar_status_coleta(context: ContextTypes.DEFAULT_TYPE, chat_id: int, qtd: int):
    # Usa o user_data do contexto atual (MessageHandler)
    msg_id = context.user_data.get("msg_contador_id")
    if not msg_id: return
    
    text = (
        f"📊 <b>Mensagens recebidas: {qtd}/20</b>\n\n"
        "Continuando a coletar...\n"
        "Encaminhe mais ou aguarde 4s para processar."
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
    logger.info(f"[TIMER] ⏳ Iniciando finalização de lote para {user_id}")
    
    # Tenta pegar o user_data do contexto ou da aplicação (fallback)
    user_data = getattr(context, "user_data", None)
    if user_data is None:
        user_data = context.application.user_data.get(user_id, {})
        
    fila = user_data.get("fila_encaminhamentos", [])
    if not fila:
        logger.info(f"[TIMER] ℹ️ Fila vazia para {user_id}, encerrando.")
        return
    
    total_recebido = len(fila)
    msg_id = user_data.get("msg_contador_id")
    
    keyboard = [
        [InlineKeyboardButton("⚙️ Processar Tudo", callback_data=CB_PROCESSAR_TUDO)],
        [InlineKeyboardButton("🎫 Adicionar Cupom", callback_data="encam_add_cupom")],
        [InlineKeyboardButton("✏️ Corrigir", callback_data="frev_corrigir")],
        [InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_ENCAM)]
    ]

    if total_recebido >= 20:
        user_data["modo_encaminhamento"] = False
        text = (
            "⚠️ <b>Limite de 20 mensagens atingido!</b>\n\n"
            f"✅ <b>{total_recebido} mensagens prontas para processar.</b>\n"
            "Clique abaixo para transformar tudo em ofertas."
        )
    else:
        linhas = []
        for i, item in enumerate(fila):
            txt_primeira = item["texto_original"].split('\n')[0][:25].strip() if item["texto_original"] else "Sem texto"
            linhas.append(f"✅ Mensagem {i+1}: {txt_primeira}...")
            
        mensagens_texto = "\n".join(linhas)
        text = (
            f"📊 <b>Mensagens recebidas: {total_recebido}/20</b>\n\n"
            f"{mensagens_texto}\n\n"
            f"Tudo pronto! Clique em ⚙️ <b>Processar Tudo</b>."
        )

    # Tenta apagar a mensagem de status anterior para não poluir
    if msg_id:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except:
            pass

    try:
        # Sempre envia uma NOVA mensagem no final do lote para ficar no rodapé do chat
        new_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        # Atualiza o ID para que, se ele mandar mais, a gente saiba qual apagar
        user_data["msg_contador_id"] = new_msg.message_id
    except Exception as e:
        logger.error(f"Erro ao finalizar lote: {e}")

async def encam_add_cupom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    context.user_data["estado_correcao"] = "cupom_inicial"
    await query.edit_message_text(
        "🎫 <b>MODO CUPOM (BATCH)</b>\n\nEnvie o código do cupom que será aplicado à <b>última mensagem</b> recebida:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancelar", callback_data="encam_cancelar_cupom")]])
    )

async def encam_cancelar_cupom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["estado_correcao"] = None
    await finalizar_lote_encaminhamento(context, update.effective_chat.id, update.effective_user.id)

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
    # Usa o construtor centralizado com o parâmetro cupom nativo
    copy_dict = build_copy(
        nome=titulo,
        preco=preco,
        loja=loja,
        store_key=loja.lower(),
        short_url=link,
        cupom=cupom
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
        
        # Mantém a copy original e remove TODOS os links encontrados (vão para o botão)
        urls = re.findall(r'https?://[^\s<>"]+', texto_original)
        copy_gerada = texto_original
        link_principal_afiliado = None

        for url in urls:
            # Tenta injetar o link de afiliado (para usar no botão)
            link_af = await injetar_link_afiliado(url)
            if link_af:
                # Remove o link do corpo da mensagem
                copy_gerada = copy_gerada.replace(url, "")
                if not link_principal_afiliado:
                    link_principal_afiliado = link_af
        
        # Limpeza de labels residuais e espaços extras
        copy_gerada = re.sub(r'(?i)(?:link|compre aqui|oferta|🛒 pegar oferta|pegar oferta|🛒 compre aqui)[:\s]*$', '', copy_gerada, flags=re.MULTILINE)
        copy_gerada = re.sub(r'\n\s*\n', '\n\n', copy_gerada).strip()
        
        # Se removeu links, garante que o usuário saiba que deve clicar no botão
        if link_principal_afiliado and "botão abaixo" not in copy_gerada.lower():
            copy_gerada += "\n\n🔗 <b>Acesse a oferta clicando no botão abaixo! 👇</b>"

        # Se não houver link de afiliado, usa o original para o botão
        link_final_botao = link_principal_afiliado or (urls[0] if urls else "Sem link")

        # Mantém a detecção de preços e cupons apenas para metadados/revisão
        precos = re.findall(r'R\$\s*[\d.,]+', texto_original)
        preco = precos[0] if precos else "Confira o preço"

        # No encaminhamento, NÃO tentamos adivinhar cupom do meio do texto
        # Isso evita que palavras como "VALOR" ou "OFERTA" sejam confundidas com cupons
        cupom = item.get("cupom") 
        
        # Passo 3
        prog_texto = (
            "⚙️ <b>Processando suas promoções...</b>\n\n"
            f"📦 Processando <b>{atual}/{total}</b>: {titulo_resumo}...\n"
            f"🏪 Loja: {loja_detectada.capitalize()} ✅\n"
            f"🔗 Links processados: {len(urls)} ✅\n"
            f"✍️ Trocando links...\n\n"
            f"{barra_progresso((atual-1) + 0.8, total)}"
        )
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode="HTML")
        await asyncio.sleep(0.6)

        import uuid
        from datetime import datetime
        offer_id = f"fwd_{uuid.uuid4().hex[:8]}"
        
        item_revisao = {
            "type": "forward",
            "midia": midia,
            "copy": copy_gerada,
            "texto_base": texto_original,
            "link_original": link_original,
            "affiliate_url": link_final_botao,
            "preco": preco,
            "loja": loja_detectada,
            "cupom": cupom,
            "aprovado": False,
            "preserve_fidelity": True, # FLAG CRÍTICA: Mantém o texto original
            "titulo": titulo_resumo, # Adicionado para compatibilidade com gerar_copy se necessário
            "nome": titulo_resumo,
            "imagem": midia.get("file_id") if isinstance(midia, dict) else midia,
            "created_at": datetime.now().isoformat()
        }

        # 1. Fila de revisão do usuário (para "Aprovar Todas" funcionar)
        if "fila_revisao" not in context.user_data:
            context.user_data["fila_revisao"] = []
        context.user_data["fila_revisao"].append(item_revisao)

        # 2. Fila persistente (Dashboard)
        if "pending_offers" not in context.bot_data:
            context.bot_data["pending_offers"] = {}
        context.bot_data["pending_offers"][offer_id] = item_revisao
        
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

    # Salva na fila persistente (Dashboard)
    from bot.utils.review_store import save_review_queue
    save_review_queue(context.bot_data["pending_offers"])
            
    # Conclusão do Processamento
    sucesso_qtd = total - sem_link_qtd
    cupons_count = sum(1 for item in context.user_data.get("fila_revisao", []) if item.get('cupom'))
    
    res_texto = (
        "✅ <b>Pronto! Ofertas organizadas.</b>\n\n"
        "📊 Resultado do Processamento:\n"
        f"✅ {sucesso_qtd} promoções identificadas\n"
        f"🎟️ {cupons_count} cupons detectados\n"
        f"⚠️ {sem_link_qtd} sem link detectado\n\n"
        "O que deseja fazer agora?"
    )
    
    keyboard = [
        [InlineKeyboardButton("👀 Abrir Fila de Revisão (Mission Control)", callback_data="review_view:0")],
        [InlineKeyboardButton("✅ Aprovar Todas (Postar Agora)", callback_data="encam_aprovar_todas")],
        [InlineKeyboardButton("📅 Agendar Todos", callback_data=CB_AGENDAR_MENU)],
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
    
    cupom_val = item.get('cupom')
    cupom_info = f"🎟️ <b>Cupom:</b> <code>{cupom_val}</code>" if cupom_val else "🎟️ <b>Cupom:</b> <i>Nenhum detectado</i>"
    dica = "\n💡 <b>Dica:</b> Use o botão abaixo para adicionar ou editar o cupom!" if not cupom_val else ""
    
    msg_texto = (
        f"💎 <b>PRÉVIA — {atual} de {total}</b>\n\n"
        f"{item['copy']}\n"
    )

    keyboard = [
        [InlineKeyboardButton("✅ Aprovar e Postar", callback_data="frev_aprovar")],
        [InlineKeyboardButton("🎫 Adicionar/Editar Cupom", callback_data="frev_cupom")],
        [InlineKeyboardButton("✍️ Corrigir Legenda", callback_data="frev_corrigir"),
         InlineKeyboardButton("📅 Agendar Este", callback_data=CB_AGENDAR_ESTE_MENU)],
        [InlineKeyboardButton("❌ Descartar", callback_data="frev_descartar"),
         InlineKeyboardButton("⏭️ Ver Próxima", callback_data="frev_proxima")],
        [InlineKeyboardButton("🏠 Voltar ao Menu", callback_data="menu_principal")]
    ]

    chat_id = update.effective_chat.id
    if update.callback_query:
        chat_id = update.callback_query.message.chat_id

    await enviar_com_midia(
        bot=context.bot,
        chat_id=chat_id,
        midia=item.get("midia", {}),
        texto=msg_texto,
        reply_markup=InlineKeyboardMarkup(keyboard)
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
            await enviar_com_midia(
                bot=context.bot, 
                chat_id=cid, 
                midia=item.get("midia", {}), 
                texto=item["copy"],
                affiliate_url=item.get("affiliate_url")
            )
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

async def frev_cupom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    try: await query.message.delete()
    except: pass
    
    context.user_data["estado_correcao"] = "cupom"
    await context.bot.send_message(query.message.chat_id, "🎫 <b>MODO CUPOM</b>\n\nEnvie apenas o código do cupom abaixo (ou envie 'remover' para tirar):", parse_mode="HTML")

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

    if context.user_data.get("estado_correcao") == "cupom_inicial":
        fila_encam = context.user_data.get("fila_encaminhamentos", [])
        if fila_encam:
            fila_encam[-1]["cupom"] = texto.upper()
            await update.message.reply_text(f"✅ Cupom <b>{texto.upper()}</b> adicionado à última mensagem!", parse_mode="HTML")
        
        context.user_data["estado_correcao"] = None
        await finalizar_lote_encaminhamento(context, update.effective_chat.id, update.effective_user.id)
        return

    if context.user_data.get("estado_correcao") == "cupom":
        if texto.lower() == "remover":
            fila[0]["cupom"] = None
        else:
            fila[0]["cupom"] = texto.upper()
        
        # Se for encaminhamento, NÃO gera copy nova, apenas anexa o cupom
        item = fila[0]
        if item.get("preserve_fidelity"):
            # Apenas remove cupom antigo se houver e adiciona o novo no final para não estragar a copy
            clean_copy = re.sub(r'\n\n🎟️ Cupom:.*', '', item["copy"])
            if item["cupom"]:
                item["copy"] = f"{clean_copy}\n\n🎟️ Cupom: <b>{item['cupom']}</b>"
            else:
                item["copy"] = clean_copy
        else:
            item["copy"] = gerar_copy(
                titulo=item.get("titulo", "Produto"),
                preco=item.get("preco", ""),
                loja=item.get("loja", ""),
                link=item.get("link_afiliado", ""),
                cupom=item["cupom"]
            )
        await update.message.reply_text("✅ Cupom atualizado!")
    else:
        fila[0]["copy"] = texto
        await update.message.reply_text("✅ Legenda substituída!")

    context.user_data["estado_correcao"] = None
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
                await enviar_com_midia(
                    bot=context.bot, 
                    chat_id=cid, 
                    midia=item.get("midia", {}), 
                    texto=item["copy"],
                    affiliate_url=item.get("affiliate_url")
                )
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

async def encam_agendar_este_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exibe opções de tempo para agendar apenas O POST ATUAL."""
    query = update.callback_query
    await query.answer()

    texto = (
        "?? <b>Agendar ESTA Promoção</b>\n\n"
        "Em quanto tempo você deseja que esta promoção seja postada?\n"
        "Ela será movida para a fila de agendamento."
    )

    keyboard = [
        [InlineKeyboardButton("?? Em 30 minutos", callback_data=f"{CB_AGENDAR_ESTE_EXEC}:30")],
        [InlineKeyboardButton("?? Em 1 hora", callback_data=f"{CB_AGENDAR_ESTE_EXEC}:60")],
        [InlineKeyboardButton("?? Em 2 horas", callback_data=f"{CB_AGENDAR_ESTE_EXEC}:120")],
        [InlineKeyboardButton("?? Em 6 horas", callback_data=f"{CB_AGENDAR_ESTE_EXEC}:360")],
        [InlineKeyboardButton("?? Voltar", callback_data="frev_proxima")] 
    ]

    await query.edit_message_text(texto, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def encam_agendar_este_exec(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Agenda apenas o item atual da fila."""
    query = update.callback_query
    await query.answer()

    try:
        minutos = int(query.data.split(":")[-1])
    except:
        minutos = 30

    fila = context.user_data.get("fila_revisao", [])
    if not fila:
        return

    # O item sendo revisado é o FILA[0]
    item = fila.pop(0)
    context.user_data["fila_revisao"] = fila

    from bot.services.scheduler_queue_service import add_to_queue
    from bot.services.metrics_service import log_event
    
    # Adiciona à fila persistente
    add_to_queue(item)
    log_event("scheduled_single")

    # Feedback rápido
    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"? <b>Agendado!</b>\nEsta promoção entrará na fila de postagem (aprox. {minutos} min).",
        parse_mode="HTML"
    )

    # Deleta menu de tempo
    try: await query.message.delete()
    except: pass

    # Segue para o próximo
    await show_next_review(update, context)
