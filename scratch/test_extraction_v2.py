
import asyncio
import logging
import sys
import os

# Ajusta o path para importar o bot
sys.path.append(os.getcwd())

from bot.services.product_extractor_v2 import extract_product_data_v2

async def test():
    logging.basicConfig(level=logging.INFO)
    
    urls = [
        "https://www.amazon.com.br/dp/B0D5B7L9V3", # Exemplo Amazon
        "https://www.magazineluiza.com.br/p/237242100/ed/tv4k/", # Exemplo Magalu
    ]
    
    for url in urls:
        print(f"\n--- TESTANDO: {url} ---")
        result = await extract_product_data_v2(url)
        print(f"RESULTADO: {result}")

if __name__ == "__main__":
    asyncio.run(test())
