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
        endpoint = "https://creatorsapi.amazon.com/catalog/v1/getItems"
        
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
        """Mapeia o objeto item da Amazon para o formato do bot."""
        # A estrutura da Creators API v1 costuma ser: itemInfo -> title, images, etc.
        item_info = item.get("itemInfo", {})
        title_obj = item_info.get("title", {})
        titulo = title_obj.get("displayValue") or title_obj.get("value")
        
        # Imagens
        images_obj = item_info.get("images", {})
        # Tenta pegar Large, depois Medium, depois Small
        img_list = images_obj.get("images", [])
        imagem = None
        if img_list:
            # Ordena por largura decrescente
            try:
                sorted_imgs = sorted(img_list, key=lambda x: x.get("width", 0), reverse=True)
                imagem = sorted_imgs[0].get("url")
            except:
                imagem = img_list[0].get("url")
        
        # Preços (Buying Options)
        offers = item.get("offers", {})
        listings = offers.get("listings", [])
        
        preco_promo = None
        preco_orig = None
        
        if listings:
            price_info = listings[0].get("price", {})
            amount = price_info.get("amount")
            if amount:
                from bot.services.product_extractor_v2 import format_api_price
                preco_promo = format_api_price(amount)
                
                # Preço original (Saving/Savings)
                savings = listings[0].get("savings", {})
                if savings:
                    # Tenta recompor o original somando o desconto
                    # Ou busca no listPrice se existir na estrutura
                    pass

            # Fallback para listPrice se existir na estrutura
            # (Estrutura da PA-API 5.0 é diferente, adaptando para Creators)
            # Na Creators API v1, costuma estar em listings[0].price
        
        # Se não achou título, usa o ASIN como fallback parcial
        if not titulo:
            titulo = f"Produto Amazon {asin}"

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
