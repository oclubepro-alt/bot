"""
Script de diagnóstico: testa extração de preço Amazon.
Uso: python scratch/test_amazon.py "https://www.amazon.com.br/dp/XXXXXX"
"""
import asyncio
import sys
import os
import logging

# Adiciona o raiz ao path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(name)s | %(message)s"
)

async def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.amazon.com.br/dp/B08N5WRWNW"
    print(f"\n{'='*60}")
    print(f"Testando URL: {url}")
    print(f"{'='*60}\n")

    from bot.services.product_extractor_v2 import extract_product_data_v2
    result = await extract_product_data_v2(url)

    print(f"\n{'='*60}")
    print("RESULTADO FINAL:")
    print(f"  Título   : {result.get('titulo')}")
    print(f"  Preço    : {result.get('preco')}")
    print(f"  Original : {result.get('preco_original')}")
    print(f"  Cupom    : {result.get('cupom')}")
    print(f"  Método   : {result.get('source_method')}")
    print(f"  Loja     : {result.get('store')} ({result.get('store_key')})")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    asyncio.run(main())
