"""
formatter.py - Monta a mensagem final da oferta no formato padrão
"""


def build_offer_message(
    nome: str,
    preco: str,
    loja: str,
    link: str,
    legenda_ia: str,
) -> str:
    """
    Retorna a mensagem formatada pronta para enviar ao canal.

    Formato:
        🔥 OFERTA

        Produto: {nome}
        💰 Preço: {preco}
        🏪 Loja: {loja}

        {legenda_ia}

        👉 {link}
    """
    return (
        f"🔥 *OFERTA*\n\n"
        f"*Produto:* {nome}\n"
        f"💰 *Preço:* {preco}\n"
        f"🏪 *Loja:* {loja}\n\n"
        f"{legenda_ia}\n\n"
        f"👉 {link}"
    )


def build_preview_message(message: str) -> str:
    """Adiciona cabeçalho de prévia antes da mensagem real."""
    return f"👀 *PRÉVIA DA OFERTA*\n\n{message}"
