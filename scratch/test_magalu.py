import asyncio
import os
import sys
from dotenv import load_dotenv

# Mocking parts of the bot environment
sys.path.append(os.getcwd())
load_dotenv()

from bot.services.affiliate_link_service import injetar_link_afiliado
from bot.services.link_shortener import shorten_url

async def test():
    # Teste 1: Magalu
    url_magalu = "https://www.magazineluiza.com.br/smartphone-samsung-galaxy-s24-ultra-512gb-preto-titanium/p/237667800/te/s24u/"
    print(f"--- TESTE MAGALU ---")
    print(f"Original: {url_magalu}")
    link_afiliado = await injetar_link_afiliado(url_magalu)
    print(f"Injetado: {link_afiliado}")
    link_final = shorten_url(link_afiliado)
    print(f"Final (is.gd): {link_final}\n")
    
    # Teste 2: Amazon (para ver se encurta via is.gd e não TinyURL)
    url_amazon = "https://www.amazon.com.br/dp/B0CX92K9M6"
    print(f"--- TESTE AMAZON ---")
    print(f"Original: {url_amazon}")
    link_amazon = await injetar_link_afiliado(url_amazon)
    print(f"Injetado: {link_amazon}")
    link_final_amazon = shorten_url(link_amazon)
    print(f"Final (is.gd): {link_final_amazon}")

if __name__ == "__main__":
    asyncio.run(test())
