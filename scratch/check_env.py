import os
from dotenv import load_dotenv

load_dotenv()

vars = [
    "AFFILIATE_ID_AMAZON",
    "AFFILIATE_ID_ML",
    "AFFILIATE_ID_MAGALU",
    "AFFILIATE_ID_NETSHOES",
    "AFFILIATE_ID_SHOPEE",
    "AUTO_APPROVE",
    "ADMIN_IDS",
    "TELEGRAM_CHANNEL_ID"
]

print("--- ENV VARS ---")
for v in vars:
    val = os.getenv(v)
    print(f"{v}: {val}")
