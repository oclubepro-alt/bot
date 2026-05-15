
import httpx
import asyncio
from bs4 import BeautifulSoup

async def test_search():
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }
    url = "https://www.magazineluiza.com.br/busca/237242100"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            html = resp.text
            print(f"HTML Length: {len(html)}")
            if "captcha" in html.lower():
                print("CAPTCHA DETECTED")
            else:
                soup = BeautifulSoup(html, 'html.parser')
                # Procura por qualquer container de produto
                products = soup.select('a[data-testid="product-card-container"]')
                print(f"Products found: {len(products)}")
                for p in products[:1]:
                    print(f"Title: {p.select_one('h3').get_text(strip=True) if p.select_one('h3') else 'N/A'}")
                    print(f"Price: {p.select_one('[data-testid=\"price-value\"]').get_text(strip=True) if p.select_one('[data-testid=\"price-value\"]') else 'N/A'}")

if __name__ == "__main__":
    asyncio.run(test_search())
