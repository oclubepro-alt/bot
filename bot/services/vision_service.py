
import base64
import logging
import httpx
from bot.services.openai_service import _client, OPENAI_MODEL

logger = logging.getLogger(__name__)

async def detect_watermark(image_bytes: bytes) -> bool:
    """
    Detecta se uma imagem possui marca d'agua ou identificacao de outros canais
    usando a capacidade de visao do GPT-4o-mini.
    """
    try:
        # Encode para base64
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        
        # O GPT-4o-mini suporta visao e e extremamente barato
        # Prompt focado em identificar @usernames, logos ou textos de verificacao
        prompt = (
            "Analise esta imagem de oferta. Ela possui alguma 'marca d'agua', logo de outro canal do Telegram, "
            "ou selo de 'oferta verificada' (ex: '@usuario', 'promocao verificada', 'exclusivo')? "
            "Responda APENAS 'SIM' ou 'NAO'."
        )

        response = await _client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}"
                            }
                        },
                    ],
                }
            ],
            max_tokens=10,
            temperature=0,
        )
        
        answer = response.choices[0].message.content.strip().upper()
        logger.info(f"[VISION] Resposta deteccao marca d'agua: {answer}")
        
        # Se a IA responder SIM, retornamos True (tem marca d'agua)
        return "SIM" in answer or "YES" in answer

    except Exception as e:
        logger.error(f"[VISION] Erro ao detectar marca d'agua: {e}")
        # Em caso de erro na IA, permitimos a imagem para nao bloquear o fluxo por falha tecnica
        return False
