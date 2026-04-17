"""
offer_by_link.py — Handler definitivo do botão "Publicar por Link".

Pipeline:
  1. Admin envia link (pode ser encurtado ou com redirecionamento).
  2. Bot resolve a URL final real.
  3. Injeta link de afiliado correto por loja.
  4. Extrai imagem, título e preço em camadas (Playwright → HTML → mínimo seguro).
  5. Gera nova copy de venda via IA.
  6. Envia prévia privada ao admin com botões [✅ Confirmar] [❌ Cancelar].
  7. Somente após confirmação, publica no canal.

Logs obrigatórios em cada etapa.
"""
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from bot.permissions import is_admin
from bot.utils.constants import CB_MENU_PRINCIPAL

logger = logging.getLogger(__name__)

# ── Estados da conversa ──────────────────────────────────────────────────────
LINK_PRODUTO           = 10
PREENCHER_NOME_FALTANTE = 11
PREENCHER_PRECO_FALTANTE = 12
LINK_AFILIADO          = 13
CONFIRMAR_LINK         = 14
EDITAR_CAMPOS          = 15

# Callbacks exclusivos deste fluxo
CB_CONFIRMAR_LINK     = "oferta_link_confirmar"
CB_CANCELAR_OFERTA    = "oferta_link_cancelar"

# ── Regex para extrair a primeira URL de um texto ────────────────────────────
_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


def _extrair_primeira_url(texto: str) -> str | None:
    match = _URL_RE.search(texto)
    return match.group(0).rstrip(".)],;") if match else None


# ── Gerador de copy ──────────────────────────────────────────────────────────

def _gerar_copy_basica(titulo: str, preco: str, link_afiliado: str, source_method: str = "") -> str:
    """
    Copia de venda simples em HTML.
    Usada se a IA falhar ou como base de prévia.
    """
    metodo_txt = f"\n\n<i>🔍 Extraído via {source_method}</i>" if source_method else ""
    return (
        f"🔥 <b>{titulo}</b>\n\n"
        f"💰 Por apenas <b>{preco}</b>\n\n"
        f"👉 <a href=\"{link_afiliado}\">Clique aqui para comprar</a>\n\n"
        f"⚡ <i>Oferta por tempo limitado. Corra!</i>"
        f"{metodo_txt}"
    )


# ============================================================================
# ENTRADA DO FLUXO
# ============================================================================

async def start_offer_by_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not is_admin(user.id):
        logger.warning(f"[OFERTA_LINK] ACESSO_NEGADO: user_id={user.id}")
        await query.edit_message_text("⛔ Você não tem permissão para publicar.")
        return ConversationHandler.END

    logger.info(f"[OFERTA_LINK] Admin {user.id} iniciou fluxo 'Publicar por Link'.")
    context.user_data.clear()

    await query.edit_message_text(
        "🔗 <b>Publicar por Link</b>\n\n"
        "Cole o link do produto abaixo:\n"
        "<i>Aceito links encurtados, de afiliado, amzn.to, bit.ly, etc.</i>",
        parse_mode=ParseMode.HTML,
    )
    return LINK_PRODUTO


# ============================================================================
# RECEBIMENTO E PROCESSAMENTO DO LINK
# ============================================================================

