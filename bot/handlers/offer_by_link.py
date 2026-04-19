"""
offer_by_link.py — Handler definitivo do botão "Publicar por Link".

Máquina de Estados:
  LINK_PRODUTO             → Admin envia o link
  PREENCHER_NOME_FALTANTE  → Bot pede nome (se extração falhou)
  PREENCHER_PRECO_FALTANTE → Bot pede preço (se extração falhou)
  AGUARDAR_CUPOM           → Bot pergunta sobre cupom (NOVO)
  CONFIRMAR_LINK           → Prévia exibida com botões Confirmar/Corrigir/Cancelar
  EDITAR_CAMPOS            → Submenu de edição (Preço/Copy/Link/Cupom/Voltar)
  AGUARDAR_EDICAO_TEXTO    → Bot aguarda texto do campo a corrigir (NOVO)

Regras críticas:
  - Na PRÉVIA: link de afiliado exibido CRUE (sem encurtamento) para verificação da tag.
  - Encurtamento SOMENTE em confirmar_envio_link(), na hora de publicar.
  - Preço PIX (is_pix_price=True) gera copy com "💰 Por apenas X no PIX".
  - Se cupom informado: copy recebe linha "🎟️ Use o cupom: <b>CODIGO</b>".
  - Todos os callbacks respondem com query.answer() antes de qualquer operação.
"""
import logging
import re

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode
from bot.services.product_extractor_v2 import extract_product_data_v2

from bot.permissions import is_admin
from bot.utils.constants import (
    CB_MENU_PRINCIPAL, CB_PUBLICAR_LINK, CB_CANCELAR_OFERTA
)

# Adicionamos aqui a constante local caso não esteja no constants.py
CB_CONFIRMAR_LINK = "confirmar_envio_link"

logger = logging.getLogger(__name__)

# ── Estados da conversa ──────────────────────────────────────────────────────
LINK_PRODUTO             = 10
PREENCHER_NOME_FALTANTE  = 11
PREENCHER_PRECO_FALTANTE = 12
LINK_AFILIADO            = 13   # mantido para compatibilidade de fallback
CONFIRMAR_LINK           = 14
EDITAR_CAMPOS            = 15
AGUARDAR_CUPOM           = 16   # NOVO
AGUARDAR_EDICAO_TEXTO    = 17   # NOVO

# ── Callbacks exclusivos deste fluxo ────────────────────────────────────────
CB_CONFIRMAR_LINK       = "oferta_link_confirmar"
CB_CANCELAR_OFERTA_LINK = "oferta_link_cancelar"
CB_SEM_CUPOM            = "sem_cupom"
CB_EDIT_PRECO      = "edit_preco"
CB_EDIT_COPY       = "edit_copy"
CB_EDIT_LINK       = "edit_link"
CB_EDIT_CUPOM      = "edit_cupom"
CB_VOLTAR_PREVIA   = "voltar_previa"

# ── Regex para extrair a primeira URL de um texto ────────────────────────────
_URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _parse_fallback_text(raw_text: str, url: str) -> dict:
    """
    Extrator de salva-vidas: tenta encontrar Título e Preço 
    no texto cru colado pelo admin (útil para compartilhamentos de Apps).
    """
    fallback_data = {"titulo": None, "preco": None}
    
    # 1. Tentar achar o título: 
    # as primeiras linhas que não são URLs nem o nome genérico da loja
    linhas = [linha.strip() for linha in raw_text.split('\n') if linha.strip()]
    candidatos_titulo = []
    lojas_ignoradas = ["amazon", "mercado livre", "magalu", "shopee", "netshoes"]
    
    for linha in linhas:
        if url in linha or linha.startswith("http"):
            continue
        if linha.lower() in lojas_ignoradas:
            continue
        if len(linha) > 5:
            candidatos_titulo.append(linha)
            
    if candidatos_titulo:
        # A primeira linha substancial costuma ser o título do produto
        fallback_data["titulo"] = candidatos_titulo[0]
        
    # 2. Tentar achar o preço com um Regex agressivo
    match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", raw_text)
    if match:
        fallback_data["preco"] = f"R$ {match.group(1)}"
        
    return fallback_data


