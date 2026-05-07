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

print(f"Testing URL: {url}")
res = requests.get(url, headers=headers, allow_redirects=True)
print(f"Status Code: {res.status_code}")
print(f"Final URL: {res.url}")

soup = BeautifulSoup(res.text, "html.parser")

def get_meta(property):
    tag = soup.find("meta", property=property) or soup.find("meta", {"name": property})
    return tag["content"] if tag else None

print(f"OG Title: {get_meta('og:title')}")
print(f"OG Image: {get_meta('og:image')}")
print(f"OG Price: {get_meta('product:price:amount') or get_meta('og:price:amount')}")

# Try API
ml_id_match = re.search(r"wid=(MLB\d+)", url)
if not ml_id_match:
    ml_id_match = re.search(r"MLB-?(\d+)", url)

if ml_id_match:
    ml_id = ml_id_match.group(1)
    if not ml_id.startswith("MLB"): ml_id = f"MLB{ml_id}"
    print(f"Detected ID: {ml_id}")
    api_url = f"https://api.mercadolibre.com/items/{ml_id}"
    r = requests.get(api_url)
    print(f"API Items Status: {r.status_code}")
    if r.status_code == 200:
        print(f"API Title: {r.json().get('title')}")
        print(f"API Price: {r.json().get('price')}")
    else:
        # Try products API if /p/
        prod_match = re.search(r"/p/(MLB\d+)", url)
        if prod_match:
            prod_id = prod_match.group(1)
            print(f"Detected Product ID: {prod_id}")
            api_url = f"https://api.mercadolibre.com/products/{prod_id}"
            r = requests.get(api_url)
            print(f"API Products Status: {r.status_code}")
            if r.status_code == 200:
                print(f"API Title: {r.json().get('name')}")
                # Products API might not have price directly or it might be in 'buy_box_winner'
                print(f"API Buy Box Price: {r.json().get('buy_box_winner', {}).get('price')}")