async def receber_link_produto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_text = update.message.text.strip()

    original_link = _extrair_primeira_url(raw_text)
    if not original_link:
        await update.message.reply_text(
            "❌ Não encontrei nenhum link válido. Envie um link completo (começando com https://)."
        )
        return LINK_PRODUTO

    logger.info(f"[OFERTA_LINK] LINK_RECEBIDO: {original_link}")

    # Guarda o texto extra como descrição base (se houver)
    if len(raw_text) > len(original_link) + 10:
        context.user_data["descricao_base"] = raw_text
    context.user_data["original_url"] = original_link

    msg_aguardo = await update.message.reply_text(
        "⏳ <b>Processando...</b>\n"
        "🔎 Resolvendo link → Injetando afiliado → Extraindo produto...\n"
        "<i>Aguarde alguns segundos.</i>",
        parse_mode=ParseMode.HTML
    )

    # ── 1. Extração de Produto e Resolução (Playwright) ──────────────────────
    logger.info(f"[OFERTA_LINK] EXTRACAO_INICIADA para: {original_link[:80]}")
    try:
        from bot.services.product_extractor_v2 import extract_product_data_v2
        dados = await extract_product_data_v2(original_link)
        final_url = dados.get("final_url", original_link)
    except Exception as e:
        logger.error(f"[OFERTA_LINK] Erro crítico na extração: {e}")
        final_url = original_link
        dados = {
            "titulo": "Produto", "preco": "Preço não disponível", "imagem": None,
            "preco_original": None, "source_method": "FALLBACK_SEM_PRECO", "erro": str(e),
        }
    
    # ── 2. Injeta afiliado (baseado na URL final real) ──────────────────────
    from bot.services.affiliate_link_service import injetar_link_afiliado, _detectar_loja
    store_key  = _detectar_loja(final_url)
    affiliate_url = injetar_link_afiliado(final_url, store_key)

    context.user_data["final_url"]     = final_url
    context.user_data["store_key"]     = store_key
    context.user_data["affiliate_url"] = affiliate_url

    logger.info(f"[OFERTA_LINK] LINK_AFILIADO_GERADO: {affiliate_url[:100]}")
    logger.info(
        f"[OFERTA_LINK] EXTRACAO_SUCESSO | METODO_USADO={dados.get('source_method')} | "
        f"titulo={dados.get('titulo', '')[:40]} | preco={dados.get('preco')}"
    )

    context.user_data["dados_produto"] = dados

    await msg_aguardo.delete()

    # ── 4. Pede dados faltantes ao admin ────────────────────────────────────
    if not dados.get("titulo") or dados["titulo"] == "Produto":
        await update.message.reply_text(
            "⚠️ Não consegui extrair o <b>nome</b> do produto automaticamente.\n\n"
            "Por favor, digite o nome do produto:",
            parse_mode=ParseMode.HTML
        )
        return PREENCHER_NOME_FALTANTE

    if not dados.get("preco") or dados["preco"] == "Preço não disponível":
        await update.message.reply_text(
            f"✅ Produto: <b>{dados['titulo'][:80]}</b>\n\n"
            "⚠️ Não consegui extrair o <b>preço</b> automaticamente.\n\n"
            "Por favor, digite o preço da promoção (ex: <code>R$ 49,90</code>):",
            parse_mode=ParseMode.HTML
        )
        return PREENCHER_PRECO_FALTANTE

    # Tudo extraído → gera prévia
    return await _gerar_e_enviar_previa(update, context)


# ============================================================================
# PREENCHIMENTO MANUAL DE DADOS FALTANTES
# ============================================================================

async def preencher_nome_faltante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome = update.message.text.strip()
    context.user_data["dados_produto"]["titulo"] = nome
    logger.info(f"[OFERTA_LINK] Nome preenchido manualmente: {nome[:60]}")

    dados = context.user_data["dados_produto"]
    if not dados.get("preco") or dados["preco"] == "Preço não disponível":
        await update.message.reply_text(
            "📝 Agora, qual é o <b>preço</b> da promoção? (ex: <code>R$ 49,90</code>)",
            parse_mode=ParseMode.HTML
        )
        return PREENCHER_PRECO_FALTANTE

    return await _gerar_e_enviar_previa(update, context)


async def preencher_preco_faltante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    preco = update.message.text.strip()
    context.user_data["dados_produto"]["preco"] = preco
    logger.info(f"[OFERTA_LINK] Preço preenchido manualmente: {preco}")
    return await _gerar_e_enviar_previa(update, context)


# ============================================================================
# RECEBIMENTO DE LINK DE AFILIADO MANUAL (opcional)
# ============================================================================

async def receber_link_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link_manual = update.message.text.strip()
    if link_manual.startswith("http"):
        context.user_data["affiliate_url"] = link_manual
        logger.info(f"[OFERTA_LINK] Link de afiliado manual recebido: {link_manual[:80]}")
    return await _gerar_e_enviar_previa(update, context)


async def pular_link_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("[OFERTA_LINK] Admin pulou o link afiliado manual. Usando automático.")
    return await _gerar_e_enviar_previa(update, context)


# ============================================================================
# GERAÇÃO DE PRÉVIA
# ============================================================================