def _extrair_primeira_url(texto: str) -> str | None:
    match = _URL_RE.search(texto)
    return match.group(0).rstrip(".)],;") if match else None

# ── Comando de Diagnóstico (Debug) ──────────────────────────────────────────

async def cmd_debug_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Comando /debug_link [URL] para investigar falhas de extração."""
    if not is_admin(update.effective_user.id):
        return

    logger.info(f"[DEBUG] Comando /debug_link acionado por {update.effective_user.id}")

    msg_text = update.effective_message.text or ""
    url = _extrair_primeira_url(msg_text)

    if not url:
        await update.message.reply_text("❌ Uso: /debug_link [URL]")
        return

    wait_msg = await update.message.reply_text(f"🔍 Iniciando diagnóstico de extração...\nURL: <code>{url}</code>", parse_mode=ParseMode.HTML)

    try:
        data = await extract_product_data_v2(url)
        
        report = (
            f"📊 <b>DIAGNÓSTICO TÉCNICO V5</b>\n\n"
            f"🏷️ <b>Título:</b> {data.get('titulo', 'N/A')}\n"
            f"💰 <b>Preço:</b> {data.get('preco', 'N/A')}\n"
            f"🏪 <b>Loja:</b> {data.get('store')} ({data.get('store_key')})\n"
            f"⚙️ <b>Método:</b> {data.get('source_method')}\n"
            f"🐞 <b>Debug:</b> <code>{data.get('debug_info', 'N/A')}</code>\n\n"
            f"🔗 <b>Encontrado em:</b>\n<code>{data.get('final_url', 'N/A')}</code>"
        )
        await wait_msg.edit_text(report, parse_mode=ParseMode.HTML)
    except Exception as e:
        await wait_msg.edit_text(f"🔴 <b>ERRO NO DEBUGGER:</b>\n<code>{str(e)}</code>", parse_mode=ParseMode.HTML)


def _escape_html(text: str) -> str:
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _gerar_copy_basica(
    titulo: str,
    preco: str,
    link: str,
    source_method: str = "",
    cupom: str | None = None,
    is_pix: bool = False,
) -> str:
    """Cópia de venda simples em HTML — usada como fallback se build_copy falhar."""
    
    preco_linha = (
        f"💰 Por apenas <b>{_escape_html(preco)} no PIX</b>"
        if is_pix
        else f"💰 Por apenas <b>{_escape_html(preco)}</b>"
    )

    cupom_linha = (
        f"\n🎟️ Use o cupom: <b>{_escape_html(cupom)}</b>"
        if cupom else ""
    )

    return (
        f"🔥 <b>{_escape_html(titulo)}</b>\n\n"
        f"{preco_linha}\n"
        f"{cupom_linha}\n\n"
        f"👉 <a href=\"{link}\">Clique aqui para comprar</a>\n\n"
        f"⚡ <i>Oferta por tempo limitado. Corra!</i>"
    )


def _build_previa_keyboard(show_ai_button: bool = False) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🚀 CONFIRMAR E PUBLICAR AGORA", callback_data=CB_CONFIRMAR_LINK)],
    ]
    
    if show_ai_button:
        buttons.append([InlineKeyboardButton("✨ REGERAR LEGENDA IA", callback_data="regen_ia")])
        
    buttons.append([
        InlineKeyboardButton("✏️ CORRIGIR DADOS", callback_data="editar_oferta"),
        InlineKeyboardButton("🗑️ DESCARTAR",  callback_data=CB_CANCELAR_OFERTA_LINK),
    ])
    return InlineKeyboardMarkup(buttons)


# ============================================================================
# NÚCLEO: _send_previa — exibe a prévia a partir de qualquer message object
# ============================================================================

async def _send_previa(message, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Envia a prévia para o admin.

    'message' é qualquer objeto telegram.Message (de update.message OU
    query.message) para que possamos usar reply_text / reply_photo.

    IMPORTANTE:
      - O link de afiliado é exibido CRUE (sem encurtar) para o admin
        verificar se sua tag está presente.
      - Encurtamento ocorre SOMENTE em confirmar_envio_link().
    """
    dados         = context.user_data.get("dados_produto", {})
    affiliate_url = context.user_data.get("affiliate_url") or context.user_data.get("final_url", "")
    store_key     = context.user_data.get("store_key", "other")
    cupom         = context.user_data.get("cupom")
    source_method = dados.get("source_method", "—")
    is_pix        = dados.get("is_pix_price", False)

    titulo         = dados.get("titulo", "Produto")
    preco          = dados.get("preco", "Preço não disponível")
    preco_original = dados.get("preco_original")
    imagem         = dados.get("imagem")

    # ── IA Copy ──────────────────────────────────────────────────────────────
    copy_ia = None
    try:
        from bot.services.ai_writer import generate_caption
        copy_ia = await generate_caption(
            nome          = titulo,
            preco         = preco,
            loja          = dados.get("store", "Loja"),
            descricao     = context.user_data.get("descricao_base"),
            preco_original= preco_original,
        )
    except Exception as e:
        logger.warning(f"[OFERTA_LINK] IA falhou ao gerar copy: {e}")

    # ── Monta a copy (usa link CRUE na prévia) ────────────────────────────────
    # Se o admin sobrescreveu a copy manualmente, respeita isso.
    copy_override = context.user_data.get("copy_override")

    if copy_override:
        copy_canal = copy_override
        copies = {"telegram": copy_canal, "whatsapp": copy_canal}
    else:
        try:
            from bot.services.copy_builder import build_copy
            copies = build_copy(
                nome          = titulo,
                preco         = preco,
                loja          = dados.get("store", "Loja"),
                store_key     = store_key,
                short_url     = affiliate_url,   # link CRUE para a prévia
                legenda_ia    = copy_ia,
                preco_original= preco_original,
            )
            copy_canal = copies.get("telegram", "")

            # Ajusta preço PIX na copy
            if is_pix:
                copy_canal = copy_canal.replace(
                    "💰 <b>Preço:</b>",
                    "💰 <b>Preço no PIX:</b>",
                )

            # Acrescenta cupom
            if cupom:
                copy_canal += f"\n\n🎟️ Use o cupom: <b>{_escape_html(cupom)}</b>"

            # Acrescenta cupom na versão WhatsApp também
            wa_copy = copies.get("whatsapp", "")
            if is_pix:
                wa_copy = wa_copy.replace(f"💰 *{preco}*", f"💰 *{preco} no PIX* 💳")
            if cupom:
                wa_copy += f"\n\n🎟️ Cupom: *{cupom}*"

            copies["telegram"] = copy_canal
            copies["whatsapp"] = wa_copy

        except Exception as e:
            logger.warning(f"[OFERTA_LINK] build_copy falhou ({e}). Usando copy básica.")
            copy_canal = _gerar_copy_basica(
                titulo, preco, affiliate_url, source_method, cupom, is_pix
            )
            copies = {"telegram": copy_canal, "whatsapp": copy_canal}

    context.user_data["copies"]    = copies
    context.user_data["copy_canal"] = copy_canal

    # ── Monta a mensagem de PRÉVIA ────────────────────────────────────────────
    if preco_original and preco_original != preco:
        preco_display = (
            f"💰 <b>De <s>{_escape_html(preco_original)}</s> "
            f"por {_escape_html(preco)}</b>"
        )
    elif is_pix:
        preco_display = f"💰 <b>{_escape_html(preco)} no PIX</b> 💳"
    else:
        preco_display = f"💰 <b>{_escape_html(preco)}</b>"

    cupom_linha = (
        f"🎟️ Cupom: <code>{_escape_html(cupom)}</code>\n"
        if cupom else ""
    )

    preview_text = (
        "💎 <b>PRÉVIA — Confirme antes de publicar</b>\n\n"
        f"🏷️ <b>{_escape_html(titulo)}</b>\n"
        f"{preco_display}\n"
        f"{cupom_linha}"
        f"🏪 Loja: <b>{_escape_html(dados.get('store', store_key))}</b>\n"
        f"📡 Método: <i>{_escape_html(source_method)}</i>\n\n"
        "🔗 <b>Link de afiliado (CRUE — verifique sua tag!):</b>\n"
        f"<code>{_escape_html(affiliate_url)}</code>\n\n"
        "━━━━━━━━━━━━━━━\n"
        "<b>Texto que será publicado no canal:</b>\n\n"
        f"{copy_canal}"
    )

    # Telegram: caption ≤ 1024, texto ≤ 4096
    limite = 900 if imagem else 3500
    if len(preview_text) > limite:
        # Busca o último espaço antes do limite para não quebrar uma TAG ou palavra no meio
        split_idx = preview_text.rfind(" ", 0, limite)
        if split_idx == -1: split_idx = limite
        preview_text = preview_text[:split_idx] + "\n\n<i>... (texto truncado)</i>"
        # Garante que não deixamos tags abertas (simplificado)
        if "<b>" in preview_text and "</b>" not in preview_text: preview_text += "</b>"
        if "<i>" in preview_text and "</i>" not in preview_text: preview_text += "</i>"
        if "<code>" in preview_text and "</code>" not in preview_text: preview_text += "</code>"

    from bot.utils.config import OPENAI_API_KEY
    keyboard = _build_previa_keyboard(show_ai_button=bool(OPENAI_API_KEY))

    logger.info(
        f"[OFERTA_LINK] PREVIEW_ENVIADA | imagem={'sim' if imagem else 'não'} "
        f"| pix={is_pix} | cupom={bool(cupom)}"
    )

    try:
        if imagem:
            await message.reply_photo(
                photo=imagem,
                caption=preview_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await message.reply_text(
                preview_text,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.error(f"[OFERTA_LINK] Erro ao enviar prévia: {e}")
        await message.reply_text(
            f"⚠️ Erro ao renderizar prévia.\n\n"
            f"Título: {titulo}\nPreço: {preco}\n"
            f"Link: {affiliate_url[:100]}",
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )

    return CONFIRMAR_LINK


# ── Alias para compatibilidade (recebe update convencional) ──────────────────
async def _gerar_e_enviar_previa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await _send_previa(update.message, context)


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
        "<i>Aceito links encurtados (amzn.to, shope.ee, bit.ly, etc.).</i>",
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
            "❌ Não encontrei nenhum link válido. Envie um link começando com https://."
        )
        return LINK_PRODUTO

    logger.info(f"[OFERTA_LINK] LINK_RECEBIDO: {original_link}")

    if len(raw_text) > len(original_link) + 10:
        context.user_data["descricao_base"] = raw_text
    context.user_data["original_url"] = original_link

    msg_aguardo = await update.message.reply_text(
        "⏳ <b>Processando...</b>\n"
        "🔎 Resolvendo link → Injetando afiliado → Extraindo produto...\n"
        "<i>Aguarde, isso pode levar até 1 minuto para garantir a melhor extração.</i>",
        parse_mode=ParseMode.HTML,
    )

    # ── 1. Resolução forçada de links curtos via Playwright (se necessário) ──
    final_url = original_link
    if "amzn.to" in original_link or "shope.ee" in original_link:
        try:
            await msg_aguardo.edit_text(
                "⏳ <b>Processando...</b>\n"
                "✅ Link recebido\n"
                "📡 <b>Resolvendo link encurtado...</b>",
                parse_mode=ParseMode.HTML
            )
            from bot.services.affiliate_link_service import resolve_url_playwright
            logger.info(f"[OFERTA_LINK] Resolvendo shortener via Playwright: {original_link}")
            final_url = await resolve_url_playwright(original_link)
        except Exception as e:
            logger.warning(f"[OFERTA_LINK] Playwright falhou ao resolver: {e}")

    # ── 2. Extração + resolução adicional ────────────────────────────────────
    await msg_aguardo.edit_text(
        "⏳ <b>Processando...</b>\n"
        "✅ Link resolvido\n"
        "🛍️ <b>Extraindo informações (Híbrido ScraperAPI + PW)...</b>",
        parse_mode=ParseMode.HTML
    )
    logger.info(f"[OFERTA_LINK] EXTRACAO_INICIADA: {final_url[:80]}")
    try:
        from bot.services.product_extractor_v2 import extract_product_data_v2
        dados = await extract_product_data_v2(final_url)
        final_url = dados.get("final_url", final_url)
    except Exception as e:
        logger.error(f"[OFERTA_LINK] Erro crítico na extração: {e}")
        dados = {
            "titulo": "Produto", "preco": "Preço não disponível", "imagem": None,
            "preco_original": None, "source_method": "FALLBACK_SEM_PRECO",
            "erro": str(e), "is_pix_price": False,
        }

    # ── 2. Injeta afiliado na URL final (sem sobrescrever depois) ────────────
    await msg_aguardo.edit_text(
        "⏳ <b>Processando...</b>\n"
        "✅ Dados extraídos\n"
        "⚙️ <b>Configurando links de afiliado...</b>",
        parse_mode=ParseMode.HTML
    )
    from bot.services.affiliate_link_service import injetar_link_afiliado, _detectar_loja

    store_key     = _detectar_loja(final_url)
    affiliate_url = await injetar_link_afiliado(final_url, store_key)

    logger.info(f"[OFERTA_LINK] AFFILIATE_URL_READY: {affiliate_url[:120]}")

    context.user_data["final_url"]     = final_url
    context.user_data["store_key"]     = store_key
    context.user_data["affiliate_url"] = affiliate_url
    context.user_data["dados_produto"] = dados

    # ── TENTATIVA DE SALVA-VIDAS VIA TEXTO DO USUÁRIO ───────────────────────
    # Se a extração falhou mas o admin mandou o nome junto com o link, usamos o da mensagem!
    fallback_dados = _parse_fallback_text(raw_text, original_link)

    if not dados.get("titulo") or dados["titulo"] == "Produto":
        if fallback_dados["titulo"]:
            dados["titulo"] = fallback_dados["titulo"]
            logger.info(f"[OFERTA_LINK] Fallback texto salvo a vida para TITULO: {dados['titulo'][:40]}")

    if not dados.get("preco") or dados["preco"] == "Preço não disponível":
        if fallback_dados["preco"]:
            dados["preco"] = fallback_dados["preco"]
            logger.info(f"[OFERTA_LINK] Fallback texto salvo a vida para PRECO: {dados['preco']}")

    try:
        await msg_aguardo.delete()
    except Exception:
        pass

    # ── 3. Dados faltantes → pede ao admin ───────────────────────────────────
    if not dados.get("titulo") or dados["titulo"] == "Produto":
        await update.message.reply_text(
            "<b>🔍 NOME DO PRODUTO</b>\n\n"
            "⚠️ Não conseguimos identificar o nome automaticamente.\n"
            "📢 <b>Por favor, digite o nome completo do produto:</b>",
            parse_mode=ParseMode.HTML,
        )
        return PREENCHER_NOME_FALTANTE

    if not dados.get("preco") or dados["preco"] == "Preço não disponível":
        await update.message.reply_text(
            f"📦 Produto: <b>{_escape_html(dados['titulo'][:80])}</b>\n\n"
            "<b>💰 PREÇO DA OFERTA</b>\n"
            "⚠️ O preço não foi detectado.\n"
            "💵 <b>Digite o valor da promoção (ex: 49,90):</b>",
            parse_mode=ParseMode.HTML,
        )
        return PREENCHER_PRECO_FALTANTE

    # Dados completos → pergunta sobre cupom
    return await _perguntar_cupom(update, context)


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
            parse_mode=ParseMode.HTML,
        )
        return PREENCHER_PRECO_FALTANTE

    return await _perguntar_cupom(update, context)


