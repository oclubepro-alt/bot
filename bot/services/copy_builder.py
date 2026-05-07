"""
copy_builder.py — Geração de copy multi-plataforma para ofertas.

Gera dois blocos distintos a partir dos dados do produto:
  1. VERSÃO TELEGRAM  — Markdown V2 compatível com parse_mode=MarkdownV2.
  2. VERSÃO WHATSAPP  — Texto puro com negrito via asteriscos (*texto*).

Regras gerais:
  - Link curto é sempre o que aparece (nunca a URL longa de afiliado).
  - Telegram: todos os caracteres especiais são escapados conforme spec Bot API.
  - WhatsApp: texto curtíssimo (≤ 160 chars sem link) para evitar botão "Ler mais".
  - Emoji de categoria é detectado automaticamente pelo nome/loja.

Usage:
    from bot.services.copy_builder import build_copy
    copy = build_copy(nome, preco, loja, store_key, short_url,
                      legenda_ia=None, preco_original=None,
                      whatsapp_channel="https://wa.me/channel/SEU_LINK")
    print(copy["telegram"])
    print(copy["whatsapp"])
"""
import re
import logging
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------
_WA_CHANNEL = os.getenv("WHATSAPP_CHANNEL_URL", "").strip()

# ---------------------------------------------------------------------------
# Mapeamento de emojis por categoria/loja/palavras-chave no nome
# ---------------------------------------------------------------------------
_CATEGORY_EMOJIS: list[tuple[list[str], str]] = [
    # Eletrônicos / Tecnologia
    (["iphone", "samsung", "xiaomi", "celular", "smartphone", "fone", "airpod",
      "tablet", "ipad", "note", "galaxy", "motorola", "poco"], "📱"),
    (["notebook", "macbook", "laptop", "pc", "computador", "monitor",
      "teclado", "mouse", "webcam", "processador", "ssd", "hd", "placa de vídeo", "gpu"], "💻"),
    (["tv", "smart tv", "televisão", "televisor", "led", "4k", "oled"], "📺"),
    (["câmera", "camera", "gopro", "lens", "lente", "tripé", "drone", "instax", "polaroid"], "📷"),
    (["fone", "headphone", "headset", "earphone", "speaker", "caixa de som",
      "soundbar", "jbl", "bose", "sony", "alexa", "echo dot"], "🔊"),
    (["console", "playstation", "xbox", "nintendo", "switch", "videogame",
      "controle", "joystick", "game", "gamer", "cadeira gamer"], "🎮"),
    # Moda / Vestuário
    (["tênis", "tenis", "adidas", "nike", "puma", "vans", "sapato",
      "bota", "sandália", "chinelo", "oakley"], "👟"),
    (["camisa", "camiseta", "blusa", "calça", "casaco", "jaqueta",
      "vestido", "moletom", "agasalho", "bermuda", "cueca", "meia"], "👕"),
    (["bolsa", "mochila", "carteira", "necessaire", "mala", "kipling"], "👜"),
    (["relógio", "relogio", "watch", "smartwatch", "apple watch", "amazfit"], "⌚"),
    (["óculos", "oculos", "ray ban", "sunglasses"], "🕶️"),
    # Casa e Cozinha
    (["airfryer", "fritadeira", "panela", "fogão", "forno", "microondas",
      "cafeteira", "nespresso", "dolce gusto", "liquidificador", "batedeira", "sanduicheira"], "🍳"),
    (["geladeira", "freezer", "refrigerador", "lavadora", "máquina de lavar",
      "secadora", "aspirador", "robô aspirador", "mop"], "🏠"),
    (["jogo de cama", "lençol", "travesseiro", "toalha", "edredom"], "🛏️"),
    (["ferramenta", "bosch", "furadeira", "parafusadeira", "jogo de chaves"], "🛠️"),
    # Esportes / Fitness
    (["haltere", "halter", "kettlebell", "bicicleta", "bike", "esteira",
      "suplemento", "whey", "proteína", "creatina", "pre treino"], "🏋️"),
    # Beleza / Cuidados
    (["perfume", "colônia", "fragrância", "maquiagem", "batom", "shampoo",
      "condicionador", "creme", "hidratante", "protetor", "skincare", "dove", "nivea"], "✨"),
    (["escova", "chapinha", "secador", "barbeador", "philips"], "🪮"),
    # Livros / Educação
    (["livro", "book", "curso", "kindle", "ebook", "papelaria"], "📚"),
    # Bebês / Infantil
    (["bebê", "bebe", "infantil", "fraldas", "carrinho", "berço", "pampers", "huggies"], "👶"),
    (["brinquedo", "lego", "boneca", "carrinho", "quebra cabeça"], "🧸"),
    # Pets
    (["pet", "cachorro", "gato", "ração", "coleira", "arranhador", "whiskas"], "🐾"),
    # Higiene / Limpeza
    (["sabão", "omo", "detergente", "amaciante", "papel higiênico", "limpeza"], "🧼"),
    # Lojas (como fallback)
    (["netshoes"], "👟"),
    (["magalu", "magazine"], "🛒"),
    (["amazon"], "📦"),
    (["mercado livre", "mercadolivre"], "🟡"),
]
]

