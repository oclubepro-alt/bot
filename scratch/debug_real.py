import asyncio
import sys
sys.path.insert(0, '.')

from bot.services.product_extractor_v2 import extract_product_data_v2, _is_valid_price_tag, _parse_price_to_float

async def test(url, label):
    print(f"\n{'='*60}\n[{label}]")
    d = await extract_product_data_v2(url)
    print(f"  titulo        : {d.get('titulo')}")
    print(f"  preco         : {d.get('preco')}")
    print(f"  preco_original: {d.get('preco_original')}")
    print(f"  source_method : {d.get('source_method')}")
    print(f"  erro          : {d.get('erro')}")

# Quick unit tests
print("--- UNIT TESTS ---")
print("xa0 parse:", _parse_price_to_float("R\xa0189,90"))   # should be 189.9
print("R$1,28 parse:", _parse_price_to_float("R$1,28"))     # should be 1.28

async def main():
    await test("https://amzn.to/48UetXo", "AMAZON FRALDA")

asyncio.run(main())
