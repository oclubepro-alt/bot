"""
openai_service.py - Integração com OpenAI para geração de legenda da oferta
"""
import logging
from openai import AsyncOpenAI, OpenAIError

from bot.utils.config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

# Cliente assíncrono (reutilizável)
_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_SYSTEM_PROMPT = """
Você é um copywriter especialista em grupos de "achadinhos" do Telegram.
Sua missão: escrever legendas curtas, envolventes e autênticas para ofertas.

REGRAS OBRIGATÓRIAS:
- Máximo 5 linhas
- Tom informal e animado (como um amigo compartilhando uma oferta)
- Destaque o preço e o benefício principal
- CTA leve no final (ex: "Corre!" / "Vale muito!" / "Não perde!")
- NÃO invente informações que não foram fornecidas
- NÃO inclua o link (ele será adicionado automaticamente)
- NÃO repita o nome do produto de forma robótica
- NÃO use markdown com asteriscos — escreva texto limpo
""".strip()


async def generate_caption(
    nome: str,
    preco: str,
    loja: str,
    descricao: str | None = None,
) -> str:
    """
    Chama o GPT para gerar uma legenda da oferta.
    Retorna a legenda gerada ou um texto padrão se a IA falhar.
    """
    descricao_extra = f"\nInformação adicional: {descricao}" if descricao else ""

    user_prompt = (
        f"Produto: {nome}\n"
        f"Preço: {preco}\n"
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
    """Texto padrão usado quando a IA não está disponível."""
    logger.warning("[IA] Usando legenda padrão (fallback)")
    return (
        f"Encontramos uma oferta incrível de {nome} por apenas {preco} na {loja}!\n"
        "Essa é uma oportunidade que não dá pra perder. Corre antes que acabe! 🏃‍♂️"
    )
