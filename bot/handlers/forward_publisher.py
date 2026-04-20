import logging
import asyncio
import re

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from bot.utils.constants import CB_PUBLICAR_ENCAMINHAMENTO
from bot.services.affiliate_link_service import injetar_link_afiliado, _detectar_loja

logger = logging.getLogger(__name__)

CB_PROCESSAR_TUDO = "encam_processar_tudo"
CB_CANCELAR_ENCAM = "encam_cancelar"

def extrair_texto_mensagem(message) -> str:
    """
    Extrai texto de qualquer tipo de mensagem.
    Mensagem só de texto → message.text
    Mensagem com foto/video → message.caption
    """
    texto = message.text or message.caption or ""
    print(f"[TEXTO] Extraído ({len(texto)} chars): {texto[:80]}...")
    return texto

async def capturar_midia_completa(message) -> dict:
    """
    Captura mídia de qualquer tipo de mensagem encaminhada.
    Retorna dict com tipo e file_id.
    """
    midia = {"tipo": None, "file_id": None}

    try:
        # CASO 1: Foto direta (mais comum em canais de promoção)
        if message.photo and len(message.photo) > 0:
            foto = message.photo[-1]  # sempre a maior resolução
            midia["tipo"] = "photo"
            midia["file_id"] = foto.file_id
            print(f"[MIDIA] ✅ Foto capturada | Resolução: {foto.width}x{foto.height}")

        # CASO 2: Documento que é imagem
        elif message.document and getattr(message.document, "mime_type", ""):
            if message.document.mime_type.startswith("image/"):
                midia["tipo"] = "photo"
                midia["file_id"] = message.document.file_id
                print(f"[MIDIA] ✅ Imagem como documento capturada")

        # CASO 3: Vídeo
        elif message.video:
            midia["tipo"] = "video"
            midia["file_id"] = message.video.file_id
            print(f"[MIDIA] ✅ Vídeo capturado")

        # CASO 4: GIF animado
        elif message.animation:
            midia["tipo"] = "animation"
            midia["file_id"] = message.animation.file_id
            print(f"[MIDIA] ✅ GIF capturado")

        else:
            print(f"[MIDIA] ℹ️ Mensagem sem mídia — apenas texto")

    except Exception as e:
        print(f"[MIDIA] ❌ Erro ao capturar mídia: {e}")

    return midia

