"""
openai_service.py - Integracao com OpenAI para geracao de legenda da oferta
"""
import logging
import httpx
from openai import AsyncOpenAI, OpenAIError

from bot.utils.config import OPENAI_API_KEY, OPENAI_MODEL, HTTP_PROXY

logger = logging.getLogger(__name__)

# Cliente assincrono (reutilizavel)
client_kwargs = {
    "api_key": OPENAI_API_KEY,
}
if HTTP_PROXY:
    client_kwargs["http_client"] = httpx.AsyncClient(proxy=HTTP_PROXY)

_client = AsyncOpenAI(**client_kwargs)

_SYSTEM_PROMPT = """
Você e um copywriter especialista em grupos de "achadinhos" do Telegram.
Sua missao: escrever legendas curtas, envolventes e autênticas para ofertas.

REGRAS OBRIGATORIAS:
- Maximo 5 linhas
- Tom informal e animado (como um amigo compartilhando uma oferta)
- Destaque o preco e o beneficio principal
- CTA leve no final (ex: "Corre!" / "Vale muito!" / "Nao perde!")
- NAO invente informacoes que nao foram fornecidas
- NAO inclua o link (ele sera adicionado automaticamente)
- NAO repita o nome do produto de forma robotica
- NAO use markdown com asteriscos — escreva texto limpo
""".strip()


async def generate_caption(
    nome: str,
    preco: str,
    loja: str,
    descricao: str | None = None,
) -> str:
    """
    Chama o GPT para gerar uma legenda da oferta.
    Retorna a legenda gerada ou um texto padrao se a IA falhar.
    """
    descricao_extra = f"\nInformacao adicional: {descricao}" if descricao else ""

    user_prompt = (
        f"Produto: {nome}\n"
        f"Preco: {preco}\n"
        f"Loja: {loja}"
        f"{descricao_extra}\n\n"
        "Escreva a legenda da oferta agora:"
    )

    logger.info(f"[IA] Gerando legenda para: '{nome}' | Modelo: {OPENAI_MODEL}")

    try:
        response = await _client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=200,
            temperature=0.75,
        )
        legenda = response.choices[0].message.content.strip()
        logger.info(f"[IA] Legenda gerada com sucesso ({len(legenda)} chars)")
        return legenda

    except OpenAIError as e:
        logger.error(f"[IA] Falha na API OpenAI: {e}")
        return _fallback_caption(nome, preco, loja)

    except Exception as e:
        logger.error(f"[IA] Erro inesperado ao chamar OpenAI: {e}")
        return _fallback_caption(nome, preco, loja)


def _fallback_caption(nome: str, preco: str, loja: str) -> str:
    """Texto padrao usado quando a IA nao esta disponivel."""
    logger.warning("[IA] Usando legenda padrao (fallback)")
    return (
        f"Encontramos uma oferta incrivel de {nome} por apenas {preco} na {loja}!\n"
        "Essa e uma oportunidade que nao da pra perder. Corre antes que acabe! 🏃‍♂️"
    )
