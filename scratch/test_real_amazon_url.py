import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.services.product_extractor_v2 import extract_product_data_v2

async def main():
    url = "https://www.amazon.com.br/dp/B0D1XLFMQZ"
    result = await extract_product_data_v2(url)
    print("EXTRACTED:")
    import pprint
    pprint.pprint(result)

if __name__ == "__main__":
    asyncio.run(main())
