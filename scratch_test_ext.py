import asyncio
import sys
import os
import logging

logging.basicConfig(level=logging.INFO)

os.environ["TELEGRAM_BOT_TOKEN"] = "fake"
os.environ["TELEGRAM_CHANNEL_ID"] = "fake"
os.environ["OPENAI_API_KEY"] = "fake"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.services.product_extractor_v2 import extract_product_data_v2

async def main():
    url = "https://www.amazon.com.br/dp/B09B8VGCR8"
    result = await extract_product_data_v2(url)
    print("EXTRACTED:")
    import pprint
    pprint.pprint(result)

if __name__ == "__main__":
    asyncio.run(main())