async def _gerar_e_enviar_previa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dados        = context.user_data["dados_produto"]
    affiliate_url = context.user_data.get("affiliate_url", context.user_data.get("final_url", ""))
    store_key    = context.user_data.get("store_key", "other")
    source_method = dados.get("source_method", "—")

    titulo        = dados.get("titulo", "Produto")
    preco         = dados.get("preco", "Preço não disponível")
    preco_original= dados.get("preco_original")
    imagem        = dados.get("imagem")

    # ── Encurtamento do link afiliado ────────────────────────────────────────
    try:
        from bot.services.link_shortener import shorten_for_publication
        import asyncio
        short_url = await asyncio.to_thread(shorten_for_publication, affiliate_url)
        logger.info(f"[OFERTA_LINK] Link encurtado: {short_url}")
    except Exception as e:
        short_url = affiliate_url
        logger.warning(f"[OFERTA_LINK] Encurtador falhou ({e}). Usando link longo.")

    context.user_data["short_url"] = short_url

    # ── Geração de copy via IA ───────────────────────────────────────────────
    msg_ia = await update.message.reply_text("⏳ Gerando copy de venda com IA...")
    try:
        from bot.services.ai_writer import generate_caption
        copy_ia = await generate_caption(
            nome     = titulo,
            preco    = preco,
            loja     = dados.get("store", "Loja"),
            descricao= context.user_data.get("descricao_base"),
            preco_original = preco_original,
        )
    except Exception as e:
        logger.warning(f"[OFERTA_LINK] IA falhou ao gerar copy: {e}. Usando fallback.")
        copy_ia = None
    await msg_ia.delete()

    # ── Monta o texto do canal (HTML seguro) ─────────────────────────────────
    try:
        from bot.services.copy_builder import build_copy
        copies = build_copy(
            nome          = titulo,
            preco         = preco,
            loja          = dados.get("store", "Loja"),
            store_key     = store_key,
            short_url     = short_url,
            legenda_ia    = copy_ia,
            preco_original= preco_original,
        )
        copy_canal = copies.get("telegram", "")
    except Exception as e:
        logger.warning(f"[OFERTA_LINK] build_copy falhou ({e}). Usando copy básica.")
        copy_canal = _gerar_copy_basica(titulo, preco, short_url, source_method)
        copies = {"telegram": copy_canal, "whatsapp": copy_canal}

    context.user_data["copies"]    = copies
    context.user_data["copy_canal"] = copy_canal

    # ── Monta a mensagem de PRÉVIA para o admin ──────────────────────────────
    # Bloco de preço: mostra "De X por Y" se hover preço original
    if preco_original and preco_original != preco:
        preco_display = f"💰 <b>De <s>{preco_original}</s> por {preco}</b>"
    else:
        preco_display = f"💰 <b>{preco}</b>"

    preview_text = (
        f"🔍 <b>PRÉVIA — Confirme antes de publicar</b>\n\n"
        f"🏷️ <b>{titulo}</b>\n"
        f"{preco_display}\n"
        f"🏪 Loja: <b>{dados.get('store', store_key)}</b>\n"
        f"📡 Método: <i>{source_method}</i>\n\n"
        f"🔗 <b>Link de afiliado:</b>\n"
        f"<code>{affiliate_url}</code>\n\n"
        f"🔗 <b>Link encurtado:</b> <code>{short_url}</code>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"<b>Texto que será publicado no canal:</b>\n\n"
        f"{copy_canal}"
    )

    # Limita tamanho da prévia (Telegram tem limite de 4096 chars)
    if len(preview_text) > 4000:
        preview_text = preview_text[:3900] + "\n\n<i>... (texto truncado na prévia)</i>"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirmar e Publicar", callback_data=CB_CONFIRMAR_LINK),
            InlineKeyboardButton("❌ Cancelar",             callback_data=CB_CANCELAR_OFERTA),
        ],
        [InlineKeyboardButton("✏️ Corrigir dados",    callback_data="editar_oferta")],
        [InlineKeyboardButton("⬅️ Voltar ao Menu",    callback_data=CB_MENU_PRINCIPAL)],
    ])

    logger.info(f"[OFERTA_LINK] PREVIEW_ENVIADA | imagem={'sim' if imagem else 'não'}")

    # Envia prévia com ou sem imagem
    try:
        if imagem:
            await update.message.reply_photo(
                photo=imagem,
                caption=preview_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await update.message.reply_text(
                preview_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error(f"[OFERTA_LINK] Erro ao enviar prévia: {e}")
        # Fallback sem HTML
        await update.message.reply_text(
            f"⚠️ Prévia com erro de renderização.\n\nTítulo: {titulo}\nPreço: {preco}\nLink: {short_url}",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    return CONFIRMAR_LINK


# ============================================================================
# CONFIRMAÇÃO / CANCELAMENTO
# ============================================================================

async def confirmar_envio_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)
    ]])

    if query.data == CB_CANCELAR_OFERTA:
        await query.answer("❌ Publicação cancelada.")
        logger.info(f"[OFERTA_LINK] PUBLICACAO_CANCELADA por admin {query.from_user.id}.")
        context.user_data.clear()
        try:
            await query.edit_message_text("❌ Oferta cancelada.", reply_markup=back_keyboard)
        except Exception:
            await query.message.reply_text("❌ Oferta cancelada.", reply_markup=back_keyboard)
        return ConversationHandler.END

    if query.data != CB_CONFIRMAR_LINK:
        await query.answer()
        return CONFIRMAR_LINK

    await query.answer("📤 Publicando no canal...")
    logger.info(f"[OFERTA_LINK] PUBLICACAO_CONFIRMADA por admin {query.from_user.id}.")

    copies  = context.user_data.get("copies", {})
    img_url = context.user_data.get("dados_produto", {}).get("imagem")

    try:
        from bot.services.publisher_router import publish_offer
        await publish_offer(query.bot, copies, img_url)

        msg_sucesso = "🎉 <b>Oferta publicada no canal com sucesso!</b>"
        try:
            if img_url:
                await query.message.delete()
                await query.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=msg_sucesso,
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard,
                )
            else:
                await query.edit_message_text(
                    msg_sucesso,
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard,
                )
        except Exception:
            pass

    except Exception as e:
        logger.error(f"[OFERTA_LINK] Erro ao publicar: {e}")
        await query.bot.send_message(
            chat_id=query.message.chat_id,
            text=f"❌ Erro ao publicar no canal: <code>{e}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard,
        )

    context.user_data.clear()
    return ConversationHandler.END


