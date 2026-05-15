
import asyncio
from bot.services.affiliate_link_service import injetar_link_afiliado
import os

# Simula ID configurado
os.environ["AFFILIATE_ID_ML"] = "55765126"

async def test():
    url = "https://www.mercadolivre.com.br/social/cupomonline?matt_word=cupomonline&matt_tool=53340084&forceInApp=true&ref=BKmeziKJR%2B1XV8KJ8soLLVviZmKZKTM5oVv%2BZcnfewWWVP9RFOPkFqhJFaJdxyVBxEVkAA7chHpWab3hDspKajjYqioF23Amf1Fy8hESoLMHfm38YC18x9hQO3BzpSIXyAoX4RX5jSk%2FJ04EuOuioUJiTEMAU6I21Loojm2iB2MfZkUUsjhZGBR578hFdEXbXmbNAs4%3D"
    result = await injetar_link_afiliado(url)
    print(f"Original: {url[:80]}...")
    print(f"Resultado: {result[:80]}...")
    if "55765126" in result:
        print("OK: ID encontrado no resultado")
    else:
        print("FAIL: ID nao encontrado")

asyncio.run(test())