_DEFAULT_EMOJI = "🔥"


def _category_emoji(nome: str, loja: str) -> str:
    """Detecta o emoji mais adequado para o produto."""
    text = (nome + " " + loja).lower()
    for keywords, emoji in _CATEGORY_EMOJIS:
        if any(kw in text for kw in keywords):
            return emoji
    return _DEFAULT_EMOJI


# ---------------------------------------------------------------------------
# Escape para Telegram MarkdownV2
# Caracteres que precisam de escape: _ * [ ] ( ) ~ ` > # + - = | { } . !
# ---------------------------------------------------------------------------
_MDV2_ESCAPE_RE = re.compile(r"([_*\[\]()~`>#+=|{}.!\-\\])")


def _escape_html(text: str) -> str:
    """Escapa texto para uso seguro no HTML do Telegram."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Desconto calculado
# ---------------------------------------------------------------------------

def _calc_desconto(preco: str, preco_original: str | None) -> str | None:
    """
    Calcula o percentual de desconto entre preço original e atual.
    Retorna string formatada '(↓ XX%)' ou None se não puder calcular.
    """
    if not preco_original:
        return None
    def _to_float(s: str) -> float | None:
        s = re.sub(r"[R$\s]", "", s)
        s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return None

    atual = _to_float(preco)
    orig  = _to_float(preco_original)
    if atual and orig and orig > atual:
        pct = round((orig - atual) / orig * 100)
        return f"↓ {pct}%"
    return None


# ---------------------------------------------------------------------------
# Construtores de copy
# ---------------------------------------------------------------------------

def _build_telegram(
    nome: str,
    preco: str,
    loja: str,
    short_url: str,
    emoji: str,
    legenda_ia: str | None,
    preco_original: str | None,
    desconto: str | None,
) -> str:
    nome_e  = _escape_html(nome)
    preco_e = _escape_html(preco)
    loja_e  = _escape_html(loja)

    linhas = []
    
    # Cabeçalho Principal
    linhas.append(f"{emoji} <b>{nome_e}</b>")
    linhas.append("")

    # Seção de Preço
    p_line = f"💰 <b>Preço:</b> {preco_e}"
    if preco_original and preco_original != preco:
        orig_e = _escape_html(preco_original)
        p_line += f" <s>{orig_e}</s>"
    
    if desconto:
        desc_e = _escape_html(desconto)
        p_line += f" ({desc_e})"
    
    linhas.append(p_line)

    # Loja e Contexto
    linhas.append(f"🏪 <b>Loja:</b> {loja_e}")

    # IA / Legenda (se houver)
    if legenda_ia and legenda_ia.strip():
        linhas.append("")
        linhas.append(f"✨ <i>{_escape_html(legenda_ia.strip())}</i>")

    # Call to Action
    linhas.append("")
    linhas.append(f"🛒 <a href='{short_url}'><b>CLIQUE AQUI PARA COMPRAR</b></a>")
    linhas.append("")
    linhas.append("🚨 <i>Preços sujeitos a alteração a qualquer momento!</i>")

    return "\n".join(linhas)


def _build_whatsapp(
    nome: str,
    preco: str,
    loja: str,
    short_url: str,
    emoji: str,
    preco_original: str | None,
    desconto: str | None,
    wa_channel: str,
) -> str:
    """
    Monta copy para WhatsApp em texto simples com negritos via *.

    Mantido ultra-curto (evita botão "Ler mais"):
        EMOJI *NOME* (até 60 chars)
        💰 *R$ XX,XX* [De R$ YY,YY] (↓ZZ%)
        🏪 Loja

        👉 LINK

        📣 Canal: WA_CHANNEL
    """
    nome_curto = nome[:60] + ("…" if len(nome) > 60 else "")

    linhas = [f"{emoji} *{nome_curto}*"]

    preco_line = f"💰 *{preco}*"
    if preco_original and preco_original != preco:
        preco_line += f" ~De: {preco_original}~"
    if desconto:
        preco_line += f" ({desconto})"
    linhas.append(preco_line)
    linhas.append(f"🏪 {loja}")

    linhas.append("")
    linhas.append(f"👉 {short_url}")

    if wa_channel:
        linhas.append("")
        linhas.append(f"📣 Canal: {wa_channel}")

    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------

def build_copy(
    nome: str,
    preco: str,
    loja: str,
    store_key: str,
    short_url: str,
    *,
    legenda_ia: str | None = None,
    preco_original: str | None = None,
    whatsapp_channel: str | None = None,
) -> dict:
    """
    Gera copy multi-plataforma para uma oferta.

    Args:
        nome:             Nome limpo do produto.
        preco:            Preço formatado (ex: "R$ 299,90").
        loja:             Nome de exibição da loja.
        store_key:        Chave interna da loja.
        short_url:        Link encurtado (nunca a URL longa de afiliado!).
        legenda_ia:       Texto gerado pela IA (opcional).
        preco_original:   Preço riscado/original (opcional).
        whatsapp_channel: URL do canal do WhatsApp para rodapé.

    Returns:
        {
            "telegram": str  — MarkdownV2 pronto para parse_mode=MarkdownV2
            "whatsapp": str  — Texto simples com asteriscos
            "emoji":    str  — Emoji da categoria detectado
        }
    """
    wa_ch   = whatsapp_channel or _WA_CHANNEL
    emoji   = _category_emoji(nome, loja)
    desconto = _calc_desconto(preco, preco_original)

    telegram_copy = _build_telegram(
        nome=nome,
        preco=preco,
        loja=loja,
        short_url=short_url,
        emoji=emoji,
        legenda_ia=legenda_ia,
        preco_original=preco_original,
        desconto=desconto,
    )

    whatsapp_copy = _build_whatsapp(
        nome=nome,
        preco=preco,
        loja=loja,
        short_url=short_url,
        emoji=emoji,
        preco_original=preco_original,
        desconto=desconto,
        wa_channel=wa_ch,
    )

    logger.info(
        f"[COPY_BUILDER] Copy gerado | emoji={emoji} | "
        f"telegram={len(telegram_copy)} chars | whatsapp={len(whatsapp_copy)} chars"
    )

    return {
        "telegram": telegram_copy,
        "whatsapp": whatsapp_copy,
        "emoji":    emoji,
    }


def build_copy_from_pipeline(pipeline_result: dict, short_url: str, **kwargs) -> dict:
    """
    Atalho: recebe o dicionário de saída do data_pipeline e gera o copy.

    Args:
        pipeline_result: Saída de data_pipeline.process_product_data().
        short_url:       Link curto para publicação.
        **kwargs:        Argumentos extras para build_copy (legenda_ia, etc.).

    Returns:
        Mesmo dict de build_copy.
    """
    return build_copy(
        nome      = pipeline_result.get("nome", ""),
        preco     = pipeline_result.get("preco", ""),
        loja      = pipeline_result.get("loja", ""),
        store_key = pipeline_result.get("store_key", "other"),
        short_url = short_url,
        **kwargs,
    )
