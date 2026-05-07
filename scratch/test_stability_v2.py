
import asyncio
import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

def _parse_price_to_float(text: str):
    if not text: return None
    text = re.sub(r"\(.*?\)", "", str(text))
    cleaned = re.sub(r"[^\d,.]", "", text)
    if not cleaned: return None
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(".", "")
    try: return float(cleaned)
    except: return None

def _is_valid_price_tag(tag):
    if not tag: return False
    text_context = tag.get_text(strip=True).lower()
    unit_keywords = ["unidade", "contagem", "/", "cada", " ml", " kg", " g", " l"]
    return not any(k in text_context for k in unit_keywords)

def extract_title_fallback(base_url):
    path = urlparse(base_url).path
    titulo = None
    if "/dp/" in path or "/gp/" in path:
        parts = [p for p in path.split('/') if p]
        idx = -1
        if "dp" in parts: idx = parts.index("dp")
        elif "product" in parts: idx = parts.index("product")
        if idx > 0:
            slug = parts[idx-1]
            if len(slug) > 5 and '-' in slug:
                titulo = slug.replace('-', ' ').strip().title()
    return titulo

# Tests
print("--- TEST: AMAZON SLUG ---")
url1 = "https://www.amazon.com.br/Fralda-Pampers-Confort-Sec-Tamanho-XG-148-Unidades/dp/B09DQ6CMG2"
print(f"URL: {url1} -> Title: {extract_title_fallback(url1)}")

print("\n--- TEST: UNIT PRICE FILTER ---")
# Simulating a common Amazon case
html = '<span class="a-price"><span class="a-offscreen">R$ 150,00</span></span> <span class="a-size-small">R$ 1,02 / unidade</span>'
soup = BeautifulSoup(html, 'html.parser')
for tag in soup.select('.a-offscreen'):
    valid = _is_valid_price_tag(tag)
    print(f"Tag: {tag.get_text()} | Valid: {valid}")

html_bad = '<span class="a-price"><span class="a-offscreen">R$ 1,02 / unidade</span></span>'
soup_bad = BeautifulSoup(html_bad, 'html.parser')
for tag in soup_bad.select('.a-offscreen'):
    valid = _is_valid_price_tag(tag)
    print(f"Tag: {tag.get_text()} | Valid (should be false): {valid}")