async def preencher_preco_faltante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    preco = update.message.text.strip()
    context.user_data["dados_produto"]["preco"] = preco
    logger.info(f"[OFERTA_LINK] Preço preenchido manualmente: {preco}")
    return await _perguntar_cupom(update, context)


# ============================================================================
# CUPOM DE DESCONTO  ←  NOVO
# ============================================================================

async def _perguntar_cupom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Pergunta se a oferta possui cupom antes de gerar a prévia."""
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Sem Cupom", callback_data=CB_SEM_CUPOM),
    ]])
    await update.message.reply_text(
        "🎟️ <b>Essa oferta possui cupom de desconto?</b>\n\n"
        "👉 Digite o código do cupom abaixo, ou clique em <b>Sem Cupom</b>.\n"
        "<i>Exemplo: PROMO30, DESCONTO10, BLACKFRIDAY…</i>",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    return AGUARDAR_CUPOM


async def receber_cupom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin digitou o código do cupom."""
    cupom = update.message.text.strip().upper()
    context.user_data["cupom"] = cupom
    logger.info(f"[OFERTA_LINK] Cupom recebido: {cupom}")
    await update.message.reply_text(
        f"✅ Cupom <b>{_escape_html(cupom)}</b> registrado! Gerando prévia...",
        parse_mode=ParseMode.HTML,
    )
    return await _gerar_e_enviar_previa(update, context)


