"""
amazon_api.py - Integracao com Amazon Creators API (v1)
Focado em extrair dados oficiais sem risco de bloqueio de scraping.
"""
import os
import httpx
import logging
import asyncio
import re
from datetime import datetime, timedelta
from bot.utils.config import (
    AMAZON_CREATORS_CLIENT_ID,
    AMAZON_CREATORS_CLIENT_SECRET,
    AFFILIATE_ID_AMAZON
)
from bot.utils.price_utils import _parse_price_to_float, format_api_price

logger = logging.getLogger(__name__)

class AmazonCreatorsAPI:
    def __init__(self):
        self.client_id = AMAZON_CREATORS_CLIENT_ID
        self.client_secret = AMAZON_CREATORS_CLIENT_SECRET
        self._token = None
        self._token_expires = None

    async def _get_access_token(self) -> str | None:
        """Obtem ou renova o token OAuth2 via LWA (Login with Amazon)."""
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token

        if not self.client_id or not self.client_secret:
            logger.error("[AMAZON_API] ❌ Client ID ou Secret nao configurados!")
            return None

        url = "https://api.amazon.com/auth/o2/token"
        
        # Lista de escopos para tentar. Prioriza o que estiver no .env
        env_scope = os.getenv("AMAZON_CREATORS_SCOPE")
        scopes_to_try = [env_scope] if env_scope else [None, "advertising::campaign_management", "amazon_creators", "profile"]
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            for scope in scopes_to_try:
                payload = {
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret
                }
                if scope:
                    payload["scope"] = scope
                
                logger.info(f"[AMAZON_API] 🔑 Solicitando token LWA (scope={scope or 'None'})...")
                
                try:
                    response = await client.post(url, data=payload)
                    
                    if response.status_code == 200:
                        data = response.json()
                        self._token = data["access_token"]
                        self._token_expires = datetime.now() + timedelta(seconds=data.get("expires_in", 3600) - 60)
                        logger.info(f"[AMAZON_API] ✅ Token obtido com sucesso (scope={scope or 'None'})")
                        return self._token
                    
                    err_data = response.json()
                    err_msg = str(err_data.get("error_description") or err_data.get("error") or "").lower()
                    
                    if "missing" in err_msg and "scope" in err_msg:
                        logger.warning(f"[AMAZON_API] ⚠️ Servidor exige scope. Tentando proximo...")
                        continue
                    elif "invalid" in err_msg and "scope" in err_msg:
                        logger.warning(f"[AMAZON_API] ⚠️ Scope '{scope}' invalido. Tentando proximo...")
                        continue
                    else:
                        logger.error(f"[AMAZON_API] ❌ Erro fatal no token: {response.status_code} - {err_msg}")
                        return None
                        
                except Exception as e:
                    logger.error(f"[AMAZON_API] ❌ Excecao no token: {e}")
                    return None
        
        return None

    def _extract_asin(self, url: str) -> str | None:
        """Extrai o ASIN da URL da Amazon."""
        # Regex robusto para ASIN
        asin_re = re.compile(r"/(?:dp|gp/product|product-reviews|aw/d|vdp)/([A-Z0-9]{10})", re.IGNORECASE)
        match = asin_re.search(url)
        if match:
            return match.group(1).upper()
        
        # Fallback para parâmetros de query
        match = re.search(r"[/\?&](B[A-Z0-9]{9})", url)
        if match:
            return match.group(1).upper()
            
        return None

    async def get_product_details(self, url: str) -> dict | None:
        """Consulta detalhes do produto via GetItems da Creators API."""
        from bot.utils.config import AMAZON_API_VERSION
        
        asin = self._extract_asin(url)
        if not asin:
            logger.warning(f"[AMAZON_API] ⚠️ ASIN nao encontrado: {url[:60]}")
            return None
        
        token = await self._get_access_token()
        if not token: return None

        marketplace = "www.amazon.com.br"
        # Usa a versao do config ou v1 como default
        version = AMAZON_API_VERSION or "v1"
        endpoint = f"https://creatorsapi.amazon.com/catalog/{version}/getItems"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-marketplace": marketplace
        }
        
        payload = {
            "itemIds": [asin],
            "itemIdType": "ASIN",
            "marketplace": marketplace,
            "partnerTag": AFFILIATE_ID_AMAZON or "associado-20"
        }

        try:
            logger.info(f"[AMAZON_API] 📡 Chamando API {version} para ASIN {asin}...")
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("items", [])
                    if items:
                        return self._map_response(items[0], asin)
                    else:
                        logger.warning(f"[AMAZON_API] ⚠️ ASIN {asin} nao retornou itens. Resposta: {data}")
                        return None
                else:
                    logger.error(f"[AMAZON_API] ❌ Erro API {resp.status_code}: {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"[AMAZON_API] ❌ Excecao GetItems: {e}")
            return None

    def _map_response(self, item_info: dict, asin: str) -> dict:
        """
        Mapeia o JSON da Amazon para o formato interno.
        Suporta tanto CamelCase (Creators API) quanto PascalCase (PA-API v5).
        """
        def get_field(obj, keys):
            if not obj or not isinstance(obj, dict): return None
            for k in keys:
                if k in obj: return obj[k]
            # Busca case-insensitive
            keys_lower = [k.lower() for k in keys]
            for k, v in obj.items():
                if k.lower() in keys_lower: return v
            return None

        product = {
            "titulo": f"Produto Amazon {asin}",
            "preco": "Preco nao disponivel",
            "preco_original": None,
            "imagem": None,
            "descricao": "",
            "store": "Amazon",
            "store_key": "amazon",
            "source_method": "AMAZON_CREATORS_API"
        }

        # 1. Titulo
        item_info_data = get_field(item_info, ["itemInfo", "ItemInfo"]) or item_info
        title_obj = get_field(item_info_data, ["title", "Title"])
        if title_obj:
            product["titulo"] = get_field(title_obj, ["displayValue", "DisplayValue"]) or product["titulo"]

        # 2. Imagem (Hierarquia: Primary -> HighRes -> Large -> Medium)
        images_obj = get_field(item_info_data, ["images", "Images"]) or {}
        primary = get_field(images_obj, ["primary", "Primary"])
        
        image_url = None
        if primary:
            # Prioridade para imagens de alta resolucao
            for size in ["highRes", "HighRes", "extraLarge", "ExtraLarge", "large", "Large", "medium", "Medium"]:
                size_obj = get_field(primary, [size])
                if size_obj:
                    image_url = get_field(size_obj, ["url", "URL"])
                    if image_url: break
        
        # Se nao achou na Primary, tenta Variants
        if not image_url:
            variants = get_field(images_obj, ["variants", "Variants"]) or []
            if variants and isinstance(variants, list):
                for v in variants:
                    for size in ["highRes", "HighRes", "large", "Large"]:
                        size_obj = get_field(v, [size])
                        if size_obj:
                            image_url = get_field(size_obj, ["url", "URL"])
                            if image_url: break
                    if image_url: break

        product["imagem"] = image_url

        # 3. Preco
        offers = get_field(item_info, ["offers", "Offers"]) or {}
        price_found = None
        orig_price = None

        # A. Tenta Summaries (LowestPrice e comum aqui)
        summaries = get_field(offers, ["summaries", "Summaries"]) or []
        if summaries and isinstance(summaries, list):
            lowest = get_field(summaries[0], ["lowestPrice", "LowestPrice"])
            if lowest:
                price_found = get_field(lowest, ["displayAmount", "DisplayAmount", "amount", "Amount", "value", "Value"])

        # B. Tenta Listings (BuyBox)
        if not price_found:
            listings = get_field(offers, ["listings", "Listings"]) or []
            if listings and isinstance(listings, list):
                listing = listings[0]
                price_info = get_field(listing, ["price", "Price"])
                if price_info:
                    # Preco de compra atual
                    price_found = (
                        get_field(price_info, ["displayAmount", "DisplayAmount"]) or
                        get_field(price_info, ["amount", "Amount"]) or 
                        get_field(price_info, ["value", "Value"])
                    )
                    # Preco original (se houver desconto)
                    savings = get_field(price_info, ["savings", "Savings"])
                    if savings:
                        # Se temos savings, buscamos listPrice para o preco "De"
                        list_price_info = get_field(listing, ["listPrice", "ListPrice"])
                        if list_price_info:
                            orig_price = get_field(list_price_info, ["amount", "Amount", "value", "Value", "displayAmount", "DisplayAmount"])
                        
                        # Se ainda nao temos orig_price mas temos o valor do desconto, calculamos
                        if not orig_price:
                            try:
                                p_float = _parse_price_to_float(str(price_found))
                                s_amount = get_field(savings, ["amount", "Amount", "value", "Value"])
                                if s_amount and p_float:
                                    orig_price = p_float + float(s_amount)
                            except: pass
                            except: pass

        # C. Fallback: ProductInfo (comum na Creators API v1)
        if not price_found:
            p_info = get_field(item_info, ["productInfo", "ProductInfo"]) or {}
            price_found = (
                get_field(p_info, ["price", "Price"]) or
                get_field(p_info, ["buyingPrice", "BuyingPrice"])
            )
            if isinstance(price_found, dict):
                price_found = get_field(price_found, ["displayAmount", "DisplayAmount", "amount", "Amount", "value", "Value"])
            
            if not orig_price:
                lp_obj = get_field(p_info, ["listPrice", "ListPrice"])
                if lp_obj:
                    orig_price = get_field(lp_obj, ["amount", "Amount", "value", "Value", "displayAmount", "DisplayAmount"])

        if price_found:
            product["preco"] = format_api_price(price_found)
        
        if orig_price:
            product["preco_original"] = format_api_price(orig_price)

        logger.info(f"[AMAZON_API] Mapeado ASIN {asin}: Titulo={product['titulo'][:40]}, Preco={product['preco']}, Imagem={'Sim' if product['imagem'] else 'Nao'}")

        return product

# Instância global
amazon_api = AmazonCreatorsAPI()
