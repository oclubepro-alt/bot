import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Monkey-patch config BEFORE any module imports it
import bot.utils.config as cfg
cfg.SCRAPERAPI_KEY = None
cfg.HTTP_PROXY = None
cfg.TELEGRAM_BOT_TOKEN = "mock"
cfg.TELEGRAM_CHANNEL_ID = "mock"
cfg.OPENAI_API_KEY = "mock"

import asyncio
from bot.services.product_extractor_v2 import extract_product_data_v2

async def main():
    res = await extract_product_data_v2('https://amzn.to/4tYSB3u')
    print('FINAL_URL:', res.get('final_url'))
    print('TITULO:', res.get('titulo'))
    print('PRECO:', res.get('preco'))
    print('CUPOM:', res.get('cupom'))
    print('METHOD:', res.get('source_method'))

if __name__ == '__main__':
    asyncio.run(main())
