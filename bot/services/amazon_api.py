import logging
import httpx
import asyncio
from datetime import datetime, timedelta
from bot.utils.config import (
    AMAZON_CREATORS_CLIENT_ID,
    AMAZON_CREATORS_CLIENT_SECRET,
    AFFILIATE_ID_AMAZON
)

logger = logging.getLogger(__name__)

class AmazonCreatorsAPI:
    """
    Serviço para integração com a nova Amazon Creators API (sucessora da PA-API).
    Implementa OAuth2 Client Credentials e consulta de produtos (GetItems).
    """
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AmazonCreatorsAPI, cls).__new__(cls)
            cls._instance._token = None
            cls._instance._token_expires = None
        return cls._instance

    async def _get_access_token(self) -> str | None:
        """Obtém ou renova o token OAuth2."""
        if self._token and self._token_expires and datetime.now() < self._token_expires:
            return self._token

        if not AMAZON_CREATORS_CLIENT_ID or not AMAZON_CREATORS_CLIENT_SECRET:
            logger.warning("[AMAZON_API] ❌ Credenciais (ID/SECRET) não configuradas no .env")
            return None

        url = "https://api.amazon.com/auth/o2/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": AMAZON_CREATORS_CLIENT_ID,
            "client_secret": AMAZON_CREATORS_CLIENT_SECRET,
            "scope": "creatorsapi::default"
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, data=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    self._token = data["access_token"]
                    # Expira em ~1 hora, subtraímos 5 min por segurança
                    expires_in = data.get("expires_in", 3600)
                    self._token_expires = datetime.now() + timedelta(seconds=expires_in - 300)
                    logger.info("[AMAZON_API] ✅ Token OAuth2 renovado com sucesso")
                    return self._token
                else:
                    logger.error(f"[AMAZON_API] ❌ Erro ao obter token: {resp.status_code} - {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"[AMAZON_API] ❌ Exceção ao obter token: {e}")
            return None

    async def get_product_details(self, url: str) -> dict | None:
        """
        Consulta detalhes do produto via GetItems da Creators API.
        Extrai o ASIN da URL automaticamente.
        """
        import re
        # Extrai ASIN (Padrão: /dp/B0... ou /product/B0...)
        asin_match = re.search(r'/(?:dp|gp/product|product)/([A-Z0-9]{10})', url)
        if not asin_match:
            logger.warning(f"[AMAZON_API] ⚠️ ASIN não encontrado na URL: {url[:80]}")
            return None
        
        asin = asin_match.group(1)
        token = await self._get_access_token()
        if not token:
            return None

        # Marketplace e Endpoint (Brasil)
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
                    if not items:
                        logger.warning(f"[AMAZON_API] ⚠️ Produto {asin} não encontrado na API")
                        return None
                    
                    item = items[0]
                    # Mapeamento de campos conforme Creators API
                    # Nota: A estrutura exata pode variar, adaptando para o mais comum
                    product_info = item.get("productInfo", {})
                    buying_options = item.get("buyingOptions", [])
                    
                    titulo = product_info.get("title")
                    # Imagem: tenta pegar a Large ou a primeira disponível
                    images = product_info.get("images", [])
                    imagem = None
                    if images:
                        # Tenta pegar a maior imagem baseada na largura
                        try:
                            sorted_images = sorted(images, key=lambda x: x.get("width", 0), reverse=True)
                            imagem = sorted_images[0].get("url")
                        except Exception:
                            imagem = images[0].get("url")
                    
                    # Preço: Pega da primeira buying option
                    preco_promo = None
                    preco_orig = None
                    if buying_options:
                        price_obj = buying_options[0].get("price", {})
                        amount = price_obj.get("amount")
                        currency = price_obj.get("currency", "BRL")
                        
                        if amount:
                            # Formata como R$ XX,XX
                            from bot.services.product_extractor_v2 import format_api_price
                            preco_promo = format_api_price(amount)
                            
                            # Preço de lista (original) se existir
                            list_price = buying_options[0].get("listPrice", {}).get("amount")
                            if list_price:
                                preco_orig = format_api_price(list_price)

                    brand = product_info.get("brand")
                    features_list = product_info.get("features", [])
                    features = " ".join(features_list) if features_list else None
                    
                    if titulo:
                        logger.info(f"[AMAZON_API] ✅ Sucesso via API | {titulo[:50]}")
                        return {
                            "titulo": titulo,
                            "imagem": imagem,
                            "preco": preco_promo or "Preço não disponível",
                            "preco_original": preco_orig,
                            "brand": brand,
                            "features": features_list,
                            "descricao": features,
                            "source_method": "AMAZON_CREATORS_API",
                            "is_pix_price": False,
                        }
                else:
                    logger.warning(f"[AMAZON_API] ❌ API retornou erro {resp.status_code}: {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"[AMAZON_API] ❌ Exceção na chamada GetItems: {e}")
            return None

amazon_api = AmazonCreatorsAPI()
