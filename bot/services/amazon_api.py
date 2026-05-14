"""
amazon_api.py - Integração com Amazon Creators API (v1)
Focado em extrair dados oficiais sem risco de bloqueio de scraping.
"""
import os
import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from bot.utils.config import (
    AMAZON_CREATORS_CLIENT_ID,
    AMAZON_CREATORS_CLIENT_SECRET,
    AFFILIATE_ID_AMAZON
)

logger = logging.getLogger(__name__)

class AmazonCreatorsAPI:
    def __init__(self):
        self.client_id = AMAZON_CREATORS_CLIENT_ID
        self.client_secret = AMAZON_CREATORS_CLIENT_SECRET
        self._token = None
        self._token_expires = None

    async def _get_access_token(self) -> str | None:
        """Obtém ou renova o token OAuth2 via LWA (Login with Amazon)."""
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token

        if not self.client_id or not self.client_secret:
            logger.error("[AMAZON_API] ❌ Client ID ou Secret não configurados!")
            return None

        url = "https://api.amazon.com/auth/o2/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "advertising::campaign_management" # Escopo comum para Creators
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, data=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    self._token = data["access_token"]
                    expires_in = data.get("expires_in", 3600)
                    self._token_expires = datetime.now() + timedelta(seconds=expires_in - 300)
                    logger.info("[AMAZON_API] ✅ Token OAuth2 renovado")
                    return self._token
                else:
                    logger.error(f"[AMAZON_API] ❌ Erro no token: {resp.status_code} - {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"[AMAZON_API] ❌ Exceção no token: {e}")
            return None

    async def get_product_details(self, url: str) -> dict | None:
        """Consulta detalhes do produto via GetItems da Creators API."""
        import re
        from bot.utils.config import AMAZON_API_VERSION
        
        # Extrai ASIN
        asin_match = re.search(r"/(?:dp|gp/product|product-reviews|aw/d|vdp|d)/([A-Z0-9]{10})", url, re.I)
        if not asin_match:
            asin_match = re.search(r"[/\?&](B[A-Z0-9]{9})", url)

        if not asin_match:
            logger.warning(f"[AMAZON_API] ⚠️ ASIN não encontrado: {url[:60]}")
            return None
        
        asin = asin_match.group(1).upper()
        token = await self._get_access_token()
        if not token: return None

        marketplace = "www.amazon.com.br"
        # Usa a versão do config ou v1 como default
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
                        logger.warning(f"[AMAZON_API] ⚠️ ASIN {asin} não retornou itens. Resposta: {data}")
                        return None
                else:
                    logger.error(f"[AMAZON_API] ❌ Erro API {resp.status_code}: {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"[AMAZON_API] ❌ Exceção GetItems: {e}")
            return None

    def _map_response(self, item: dict, asin: str) -> dict:
        """Mapeia o objeto item da Amazon para o formato do bot, suportando diversas variantes."""
        # Suporte a case-insensitive para chaves comuns
        def get_field(obj, keys):
            if not obj or not isinstance(obj, dict): return None
            for k in keys:
                # Tenta exato, lowercase e PascalCase
                for variant in [k, k.lower(), k.capitalize()]:
                    if variant in obj: return obj[variant]
            return None

        item_info = get_field(item, ["itemInfo", "ItemInfo"]) or {}
        
        # 1. TÍTULO
        title_obj = get_field(item_info, ["title", "Title"]) or {}
        titulo = (
            get_field(title_obj, ["displayValue", "DisplayValue"]) or 
            get_field(title_obj, ["value", "Value"]) or 
            get_field(item, ["itemName", "ItemName", "title", "Title"])
        )
        
        # 2. IMAGEM (Estrutura PA-API v5 e Creators API v1)
        imagem = None
        images_obj = get_field(item_info, ["images", "Images"]) or {}
        
        # Tenta Primary -> Large -> URL
        primary = get_field(images_obj, ["primary", "Primary"])
        if primary:
            large = get_field(primary, ["large", "Large"])
            if large:
                imagem = get_field(large, ["url", "URL"])
        
        # Fallback 1: Primeira variante Large
        if not imagem:
            variants = get_field(images_obj, ["variants", "Variants"]) or []
            if variants and isinstance(variants, list):
                v_large = get_field(variants[0], ["large", "Large"])
                if v_large:
                    imagem = get_field(v_large, ["url", "URL"])

        # Fallback 2: Lista genérica de imagens (como estava antes)
        if not imagem:
            img_list = get_field(images_obj, ["images", "Images"]) or []
            if img_list and isinstance(img_list, list):
                try:
                    sorted_imgs = sorted(img_list, key=lambda x: get_field(x, ["width", "Width"]) or 0, reverse=True)
                    imagem = get_field(sorted_imgs[0], ["url", "URL"])
                except:
                    imagem = get_field(img_list[0], ["url", "URL"])

        # 3. PREÇOS
        preco_promo = None
        preco_orig = None
        
        # Tenta via Offers -> Listings
        offers = get_field(item, ["offers", "Offers"]) or {}
        listings = get_field(offers, ["listings", "Listings"]) or []
        
        if listings and isinstance(listings, list):
            listing = listings[0]
            price_info = get_field(listing, ["price", "Price"]) or {}
            amount = (
                get_field(price_info, ["amount", "Amount"]) or 
                get_field(price_info, ["value", "Value"]) or 
                get_field(price_info, ["displayAmount", "DisplayAmount"])
            )
            
            if amount:
                from bot.services.product_extractor_v2 import format_api_price
                preco_promo = format_api_price(amount)
                
                # Preço original (Savings ou listPrice)
                savings = get_field(listing, ["savings", "Savings"]) or {}
                s_amount = get_field(savings, ["amount", "Amount"]) or get_field(savings, ["value", "Value"])
                if s_amount and preco_promo:
                    try:
                        from bot.services.product_extractor_v2 import _parse_price_to_float
                        p_float = _parse_price_to_float(preco_promo)
                        s_float = float(s_amount)
                        preco_orig = format_api_price(p_float + s_float)
                    except: pass

        # Fallback de preço: ProductInfo (comum na Creators API)
        if not preco_promo:
            p_info = get_field(item_info, ["productInfo", "ProductInfo"]) or get_field(item, ["productInfo", "ProductInfo"]) or {}
            amount = (
                get_field(item, ["price", "Price"]) or 
                get_field(item, ["buyingPrice", "BuyingPrice"]) or 
                get_field(item, ["root_price"]) or
                get_field(p_info, ["price", "Price"]) or
                get_field(p_info, ["buyingPrice", "BuyingPrice"]) or
                get_field(p_info, ["listPrice", "ListPrice"])
            )
            
            if isinstance(amount, dict):
                amount = get_field(amount, ["amount", "Amount", "value", "Value", "displayAmount", "DisplayAmount"])

            if amount:
                from bot.services.product_extractor_v2 import format_api_price
                preco_promo = format_api_price(amount)
                
                # Tenta pegar preco_orig das economias
                try:
                    from bot.services.product_extractor_v2 import _parse_price_to_float
                    p_float = _parse_price_to_float(preco_promo)
                    savings_info = get_field(item, ["savings", "Savings"]) or get_field(p_info, ["savings", "Savings"]) or {}
                    savings_amount = get_field(savings_info, ["amount", "Amount", "value", "Value"])
                    if savings_amount and p_float:
                        s_float = float(savings_amount)
                        preco_orig = format_api_price(p_float + s_float)
                except: pass

        # Fallback final de preço original: listPrice direto
        if preco_promo and not preco_orig:
            p_info = get_field(item_info, ["productInfo", "ProductInfo"]) or {}
            lp_obj = get_field(p_info, ["listPrice", "ListPrice"])
            if lp_obj:
                lp_amount = get_field(lp_obj, ["amount", "Amount", "value", "Value", "displayAmount", "DisplayAmount"])
                if lp_amount:
                    from bot.services.product_extractor_v2 import format_api_price
                    preco_orig = format_api_price(lp_amount)

        # Se ainda não achou título, usa o ASIN
        if not titulo:
            titulo = f"Produto Amazon {asin}"

        logger.info(f"[AMAZON_API] Mapeado ASIN {asin}: Titulo={titulo[:40]}, Preço={preco_promo}, Imagem={'Sim' if imagem else 'Não'}")

        return {
            "titulo": titulo,
            "imagem": imagem,
            "preco": preco_promo or "Preço não disponível",
            "preco_original": preco_orig,
            "source_method": "AMAZON_CREATORS_API",
            "is_pix_price": False,
        }

# Instância global
amazon_api = AmazonCreatorsAPI()
