
import asyncio
import sys
sys.path.insert(0, '.')

from bot.services.product_extractor_v2 import extract_product_data_v2, _parse_price_to_float

async def test(url, label):
    print(f"\n[ {label} ]")
    d = await extract_product_data_v2(url)
    print(f"  Titulo: {d.get('titulo')}")
    print(f"  Preco: {d.get('preco')}")
    print(f"  Method: {d.get('source_method')}")
    # Se o título contiver 'parece que você', o teste falhou
    if d.get('titulo') and 'parece que você' in d.get('titulo').lower():
        print("  FAIL: Block message leaked into title!")
    else:
        print("  OK: Title is either correct or fallback-protected.")

async def main():
    # Test cases for price parsing
    print("--- PRICE PARSING TESTS ---")
    prices = ["399.00", "1.299,90", "91,99", "1.020"]
    for p in prices:
        print(f"  {p} -> {_parse_price_to_float(p)}")

    # Real link test (Magalu)
    # Cafeteira Arno Nescafe Dolce Gusto
    url_magalu = "https://www.magazineluiza.com.br/cafeteira-expresso-arno-nescafe-dolce-gusto-genio-s-basic-de-capsula-15-bar/p/023318000/ep/cadc/"
    await test(url_magalu, "MAGALU CAFETEIRA")

if __name__ == "__main__":
    asyncio.run(main())