async def enviar_com_midia(
    bot,
    chat_id,
    midia: dict,
    texto: str,
    keyboard=None,
    parse_mode: str = "HTML"
):
    tipo = midia.get("tipo")
    file_id = midia.get("file_id")

    try:
        if tipo == "photo" and file_id:
            await bot.send_photo(
                chat_id=chat_id,
                photo=file_id,
                caption=texto,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
            print(f"[ENVIO] ✅ Foto enviada para {chat_id}")

        elif tipo == "video" and file_id:
            await bot.send_video(
                chat_id=chat_id,
                video=file_id,
                caption=texto,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
            print(f"[ENVIO] ✅ Vídeo enviado para {chat_id}")

        elif tipo == "animation" and file_id:
            await bot.send_animation(
                chat_id=chat_id,
                animation=file_id,
                caption=texto,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
            print(f"[ENVIO] ✅ GIF enviado para {chat_id}")

        else:
            await bot.send_message(
                chat_id=chat_id,
                text=texto,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
            print(f"[ENVIO] ℹ️ Texto enviado para {chat_id} sem mídia")

    except Exception as e:
        print(f"[ENVIO] ❌ Erro no envio: {e}")
        # Fallback seguro: envia só o texto
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=texto,
                parse_mode=parse_mode,
                reply_markup=keyboard
            )
        except Exception as e2:
            print(f"[ENVIO] ❌ Fallback também falhou: {e2}")

async def start_forward_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["modo_encaminhamento"] = True
    context.user_data["fila_encaminhamentos"] = []

    keyboard = [
        [InlineKeyboardButton("✅ Processar Tudo", callback_data=CB_PROCESSAR_TUDO)],
        [InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_ENCAM)],
    ]

    text = (
        "📨 <b>Modo Encaminhamento Ativado!</b>\n\n"
        "Encaminhe até 20 mensagens de promoções de qualquer canal do Telegram diretamente aqui.\n\n"
        "Quando terminar, clique em ✅ Processar Tudo.\n\n"
        "📊 Mensagens recebidas: 0/20"
    )

    msg = await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data["encam_msg_id"] = msg.message_id
    context.user_data["encam_chat_id"] = msg.chat_id

async def receive_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message

    print("=" * 50)
    print(f"[DEBUG MIDIA] message.photo: {message.photo}")
    print(f"[DEBUG MIDIA] message.caption: {message.caption}")
    print(f"[DEBUG MIDIA] message.text: {message.text}")
    print(f"[DEBUG MIDIA] message.document: {message.document}")
    print(f"[DEBUG MIDIA] message.video: {message.video}")
    print(f"[DEBUG MIDIA] message.animation: {message.animation}")
    print(f"[DEBUG MIDIA] effective_attachment: {message.effective_attachment}")
    print(f"[DEBUG MIDIA] forward_from_chat: {message.forward_from_chat}")
    print("=" * 50)

    if not context.user_data.get("modo_encaminhamento"):
        return

    # Se estivermos aguardando correção de revisão na personal queue, ignoramos o acúmulo temporariamente
    if context.user_data.get("estado_correcao"):
        return

    fila = context.user_data.get("fila_encaminhamentos", [])
    if len(fila) >= 20:
        return

    msg = update.message
    if not msg:
        return

    texto = extrair_texto_mensagem(msg)
    midia = await capturar_midia_completa(msg)
    
    # Se nem texto nem midia tem (só uma mensagem muito atípica), ignoramos
    if not texto and not midia.get("file_id"):
        return

    primeira_linha = texto.split('\n')[0][:50] if texto else "Produto sem texto"

    fila.append({
        "texto": texto,
        "midia": midia,
        "nome_curto": primeira_linha
    })

    context.user_data["fila_encaminhamentos"] = fila
    qtd = len(fila)

    chat_id = context.user_data.get("encam_chat_id")
    msg_id = context.user_data.get("encam_msg_id")

    keyboard = [
        [InlineKeyboardButton("✅ Processar Tudo", callback_data=CB_PROCESSAR_TUDO)],
        [InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_ENCAM)],
    ]

    if qtd >= 20:
        context.user_data["modo_encaminhamento"] = False
        text = (
            "⚠️ <b>Limite de 20 mensagens atingido!</b>\n"
            "Clique em ✅ Processar Tudo para continuar."
        )
    else:
        lista_limitada = "\n".join([f"✅ {v['nome_curto']}..." for v in fila[:5]])
        if qtd > 5:
            lista_limitada += f"\n... e mais {qtd - 5} promoções"

        text = (
            "📨 <b>Modo Encaminhamento Ativado!</b>\n\n"
            f"📊 Mensagens recebidas: {qtd}/20\n"
            f"{lista_limitada}\n\n"
            "Encaminhe mais ou clique em ✅ Processar Tudo."
        )

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    except Exception as e:
        logger.error(f"Erro ao editar status modo encaminhamento: {e}")


async def cancel_forward_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["modo_encaminhamento"] = False
    context.user_data["fila_encaminhamentos"] = []

    from bot.handlers.start import start_command
    await start_command(update, context)

def barra_progresso(atual: int, total: int) -> str:
    if total == 0:
        return f"[{'░' * 20}] 0%"
    preenchido = int((atual / total) * 20)
    vazio = 20 - preenchido
    porcentagem = int((atual / total) * 100)
    return f"[{'█' * preenchido}{'░' * vazio}] {porcentagem}%"

def gerar_copy_encaminhamento(titulo: str, preco: str, cupom: str, link: str) -> str:
    cupom_linha = f"\n🎟️ Cupom: <b>{cupom}</b>" if cupom else ""
    return (
        f"🔥 <b>{titulo}</b>\n\n"
        f"💰 <b>{preco}</b>"
        f"{cupom_linha}\n\n"
        f"👉 <a href='{link}'>GARANTIR OFERTA AGORA</a>\n\n"
        f"⚡ Oferta por tempo limitado!"
    )

async def process_all_forwardings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    context.user_data["modo_encaminhamento"] = False
    fila = context.user_data.get("fila_encaminhamentos", [])
    total = len(fila)

    if total == 0:
        await query.edit_message_text("⚠️ Nenhuma mensagem foi encaminhada.")
        from bot.handlers.start import start_command
        await asyncio.sleep(2)
        await start_command(update, context)
        return

    if "fila_revisao" not in context.user_data:
        context.user_data["fila_revisao"] = []

    chat_id = query.message.chat_id
    msg_id = query.message.message_id

    sucesso_qtd = 0
    sem_link_qtd = 0

    for i, item in enumerate(fila):
        atual = i + 1
        texto = item["texto"]
        midia = item.get("midia", {})
        nome_curto = item["nome_curto"]

        # Inicia atualização
        prog_texto = (
            "⚙️ <b>Processando suas promoções...</b>\n\n"
            f"📦 Processando {atual}/{total}: {nome_curto}...\n"
            f"  🔗 Identificando link...\n\n"
            f"{barra_progresso(atual-1, total)}"
        )
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.5)

        # Extrair link
        urls = re.findall(r'https?://[^\s<>"]+', texto)
        link_original = urls[0] if urls else None

        if not link_original:
            sem_link_qtd += 1
            context.user_data["fila_revisao"].append({
                "midia": midia,
                "copy": texto,
                "link_afiliado": None,
                "link_cru": None,
                "preco": "Preço não informado",
                "loja": "Desconhecida",
                "status": "sem_link",
                "text_original": texto,
                "nome_curto": nome_curto
            })
            continue

        # Injetar afiliado
        link_afiliado = await injetar_link_afiliado(link_original)
        loja_detectada = _detectar_loja(link_afiliado)

        prog_texto = (
            "⚙️ <b>Processando suas promoções...</b>\n\n"
            f"📦 Processando {atual}/{total}: {nome_curto}...\n"
            f"  🔗 Identificando link... ✅\n"
            f"  🏪 Loja detectada: {loja_detectada.capitalize()}\n"
            f"  🔑 Aplicando tag afiliado...\n\n"
            f"{barra_progresso(atual-1, total)}"
        )
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.5)

        # Extrair preço
        precos = re.findall(r'R\$\s*[\d.,]+', texto)
        preco = precos[0] if precos else "Preço não informado"

        # Montar copy
        titulo = nome_curto
        cupom = "" # Pode adicionar extração de regex pra cupom futuramente
        copy_gerada = gerar_copy_encaminhamento(titulo, preco, cupom, link_afiliado)

        context.user_data["fila_revisao"].append({
            "midia": midia,
            "copy": copy_gerada,
            "link_afiliado": link_afiliado,
            "link_cru": link_afiliado,
            "preco": preco,
            "loja": loja_detectada,
            "status": "ok",
            "text_original": texto,
            "nome_curto": nome_curto
        })

        sucesso_qtd += 1

        prog_texto = (
            "⚙️ <b>Processando suas promoções...</b>\n\n"
            f"📦 Processando {atual}/{total}: {nome_curto}...\n"
            f"  🔗 Identificando link... ✅\n"
            f"  🏪 Loja detectada: {loja_detectada.capitalize()}\n"
            f"  🔑 Aplicando tag afiliado... ✅\n"
            f"  ✍️ Reescrevendo copy... ✅\n\n"
            f"{barra_progresso(atual, total)}"
        )
        await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=prog_texto, parse_mode=ParseMode.HTML)
        await asyncio.sleep(0.5)

    # Limpamos a fila temporária
    context.user_data["fila_encaminhamentos"] = []

    res_texto = (
        "✅ <b>Processamento Concluído!</b>\n\n"
        "📊 <b>Resultado:</b>\n"
        f"✅ {sucesso_qtd} promoções prontas para revisar\n"
    )
    if sem_link_qtd > 0:
        res_texto += f"⚠️ {sem_link_qtd} sem link identificado\n"

    res_texto += "\nIniciando fila de revisão..."
    await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=res_texto, parse_mode=ParseMode.HTML)
    await asyncio.sleep(2)

    await show_next_review(update, context)