# ============================================================================
# EDIÇÃO DE CAMPOS
# ============================================================================

async def btn_editar_oferta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    keyboard = [
        [
            InlineKeyboardButton("🏷️ Nome",          callback_data="edit_nome"),
            InlineKeyboardButton("💰 Preço",          callback_data="edit_preco"),
        ],
        [InlineKeyboardButton("📝 Copy/Legenda",      callback_data="edit_copy")],
        [InlineKeyboardButton("⬅️ Cancelar Edição",  callback_data="cancel_edit")],
    ]
    await query.edit_message_text(
        "🛠️ <b>O que deseja corrigir?</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return EDITAR_CAMPOS


async def escolher_campo_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel_edit":
        return await _gerar_e_enviar_previa(update, context)

    campo = query.data.replace("edit_", "")
    context.user_data["edit_campo"] = campo

    msgs = {
        "nome":  "Digite o novo <b>nome</b> do produto:",
        "preco": "Digite o novo <b>preço</b> (ex: <code>R$ 99,90</code>):",
        "copy":  "Digite a nova <b>copy/legenda</b>:",
    }
    await query.edit_message_text(
        f"✍️ {msgs.get(campo, 'Digite o novo valor:')}",
        parse_mode=ParseMode.HTML,
    )
    return EDITAR_CAMPOS


async def salvar_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    novo_valor = update.message.text.strip()
    campo = context.user_data.get("edit_campo")

    if campo == "nome":
        context.user_data["dados_produto"]["titulo"] = novo_valor
    elif campo == "preco":
        context.user_data["dados_produto"]["preco"] = novo_valor
    elif campo == "copy":
        # Substitui a copy diretamente nas copies salvas
        if "copies" in context.user_data:
            context.user_data["copies"]["telegram"] = novo_valor
            context.user_data["copies"]["whatsapp"] = novo_valor

    await update.message.reply_text(f"✅ Campo <b>{campo}</b> atualizado!", parse_mode=ParseMode.HTML)
    return await _gerar_e_enviar_previa(update, context)
