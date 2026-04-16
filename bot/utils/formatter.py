def escape_html(text: str) -> str:
    """Escapa caracteres HTML básicos."""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_offer_message(
    nome: str,
    preco: str,
    loja: str,
    link: str,
    legenda_ia: str,
) -> str:
    """
    Retorna a mensagem formatada em HTML pronta para enviar ao canal.
    """
    return (
        f"📦 <b>{escape_html(nome)}</b>\n\n"
        f"💰 <b>Preço:</b> {escape_html(preco)}\n"
        f"🏪 <b>Loja:</b> {escape_html(loja)}\n\n"
        f"{escape_html(legenda_ia)}\n\n"
        f"🛒 <b>Compre aqui:</b> {escape_html(link)}"
    )


def build_preview_message(message: str) -> str:
    """O message já vem formatado em HTML pelo build_offer_message."""
    return f"👀 <b>PRÉVIA DA OFERTA</b>\n\n{message}"