async def show_next_review(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fila = context.user_data.get("fila_revisao", [])
    if not fila:
        if update.callback_query:
            await update.callback_query.message.reply_text("✅ Todas as promoções foram processadas!")
        else:
            await context.bot.send_message(update.effective_chat.id, "✅ Todas as promoções foram processadas!")
        from bot.handlers.start import start_command
        await start_command(update, context)
        return

    item = fila[0]
    keyboard = []

    if item["status"] == "sem_link":
        keyboard.append([InlineKeyboardButton("✏️ Corrigir (Inserir Link)", callback_data="frev_corrigir_link")])
    elif item["loja"] == "other":
        keyboard.append([InlineKeyboardButton("✅ Aprovar (Loja não reconhecida)", callback_data="frev_aprovar")])
    else:
        keyboard.append([InlineKeyboardButton("✅ Aprovar e Postar no Canal", callback_data="frev_aprovar")])

    keyboard.append([InlineKeyboardButton("✏️ Corrigir Texto", callback_data="frev_corrigir_texto")])
    keyboard.append([InlineKeyboardButton("❌ Descartar", callback_data="frev_descartar")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    msg_texto = item.get("copy", "")
    msg_texto += f"\n\n--- <i>Prévia Interna (Sem Link Encurtado)</i> ---\nLink: {item.get('link_cru', 'Sem link')}"

    chat_id = update.callback_query.message.chat_id if update.callback_query else update.effective_chat.id
    await enviar_com_midia(
        bot=context.bot,
        chat_id=chat_id,
        midia=item.get("midia", {}),
        texto=msg_texto,
        keyboard=reply_markup,
        parse_mode=ParseMode.HTML
    )

async def frev_aprovar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fila = context.user_data.get("fila_revisao", [])
    if not fila:
        return

    item = fila.pop(0)

    from bot.utils.config import TELEGRAM_CHANNEL_ID
    from bot.utils.channel_store import get_channels
    from bot.utils.telegram_utils import normalize_chat_id
    
    canais_destino = [TELEGRAM_CHANNEL_ID]
    for ch in get_channels():
        if ch not in canais_destino:
            canais_destino.append(ch)

    try:
        for chat_id in canais_destino:
            cid = normalize_chat_id(chat_id)
            await enviar_com_midia(context.bot, cid, item.get("midia", {}), item["copy"])
        await query.message.reply_text("✅ Oferta postada com sucesso!")
    except Exception as e:
        await query.message.reply_text(f"❌ Erro ao postar: {e}")

    await query.message.delete()
    context.user_data["fila_revisao"] = fila
    await show_next_review(update, context)

async def frev_descartar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    fila = context.user_data.get("fila_revisao", [])
    if fila:
        fila.pop(0)

    await query.message.delete()
    context.user_data["fila_revisao"] = fila
    await show_next_review(update, context)

async def frev_corrigir_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["estado_correcao"] = "link"
    await query.message.reply_text("🔗 Envie o link correto do produto para preencher automático:")

async def frev_corrigir_texto(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["estado_correcao"] = "texto"
    await query.message.reply_text("✍️ Envie a nova copy completa (inclua HTML, formatação, preços e o link):")

async def receive_correction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("estado_correcao"):
        return

    estado = context.user_data["estado_correcao"]
    texto = update.message.text
    if not texto: return

    fila = context.user_data.get("fila_revisao", [])
    if not fila:
        context.user_data["estado_correcao"] = None
        return

    if estado == "link":
        link_afiliado = await injetar_link_afiliado(texto)
        fila[0]["link_afiliado"] = link_afiliado
        fila[0]["link_cru"] = link_afiliado
        fila[0]["status"] = "ok"
        fila[0]["loja"] = _detectar_loja(link_afiliado)
        
        if fila[0].get("text_original"):
            titulo = fila[0]["nome_curto"]
            preco = fila[0]["preco"]
            fila[0]["copy"] = gerar_copy_encaminhamento(titulo, preco, "", link_afiliado)
        else:
            fila[0]["copy"] += f"\n\n👉 <a href='{link_afiliado}'>COMPRAR AQUI</a>"

    elif estado == "texto":
        fila[0]["copy"] = texto

    context.user_data["estado_correcao"] = None
    await update.message.reply_text("✅ Substituição concluída!")
    await show_next_review(update, context)
