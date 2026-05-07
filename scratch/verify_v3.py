import asyncio
import sys
sys.path.insert(0, '.')

from bot.services.product_extractor_v2 import extract_product_data_v2

async def test(url, label):
    print(f"\n[ {label} ]")
    d = await extract_product_data_v2(url)
    print(f"  Titulo: {d.get('titulo')}")
    print(f"  Preco: {d.get('preco')}")
    print(f"  Preco Original: {d.get('preco_original')}")
    print(f"  Method: {d.get('source_method')}")

async def main():
    # Test Amazon
    await test('https://amzn.to/48UetXo', 'AMAZON DIAPER')
    # Test ML
    await test('https://produto.mercadolivre.com.br/MLB-3513790568-tnis-de-treino-unissex-under-armour-tribase-reps-_JM', 'ML SNEAKER')

if __name__ == "__main__":
    asyncio.run(main())