async def btn_sem_cupom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicou em ❌ Sem Cupom."""
    query = update.callback_query
    await query.answer("Sem cupom. Gerando prévia...")
    context.user_data["cupom"] = None
    logger.info("[OFERTA_LINK] Admin optou por 'Sem Cupom'.")
    # query.message é a mensagem que tinha o botão — usamos como base do reply
    return await _send_previa(query.message, context)


# ============================================================================
# LINK AFILIADO MANUAL (mantido por compatibilidade)
# ============================================================================

async def receber_link_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    link_manual = update.message.text.strip()
    if link_manual.startswith("http"):
        context.user_data["affiliate_url"] = link_manual
        logger.info(f"[OFERTA_LINK] Link afiliado manual: {link_manual[:80]}")
    return await _gerar_e_enviar_previa(update, context)


async def pular_link_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    logger.info("[OFERTA_LINK] Admin pulou link afiliado manual.")
    return await _gerar_e_enviar_previa(update, context)


# ============================================================================
# CONFIRMAÇÃO / CANCELAMENTO
# ============================================================================

async def confirmar_envio_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL),
    ]])

    # ── Cancelamento ────────────────────────────────────────────────────────
    if query.data == CB_CANCELAR_OFERTA_LINK:
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

    # ── Publicação ──────────────────────────────────────────────────────────
    await query.answer("🚀 Publicando...")
    logger.info(f"[OFERTA_LINK] PUBLICACAO_INICIADA por admin {query.from_user.id}.")

    copies        = context.user_data.get("copies")
    img_url       = context.user_data.get("dados_produto", {}).get("imagem")
    affiliate_url = context.user_data.get("affiliate_url", "")
    cupom         = context.user_data.get("cupom")
    is_pix        = context.user_data.get("dados_produto", {}).get("is_pix_price", False)
    dados         = context.user_data.get("dados_produto", {})

    if not copies:
        logger.error("[OFERTA_LINK] 'copies' ausente no user_data.")
        await query.answer("❌ Dados da oferta perdidos. Recomece o fluxo.", show_alert=True)
        return ConversationHandler.END

    try:
        # ── Encurtamento AQUI — apenas na publicação final ───────────────────
        short_url = affiliate_url
        try:
            from bot.services.link_shortener import shorten_for_publication
            import asyncio
            short_url = await asyncio.to_thread(shorten_for_publication, affiliate_url)
            logger.info(f"[OFERTA_LINK] Link encurtado: {short_url}")
        except Exception as e:
            logger.warning(f"[OFERTA_LINK] Encurtador falhou ({e}). Usando link longo.")

        # ── Reconstrói a copy com o link ENCURTADO para o canal ─────────────
        titulo    = dados.get("titulo", "Produto")
        preco     = dados.get("preco", "")
        preco_ori = dados.get("preco_original")
        store_key = context.user_data.get("store_key", "other")

        try:
            from bot.services.copy_builder import build_copy
            from bot.services.ai_writer import generate_caption
            
            try:
                copy_ia = await generate_caption(
                    nome=titulo, preco=preco, loja=dados.get("store", "Loja"),
                    preco_original=preco_ori,
                )
            except Exception:
                copy_ia = None

            copies_final = build_copy(
                nome          = titulo,
                preco         = preco,
                loja          = dados.get("store", "Loja"),
                store_key     = store_key,
                short_url     = short_url,
                legenda_ia    = copy_ia,
                preco_original= preco_ori,
            )
            # Aplica PIX e cupom na copy final
            tg = copies_final.get("telegram", "")
            if is_pix:
                tg = tg.replace("💰 <b>Preço:</b>", "💰 <b>Preço no PIX:</b>")
            if cupom:
                tg += f"\n\n🎟️ Use o cupom: <b>{_escape_html(cupom)}</b>"

            wa = copies_final.get("whatsapp", "")
            if is_pix:
                wa = wa.replace(f"💰 *{preco}*", f"💰 *{preco} no PIX* 💳")
            if cupom:
                wa += f"\n\n🎟️ Cupom: *{cupom}*"

            copies_final["telegram"] = tg
            copies_final["whatsapp"] = wa

        except Exception as e:
            logger.warning(f"[OFERTA_LINK] Rebuild copy falhou ({e}). Substituindo link nas copies salvas.")
            copies_final = dict(copies)
            if isinstance(copies_final.get("telegram"), str):
                copies_final["telegram"] = copies_final["telegram"].replace(affiliate_url, short_url)
            if isinstance(copies_final.get("whatsapp"), str):
                copies_final["whatsapp"] = copies_final["whatsapp"].replace(affiliate_url, short_url)

        # ── Publica no canal ────────────────────────────────────────────────
        from bot.services.publisher_router import publish_offer
        logger.info(f"[OFERTA_LINK] Chamando publish_offer (imagem={'sim' if img_url else 'não'})...")
        await publish_offer(context.bot, copies_final, img_url)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔗 Publicar Outro Link", callback_data=CB_PUBLICAR_LINK)],
            [InlineKeyboardButton("🏠 Menu Principal", callback_data=CB_MENU_PRINCIPAL)],
        ])

        msg_sucesso = "✅ <b>Oferta enviada com sucesso ao canal!</b>"
        await query.message.reply_text(
            msg_sucesso,
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard,
        )
        try:
            await query.message.delete()
        except:
            pass

    except Exception as e:
        logger.error(f"[OFERTA_LINK] Erro ao publicar: {e}")
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Erro ao publicar no canal:\n\n<code>{_escape_html(str(e))}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=back_keyboard,
            )
        except Exception as fallback_err:
            logger.error(f"[OFERTA_LINK] Falha dupla ao enviar erro: {fallback_err}")

    context.user_data.clear()
    return ConversationHandler.END


# ============================================================================
# MENU "CORRIGIR"  ←  IMPLEMENTADO DE VERDADE
# ============================================================================

async def btn_editar_oferta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Exibe o submenu de edição quando admin clica em ✏️ Corrigir.
    Responde o query e edita a mensagem com os botões de campo.
    """
    query = update.callback_query
    await query.answer()

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Preço",  callback_data=CB_EDIT_PRECO),
            InlineKeyboardButton("📝 Copy",   callback_data=CB_EDIT_COPY),
        ],
        [
            InlineKeyboardButton("🔗 Link",   callback_data=CB_EDIT_LINK),
            InlineKeyboardButton("🎟️ Cupom",  callback_data=CB_EDIT_CUPOM),
        ],
        [InlineKeyboardButton("⬅️ Voltar pra Prévia", callback_data=CB_VOLTAR_PREVIA)],
    ])
    await query.edit_message_text(
        "🛠️ <b>O que você deseja corrigir?</b>\n\n"
        "Escolha o campo e envie o novo valor em seguida:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )
    return EDITAR_CAMPOS


async def escolher_campo_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Processa os botões do submenu de edição.
    Edita a mensagem pedindo o novo valor e muda para AGUARDAR_EDICAO_TEXTO.
    """
    query = update.callback_query
    await query.answer()

    campo = query.data
    context.user_data["edit_campo"] = campo

    prompts = {
        CB_EDIT_PRECO: (
            "💰 <b>Digite o novo preço:</b>\n\n"
            "<i>Exemplo: R$ 99,90</i>"
        ),
        CB_EDIT_COPY: (
            "📝 <b>Digite a nova copy completa</b> que será publicada no canal:\n\n"
            "<i>Use HTML: &lt;b&gt;negrito&lt;/b&gt;, &lt;i&gt;itálico&lt;/i&gt;</i>"
        ),
        CB_EDIT_LINK: (
            "🔗 <b>Cole o novo link de afiliado</b> (completo, com sua tag):\n\n"
            "<i>Exemplo: https://amzn.to/xxxx?tag=seutag-20</i>"
        ),
        CB_EDIT_CUPOM: (
            "🎟️ <b>Digite o novo código do cupom:</b>\n\n"
            "<i>Para REMOVER o cupom, envie: <code>REMOVER</code></i>"
        ),
    }

    await query.edit_message_text(
        prompts.get(campo, "✍️ Digite o novo valor:") + "\n\n<i>Envie a mensagem abaixo:</i>",
        parse_mode=ParseMode.HTML,
    )
    return AGUARDAR_EDICAO_TEXTO


async def salvar_edicao_texto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Recebe o texto digitado pelo admin, atualiza user_data e regenera a prévia.
    """
    novo_valor = update.message.text.strip()
    campo      = context.user_data.get("edit_campo", "")

    if campo == CB_EDIT_PRECO:
        context.user_data["dados_produto"]["preco"] = novo_valor
        # Limpa override de copy para regenerar com novo preço
        context.user_data.pop("copy_override", None)
        await update.message.reply_text(
            f"✅ Preço atualizado para: <b>{_escape_html(novo_valor)}</b>",
            parse_mode=ParseMode.HTML,
        )

    elif campo == CB_EDIT_COPY:
        # Armazena override da copy — será usado por _send_previa
        context.user_data["copy_override"] = novo_valor
        await update.message.reply_text(
            "✅ <b>Copy atualizada!</b> Regenerando prévia...",
            parse_mode=ParseMode.HTML,
        )

    elif campo == CB_EDIT_LINK:
        from bot.services.affiliate_link_service import injetar_link_afiliado, _detectar_loja
        novo_link     = _extrair_primeira_url(novo_valor) or novo_valor.strip()
        store_key     = _detectar_loja(novo_link)
        affiliate_url = injetar_link_afiliado(novo_link, store_key)

        context.user_data["affiliate_url"] = affiliate_url
        context.user_data["store_key"]     = store_key
        context.user_data["final_url"]     = novo_link
        # Limpa override de copy para regenerar com novo link
        context.user_data.pop("copy_override", None)

        logger.info(f"[OFERTA_LINK] Link corrigido: {affiliate_url[:100]}")
        await update.message.reply_text(
            f"✅ Link atualizado!\n<code>{_escape_html(affiliate_url[:120])}</code>",
            parse_mode=ParseMode.HTML,
        )

    elif campo == CB_EDIT_CUPOM:
        if novo_valor.upper() == "REMOVER":
            context.user_data["cupom"] = None
            await update.message.reply_text(
                "✅ Cupom <b>removido</b> da oferta.",
                parse_mode=ParseMode.HTML,
            )
        else:
            context.user_data["cupom"] = novo_valor.upper()
            await update.message.reply_text(
                f"✅ Cupom atualizado para: <b>{_escape_html(novo_valor.upper())}</b>",
                parse_mode=ParseMode.HTML,
            )
        context.user_data.pop("copy_override", None)

    context.user_data.pop("edit_campo", None)

    # Regenera prévia com os dados atualizados
    return await _gerar_e_enviar_previa(update, context)


async def voltar_previa_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Admin clicou em ⬅️ Voltar pra Prévia no menu de edição."""
    query = update.callback_query
    await query.answer()
    # Usa query.message como base do reply
    return await _send_previa(query.message, context)


# ── Alias legado ─────────────────────────────────────────────────────────────
async def salvar_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Alias de compatibilidade para salvar_edicao_texto."""
    return await salvar_edicao_texto(update, context)
async def regen_ia_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Callback para o botão 'Gerar Legenda IA'."""
    query = update.callback_query
    await query.answer("✨ Gerando nova versão...")
    
    await _gerar_legenda_ia_background(query.message, context)
    return await _send_previa(query.message, context)
