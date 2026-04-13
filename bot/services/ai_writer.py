"""
ai_writer.py - Integração com OpenAI para geração de legenda da oferta
"""
import logging
import httpx
from openai import AsyncOpenAI, OpenAIError

from bot.utils.config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL

logger = logging.getLogger(__name__)

# Cliente assíncrono (reutilizável) suportando fallback de URL
client_kwargs = {"api_key": OPENAI_API_KEY}
if OPENAI_BASE_URL:
    client_kwargs["base_url"] = OPENAI_BASE_URL

_client = AsyncOpenAI(
    **client_kwargs,
    http_client=httpx.AsyncClient(proxy="http://proxy.server:3128")
)

_SYSTEM_PROMPT = """
Você é um copywriter especialista em grupos de "achadinhos" do Telegram.
Sua missão: escrever legendas curtas, envolventes e autênticas para ofertas.

REGRAS OBRIGATÓRIAS:
- Escrever em português do Brasil
- Máximo 5 linhas
- Tom informal, focado em "achadinhos" (use termos como "Olha isso!", "Preção!", "Corre!")
- Se houver preço original e preço atual, calcule mentalmente ou destaque que está em PROMOÇÃO/DESCONTO.
- Seja coerente: se o desconto for grande, use emojis de fogo 🔥 ou espanto 😱.
- CTA leve no final (ex: "Corre!" / "Vale muito!" / "Não perde!")
- NÃO invente preço nem frete grátis.
- NÃO altere o nome do produto nem a loja.
- NÃO inclua o link na sua resposta.
- NÃO use markdown com asteriscos (ex: **texto** é proibido).
""".strip()


async def generate_caption(
    nome: str,
    preco: str,
    loja: str,
    descricao: str | None = None,
    preco_original: str | None = None,
) -> str:
    """
    Chama o GPT para gerar uma legenda da oferta.
    """
    descricao_extra = f"\nInformação adicional: {descricao}" if descricao else ""
    info_desconto = f"\nPreço Original: {preco_original}\nPreço Atual: {preco}" if preco_original else f"\nPreço: {preco}"

    user_prompt = (
        f"Produto: {nome}"
        f"{info_desconto}\n"
        f"Loja: {loja}"
        f"{descricao_extra}\n\n"
        "Se houver preço original e atual, destaque o DESCONTO no texto de forma empolgante.\n"
        "Escreva a legenda da oferta agora (sem asteriscos):"
    )

    logger.info(f"[IA] Gerando legenda para: '{nome[:30]}...' | Modelo: {OPENAI_MODEL}")

    try:
        response = await _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=200,
            temperature=0.8,
        )
        legenda = response.choices[0].message.content.strip()
        logger.info(f"[IA] Legenda gerada com sucesso ({len(legenda)} chars)")
        return legenda

    except OpenAIError as e:
        logger.error(f"[IA] Falha na API OpenAI: {e}")
        return _fallback_caption(nome, preco, loja, preco_original)

    except Exception as e:
        logger.error(f"[IA] Erro inesperado ao chamar OpenAI: {e}")
        return _fallback_caption(nome, preco, loja, preco_original)


def _fallback_caption(nome: str, preco: str, loja: str, preco_original: str | None = None) -> str:
    """Texto padrão usado quando a IA não está disponível."""
    logger.warning("[IA] Usando legenda padrão (fallback)")
    if preco_original:
        return (
            f"🔥 OPORTUNIDADE: {nome}\n"
            f"De {preco_original} por APENAS {preco} na {loja}!\n"
            "Corre pra aproveitar esse descontão! 🏃‍♂️💨"
        )
    return (
        f"Encontramos uma oferta incrível de {nome} por apenas {preco} na {loja}!\n"
        "Essa é uma oportunidade que não dá pra perder. Corre antes que acabe! 🏃‍♂️"
    )
