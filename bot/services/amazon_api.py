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
        """Mapeia o objeto item da Amazon para o formato do bot."""
        # A estrutura da Creators API costuma ser: itemInfo -> title, images, etc.
        item_info = item.get("itemInfo", {})
        title_obj = item_info.get("title", {})
        titulo = title_obj.get("displayValue") or title_obj.get("value")
        
        # Imagens
        images_obj = item_info.get("images", {})
        img_list = images_obj.get("images", [])
        imagem = None
        if img_list:
            try:
                # Prioriza imagens maiores
                sorted_imgs = sorted(img_list, key=lambda x: x.get("width", 0), reverse=True)
                imagem = sorted_imgs[0].get("url")
            except:
                imagem = img_list[0].get("url")
        
        # Preços (Offers -> Listings)
        offers = item.get("offers", {})
        listings = offers.get("listings", [])
        
        preco_promo = None
        preco_orig = None
        
        if listings:
            # Tenta pegar o preço da primeira listagem (geralmente a oferta principal)
            listing = listings[0]
            price_info = listing.get("price", {})
            
            # Tenta vários campos comuns
            amount = price_info.get("amount") or price_info.get("value")
            if not amount:
                # Algumas versões retornam displayAmount
                display = price_info.get("displayAmount")
                if display:
                    amount = display
            
            if amount:
                from bot.services.product_extractor_v2 import format_api_price
                preco_promo = format_api_price(amount)
                
                # Preço original (Savings ou listPrice)
                # Tenta recompor o original se houver savings
                savings = listing.get("savings", {})
                s_amount = savings.get("amount") or savings.get("value")
                if s_amount and preco_promo:
                    try:
                        # Se temos o promo e o desconto, podemos sugerir o original
                        from bot.services.product_extractor_v2 import _parse_price_to_float
                        p_float = _parse_price_to_float(preco_promo)
                        s_float = float(s_amount)
                        if p_float:
                            preco_orig = format_api_price(p_float + s_float)
                    except:
                        pass
        
        # Fallback para productInfo se preço não estiver em offers
        if not preco_promo:
            prod_info = item_info.get("productInfo", {})
            lp = prod_info.get("listPrice", {})
            lp_amount = lp.get("amount") or lp.get("value")
            if lp_amount:
                from bot.services.product_extractor_v2 import format_api_price
                preco_promo = format_api_price(lp_amount)

        # Se ainda não achou título, usa o ASIN
        if not titulo:
            titulo = f"Produto Amazon {asin}"

        logger.info(f"[AMAZON_API] Mapeado ASIN {asin}: Titulo={titulo[:40]}, Preço={preco_promo}")

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
