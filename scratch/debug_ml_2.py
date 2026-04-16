import requests
from bs4 import BeautifulSoup
import re
import json

url = "https://www.mercadolivre.com.br/celular-samsung-galaxy-a17-5g-com-ia-128gb-4gb-ram-cm-de-50mp-tela-de-67-nfc-ip54-preto/p/MLB55027309?pdp_filters=deal%3AMLB779362-1#polycard_client=offers&deal_print_id=908b25d5-2522-44a1-a671-19432a12e2cf&position=3&tracking_id=57869f27-ffbd-4137-878d-ada1055526b8&wid=MLB6543431512&sid=offers"

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

res = requests.get(url, headers=headers, allow_redirects=True)
res.encoding = 'utf-8' # Force utf-8
soup = BeautifulSoup(res.text, "html.parser")

def extract_json_ld(soup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "Product": return item
            elif data.get("@type") == "Product": return data
        except Exception: continue
    return {}

jld = extract_json_ld(soup)
print(f"JLD Name: {jld.get('name')}")
print(f"JLD Offers Price: {jld.get('offers', {}).get('price') if isinstance(jld.get('offers'), dict) else 'N/A'}")

tag = soup.find("meta", property="og:title")
if tag:
    print(f"OG Title Raw: {tag['content']}")
    clean_t = re.sub(r"\s-\sR\$.*", "", tag['content'])
    clean_t = re.sub(r"\sno\sMercado\sLivre.*", "", clean_t, flags=re.IGNORECASE)
    print(f"OG Title Clean: {clean_t.strip()}")

# Look for price scripts
scripts = soup.find_all("script")
for s in scripts:
    if s.string and '"price":' in s.string:
        match = re.search(r'"price":\s*(\d+)', s.string)
        if match:
             print(f"Found price in script: {match.group(1)}")
