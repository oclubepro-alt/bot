
import asyncio
from bot.services.affiliate_link_service import injetar_link_afiliado
import os

# Simula ID configurado
os.environ["AFFILIATE_ID_ML"] = "MEU_ID_TESTE"

async def test():
    url = "https://www.mercadolivre.com.br/social/cupomonline?matt_word=cupomonline&matt_tool=53340084&forceInApp=true&ref=TESTE"
    result = await injetar_link_afiliado(url)
    print(f"Original: {url}")
    print(f"Resultado: {result}")

asyncio.run(test())
