
import asyncio
import logging
import sys
import os

# Mock logging
logging.basicConfig(level=logging.INFO)

# Adiciona o diretorio atual ao path
sys.path.append(r"c:\Users\rrps2\Downloads\bot-main\bot-main")

from bot.services.product_extractor_v2 import fetch_magalu_api

async def test():
    url = "https://www.magazineluiza.com.br/p/237242100/ed/tv4k/"
    print(f"Testing Magalu API for: {url}")
    res = await fetch_magalu_api(url)
    print(f"Result: {res}")

if __name__ == "__main__":
    asyncio.run(test())
