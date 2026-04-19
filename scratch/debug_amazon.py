import requests
from bs4 import BeautifulSoup
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8',
    'Connection': 'keep-alive',
}
r = requests.get('https://www.amazon.com.br/dp/B09DQ6CMG2', headers=headers, allow_redirects=True)
soup = BeautifulSoup(r.text, 'html.parser')

print("=== PRICE TAGS com contexto pai ===")
for tag in soup.select('.a-price .a-offscreen'):
    val = tag.get_text(strip=True)
    parent_text = ''
    p = tag.parent
    for _ in range(8):
        if p:
            parent_text = p.get_text(strip=True).lower()[:200]
            p = p.parent
    print(f"  VAL={val!r} | CONTEXT_SNIPPET={parent_text[:120]!r}")
    print()
