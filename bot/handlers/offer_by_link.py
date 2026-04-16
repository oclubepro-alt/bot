"""
offer_by_link.py - Handler para criar ofertas via extração de link.

Fluxo:
  1. Admin envia link (pode ser encurtado/afiliado)
  2. Bot resolve a URL final (url_resolver)
  3. Bot extrai dados do produto (product_extractor)
  4. Se faltarem nome/preço, pede ao admin
  5. Admin pode informar link afiliado manual (ou /pular)
  6. Sistema aplica afiliado automático se configurado (affiliate_links)
  7. IA gera copy; admin confirma; bot publica
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ParseMode

from bot.permissions import is_admin
from bot.utils.constants import CB_CANCELAR_OFERTA, CB_MENU_PRINCIPAL
from bot.utils.url_resolver import resolve_url
from bot.services.product_extractor import extract_product_data
from bot.services.affiliate_links import get_final_link
from bot.services.affiliate_injector import get_affiliate_url
from bot.services.data_pipeline import process_product_data
from bot.services.link_shortener import shorten_for_publication
from bot.services.copy_builder import build_copy
from bot.services.ai_writer import generate_caption
from bot.services.publisher_router import publish_offer
from bot.utils.formatter import build_offer_message, build_preview_message

logger = logging.getLogger(__name__)

# Estados do fluxo de link
LINK_PRODUTO, PREENCHER_NOME_FALTANTE, PREENCHER_PRECO_FALTANTE, LINK_AFILIADO, CONFIRMAR_LINK, EDITAR_CAMPOS = range(10, 16)

# Callback exclusivo de confirmação deste fluxo
CB_CONFIRMAR_LINK = "oferta_link_confirmar"


async def start_offer_by_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user = query.from_user

    if not is_admin(user.id):
        logger.warning(f"[ACESSO NEGADO] {user.id} tentou acessar publicar por link.")
        await query.edit_message_text("⛔ Você não tem permissão para publicar.")
        return ConversationHandler.END

    logger.info(f"[OFERTA LINK] Admin {user.id} iniciou fluxo de extração.")
    context.user_data.clear()

    await query.edit_message_text(
        "🔗 <b>Passo 1</b> — Envie o <b>link</b> do produto:\n"
        "<i>(Aceito links encurtados: amzn.to, tidd.ly, bit.ly, etc.)</i>",
        parse_mode=ParseMode.HTML,
    )
    return LINK_PRODUTO


from bot.services.link_converter import extract_first_url, convert_links_in_text

async def receber_link_produto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw_text = update.message.text.strip()
    
    # Extrai o link principal do texto (pode ser uma mensagem completa)
    original_link = extract_first_url(raw_text)
    
    if not original_link:
        await update.message.reply_text("❌ Não encontrei nenhum link válido na sua mensagem. Tente novamente.")
        return LINK_PRODUTO

    logger.info(
        f"[OFERTA LINK] ── Promoção recebida ────────────────────────────\n"
        f"[OFERTA LINK] Texto Bruto: {raw_text[:100]}...\n"
        f"[OFERTA LINK] Link Extraído: {original_link}"
    )

    # Se a mensagem for maior que o link, guardamos o resto como descrição/base
    if len(raw_text) > len(original_link) + 10:
        context.user_data["descricao_base"] = raw_text
        logger.info("[OFERTA LINK] Texto adicional detectado, será usado como descrição.")

    # Guarda link ORIGINAL (será usado na publicação como fallback)
    context.user_data["original_url"] = original_link
    context.user_data["product_url"] = original_link

    msg = await update.message.reply_text(
        "⏳ Resolvendo link e extraindo dados do produto... Aguarde."
    )

    # Extração Mestra (Etapas 1, 2, 3, 4) — Agora faz o resolve internamente
    dados = extract_product_data(original_link)
    
    # Normalização para compatibilidade com o resto do handler
    # O novo extrator retorna 'title', 'price', 'image_url'
    dados["nome"] = dados.get("title")
    dados["preco"] = dados.get("price")
    dados["imagem"] = dados.get("image_url")
    
    # Preserva o link original como URL do produto (não a URL técnica)
    dados["product_url"] = original_link
    
    # Se capturamos uma descrição base, usamos se o extractor falhar
    if context.user_data.get("descricao_base") and (not dados.get("descricao") or dados.get("descricao") == "Produto"):
        dados["descricao"] = context.user_data["descricao_base"]

    context.user_data["extracted"] = dados

    await msg.delete()

    loja_txt = dados.get("loja", "Desconhecida")
    store_key = dados.get("store_key", "other")
    logger.info(f"[OFERTA LINK] Loja detectada: {loja_txt} (key={store_key})")

    # Fallbacks manuais (Etapa 4: se voltou o padrão "Produto" ou "Preço não disponível")
    if not dados.get("nome") or dados.get("nome") == "Produto":
        await update.message.reply_text(
            "📝 Não consegui extrair o nome automaticamente. Por favor, digite o <b>nome do produto</b>:",
            parse_mode=ParseMode.HTML
        )
        return PREENCHER_NOME_FALTANTE

    if not dados.get("preco") or dados.get("preco") == "Preço não disponível":
        nome_extraido = dados.get("nome", "Não extraído")
        await update.message.reply_text(
            f"✅ Nome: <b>{nome_extraido}</b>\n"
            f"🏪 Loja: <b>{dados.get('loja', 'Desconhecida')}</b>\n"
            f"⚠️ <i>(Debug V3.5)</i>\n\n"
            "📝 Não consegui extrair o preço automaticamente. Por favor, digite o <b>preço</b> (ex: R$ 49,90):",
            parse_mode=ParseMode.HTML
        )
        return PREENCHER_PRECO_FALTANTE

    # Agora, em vez de pedir link de afiliado, vamos direto para a prévia completa
    return await _gerar_previa_link(update, context)


async def preencher_nome_faltante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    nome = update.message.text.strip()
    context.user_data["extracted"]["nome"] = nome

    if not context.user_data["extracted"].get("preco"):
        await update.message.reply_text(
            "📝 Agora, por favor, digite o <b>preço</b>:",
            parse_mode=ParseMode.HTML
        )
        return PREENCHER_PRECO_FALTANTE

    return await _gerar_previa_link(update, context)


async def preencher_preco_faltante(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    preco = update.message.text.strip()
    context.user_data["extracted"]["preco"] = preco
    return await _gerar_previa_link(update, context)


async def _pedir_link_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE):
    dados = context.user_data["extracted"]
    original_url = context.user_data.get("original_url", "")
    resolved_url = context.user_data.get("resolved_url", "")

    # Verifica se já existe afiliado automático configurado
    from bot.services.affiliate_links import get_final_link as _get_final
    auto_link = _get_final(original_url, affiliate_url=None, resolved_url=resolved_url)
    has_auto = auto_link != original_url  # mudou → tem afiliado auto

    auto_info = (
        f"\n\n✅ <b>Afiliado automático detectado!</b> ({dados.get('loja', '')})\n"
        "O bot já vai aplicar o link de afiliado configurado automaticamente."
        if has_auto else ""
    )

    preco_original_txt = f"\n🔹 <b>Preço Original:</b> {dados.get('preco_original')}" if dados.get("preco_original") else ""
    await update.message.reply_text(
        f"✅ <b>Extração Concluída</b>\n\n"
        f"🔹 <b>Produto:</b> {dados['nome']}\n"
        f"🔹 <b>Preço Atual:</b> {dados['preco']}"
        f"{preco_original_txt}\n"
        f"🔹 <b>Loja:</b> {dados.get('loja', 'Desconhecida')}\n"
        f"{auto_info}\n\n"
        "🔗 <b>Passo 2</b> — Envie o <b>Link de Afiliado</b> para usar na publicação!\n"
        "<i>(Ou envie /pular para usar o link automático/original)</i>",
        parse_mode=ParseMode.HTML
    )


async def receber_link_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["affiliate_url"] = update.message.text.strip()
    return await _gerar_previa_link(update, context)


async def pular_link_afiliado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["affiliate_url"] = None
    return await _gerar_previa_link(update, context)


async def _gerar_previa_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    dados = context.user_data["extracted"]
    original_url = context.user_data.get("original_url") or context.user_data.get("product_url", "")
    resolved_url = context.user_data.get("resolved_url", "")
    affiliate_url_manual = context.user_data.get("affiliate_url")
    store_key = dados.get("store_key", "other")

    # ── 1. Pipeline: limpeza + validação de preço ────────────────────────────
    pipeline = process_product_data(
        raw_nome  = dados.get("nome"),
        raw_preco = dados.get("preco"),
        loja      = dados.get("loja", "Desconhecida"),
        store_key = store_key,
    )
    # Actualiza dados com nome/preço limpos
    dados["nome"]  = pipeline["nome"]  or dados.get("nome", "")
    dados["preco"] = pipeline["preco"] or dados.get("preco", "")

    # Alerta de preço suspeito ao admin (não bloqueia publicação)
    if pipeline["status"] == "ERRO: PREÇO_SUSPEITO":
        await update.message.reply_text(
            "⚠️ <b>ATENÇÃO: PREÇO SUSPEITO DETECTADO!</b>\n\n"
            f"O preço <code>{pipeline['preco']}</code> está muito distante da média histórica "
            "para este produto.\n"
            "Verifique se é um erro de scraping antes de publicar.",
            parse_mode=ParseMode.HTML,
        )
        logger.warning(
            f"[OFERTA LINK] PREÇO SUSPEITO para '{dados['nome'][:40]}' "
            f"— preço={pipeline['preco']} | store_key={store_key}"
        )

    # ── 2. Injeção de afiliado ───────────────────────────────────────────────
    # Prioridade: injector automático > afiliado manual > original
    if affiliate_url_manual and affiliate_url_manual.strip():
        final_link_longo = affiliate_url_manual.strip()
        logger.info(f"[OFERTA LINK] Usando afiliado MANUAL fornecido pelo admin.")
    else:
        final_link_longo = get_affiliate_url(
            original_url = original_url,
            resolved_url = resolved_url,
            store_key    = store_key,
        )
        # Fallback para o sistema legado (affiliate_config.json)
        if final_link_longo == original_url:
            legacy = get_final_link(
                original_url = original_url,
                affiliate_url = None,
                resolved_url  = resolved_url,
            )
            if legacy != original_url:
                final_link_longo = legacy

    logger.info(f"[OFERTA LINK] Link longo (afiliado): {final_link_longo[:100]}")

    # ── 3. Encurtamento ──────────────────────────────────────────────────────
    short_url = shorten_for_publication(final_link_longo)
    logger.info(f"[OFERTA LINK] Link curto: {short_url}")
    context.user_data["final_link"] = short_url
    context.user_data["final_link_longo"] = final_link_longo

    # ── 4. Geração de copy pela IA ───────────────────────────────────────────
    aguardo = await update.message.reply_text("⏳ IA gerando copy envolvente... aguarde!")

    copy_ia = await generate_caption(
        nome         = dados["nome"],
        preco        = dados["preco"],
        loja         = dados["loja"],
        descricao    = dados.get("descricao"),
        preco_original = dados.get("preco_original"),
    )

    # ── 5. Copy multi-plataforma ─────────────────────────────────────────────
    copies = build_copy(
        nome           = dados["nome"],
        preco          = dados["preco"],
        loja           = dados["loja"],
        store_key      = store_key,
        short_url      = short_url,
        legenda_ia     = copy_ia,
        preco_original = dados.get("preco_original"),
    )
    context.user_data["copies"]      = copies
    context.user_data["copy_ia"]     = copy_ia

    # Mantém compatibilidade com o publisher legado
    mensagem = build_offer_message(
        nome      = dados["nome"],
        preco     = dados["preco"],
        loja      = dados["loja"],
        link      = short_url,
        legenda_ia = copy_ia,
    )
    context.user_data["mensagem_final"] = mensagem

    await aguardo.delete()

    # ── 6. Prévia ao admin ───────────────────────────────────────────────────
    # Exibe ambas as versões para o admin avaliar
    preview_full = (
        f"📱 <b>VERSÃO TELEGRAM:</b>\n\n"
        f"{copies['telegram']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 <b>VERSÃO WHATSAPP:</b>\n\n"
        f"{copies['whatsapp']}"
    )

    keyboard = [
        [
            InlineKeyboardButton("✅ Confirmar Envio", callback_data=CB_CONFIRMAR_LINK),
            InlineKeyboardButton("❌ Cancelar", callback_data=CB_CANCELAR_OFERTA),
        ],
        [InlineKeyboardButton("✏️ Corrigir Promoção", callback_data="editar_oferta")],
        [InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)]
    ]

    img_url = dados.get("imagem")
    try:
        if img_url:
            await update.message.reply_photo(
                photo=img_url,
                caption=preview_full,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await update.message.reply_text(
                preview_full,
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(keyboard),
                disable_web_page_preview=True,
            )
    except Exception:
        # Fallback: envia sem formatação para não travar o fluxo
        await update.message.reply_text(
            "Visualização formatada falhou, mas a oferta pode ser enviada.\n" + copies["telegram"],
            reply_markup=InlineKeyboardMarkup(keyboard),
            disable_web_page_preview=True,
        )
    return CONFIRMAR_LINK


async def confirmar_envio_link(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    back_keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ Voltar ao Menu", callback_data=CB_MENU_PRINCIPAL)
    ]])

    if query.data == CB_CANCELAR_OFERTA:
        context.user_data.clear()
        await query.edit_message_text(
            "❌ Oferta via link cancelada.",
            reply_markup=back_keyboard
        )
        return ConversationHandler.END

    # Pega os copies conforme a plataforma no publisher_router
    # Passamos o dicionário 'copies' para o publisher_router
    copies = context.user_data["copies"]
    img_url = context.user_data.get("extracted", {}).get("imagem")

    try:
        await publish_offer(context.bot, copies, img_url)
        msg_sucesso = "🎉 <b>Oferta via link publicada com sucesso!</b>"
        try:
            if img_url:
                await query.message.delete()
                await context.bot.send_message(
                    query.message.chat_id, 
                    text=msg_sucesso, 
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard
                )
            else:
                await query.edit_message_text(
                    msg_sucesso, 
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard
                )
        except Exception:
            pass
    except Exception as e:
        await context.bot.send_message(
            query.message.chat_id, 
            text=f"❌ Erro ao enviar: {e}",
            reply_markup=back_keyboard
        )

    context.user_data.clear()
    return ConversationHandler.END


# ── Edição de Campos ────────────────────────────────────────────────────────

async def btn_editar_oferta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("🏷️ Nome", callback_data="edit_nome"), InlineKeyboardButton("💰 Preço", callback_data="edit_preco")],
        [InlineKeyboardButton("📝 Legenda/Copy", callback_data="edit_copy")],
        [InlineKeyboardButton("⬅️ Cancelar Edição", callback_data="cancel_edit")]
    ]
    
    await query.edit_message_text(
        "🛠️ <b>O que você deseja corrigir?</b>",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return EDITAR_CAMPOS

async def escolher_campo_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "cancel_edit":
        return await _gerar_previa_link(update, context)
        
    campo = query.data.replace("edit_", "")
    context.user_data["edit_campo"] = campo
    
    msgs = {
        "nome": "Digite o novo *Nome* do produto:",
        "preco": "Digite o novo *Preço* (ex: R$ 99,90):",
        "copy": "Digite a nova *Legenda/Copy* (será usada no Telegram e no WhatsApp):"
    }
    
    await query.edit_message_text(
        f"✍️ {msgs.get(campo)}",
        parse_mode=ParseMode.HTML
    )
    return EDITAR_CAMPOS # Reutilizamos o estado para receber a msg de texto

async def salvar_edicao(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    novo_valor = update.message.text.strip()
    campo = context.user_data.get("edit_campo")
    
    if campo == "nome":
        context.user_data["extracted"]["nome"] = novo_valor
    elif campo == "preco":
        # Tentamos reprocessar o preço se for edição de valor
        context.user_data["extracted"]["preco"] = novo_valor
    elif campo == "copy":
        context.user_data["copy_ia"] = novo_valor

    await update.message.reply_text(f"✅ Campo *{campo}* atualizado!")
    return await _gerar_previa_link(update, context)
