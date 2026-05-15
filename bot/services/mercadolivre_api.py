"""
mercadolivre_api.py - Integracao com API Oficial do Mercado Livre
Focado em extrair dados oficiais sem risco de bloqueio de scraping.
"""
import os
import httpx
import logging
import asyncio
import re
from datetime import datetime, timedelta
from bot.utils.config import (
    ML_APP_ID,
    ML_CLIENT_SECRET,
    ML_TG_TOKEN
)

logger = logging.getLogger(__name__)

class MercadoLivreAPI:
    def __init__(self):
        self.app_id = ML_APP_ID
        self.client_secret = ML_CLIENT_SECRET
        self._access_token = os.getenv("ML_ACCESS_TOKEN", "").strip()
        self._refresh_token = os.getenv("ML_REFRESH_TOKEN", "").strip()
        self._token_expires = None

    async def _get_access_token(self) -> str | None:
        """Obtem ou renova o token OAuth2."""
        # Se ja temos um token valido em memoria, usa ele
        if self._access_token and self._token_expires and datetime.now() < self._token_expires:
            return self._access_token

        if not self.app_id or not self.client_secret:
            logger.error("[ML_API] ❌ App ID ou Secret nao configurados!")
            return None

        url = "https://api.mercadolibre.com/oauth/token"
        
        # 1. Se temos um refresh_token, tenta renovar
        if self._refresh_token:
            logger.info("[ML_API] 🔄 Tentando renovar token via refresh_token...")
            payload = {
                "grant_type": "refresh_token",
                "client_id": self.app_id,
                "client_secret": self.client_secret,
                "refresh_token": self._refresh_token
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, data=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        self._access_token = data["access_token"]
                        self._refresh_token = data.get("refresh_token", self._refresh_token)
                        self._token_expires = datetime.now() + timedelta(seconds=data.get("expires_in", 21600) - 60)
                        logger.info("[ML_API] ✅ Token renovado com sucesso")
                        return self._access_token
                    else:
                        logger.warning(f"[ML_API] ⚠️ Falha ao renovar token: {resp.text}")
                        # Se falhou, limpa o refresh_token para tentar o inicial ou client_credentials
                        self._refresh_token = None
            except Exception as e:
                logger.error(f"[ML_API] ❌ Excecao ao renovar token: {e}")

        # 2. Se temos o TG_TOKEN (code) inicial, tenta trocar por tokens
        if ML_TG_TOKEN and not self._access_token:
            logger.info(f"[ML_API] 🔑 Trocando TG_TOKEN por tokens reais...")
            payload = {
                "grant_type": "authorization_code",
                "client_id": self.app_id,
                "client_secret": self.client_secret,
                "code": ML_TG_TOKEN,
                "redirect_uri": "https://google.com" # Como no arquivo fornecido
            }
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, data=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        self._access_token = data["access_token"]
                        self._refresh_token = data.get("refresh_token")
                        self._token_expires = datetime.now() + timedelta(seconds=data.get("expires_in", 21600) - 60)
                        logger.info("[ML_API] ✅ Tokens obtidos com sucesso via TG_TOKEN")
                        logger.info(f"[ML_API] 💡 IMPORTANTE: Atualize seu ML_REFRESH_TOKEN no Railway com: {self._refresh_token}")
                        return self._access_token
                    else:
                        logger.warning(f"[ML_API] ⚠️ Falha ao trocar TG_TOKEN: {resp.text}")
            except Exception as e:
                logger.error(f"[ML_API] ❌ Excecao ao trocar TG_TOKEN: {e}")

        # 3. Fallback para client_credentials (dados publicos)
        logger.info("[ML_API] 🔑 Tentando client_credentials (fallback)...")
        payload = {
            "grant_type": "client_credentials",
            "client_id": self.app_id,
            "client_secret": self.client_secret
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, data=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    self._access_token = data["access_token"]
                    self._token_expires = datetime.now() + timedelta(seconds=data.get("expires_in", 21600) - 60)
                    logger.info("[ML_API] ✅ Token obtido via client_credentials")
                    return self._access_token
                else:
                    logger.error(f"[ML_API] ❌ Erro total na autenticacao ML: {resp.text}")
        except Exception as e:
            logger.error(f"[ML_API] ❌ Excecao client_credentials: {e}")

        return None

    def _extract_ml_id(self, url: str) -> str | None:
        """Extrai o ID do item do Mercado Livre (ex: MLB12345678)."""
        # Padrao: MLB-12345678, MLB12345678, etc.
        match = re.search(r"(ML[A-Z]\-?\d{8,15})", url, re.I)
        if match:
            return match.group(1).replace("-", "")
        return None

    async def get_product_details(self, url: str) -> dict | None:
        """Consulta detalhes do produto via API do Mercado Livre."""
        item_id = self._extract_ml_id(url)
        if not item_id:
            logger.warning(f"[ML_API] ⚠️ ID nao encontrado na URL: {url[:60]}")
            return None
        
        token = await self._get_access_token()
        
        endpoint = f"https://api.mercadolibre.com/items/{item_id}"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        
        try:
            logger.info(f"[ML_API] 📡 Consultando Item {item_id}...")
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(endpoint, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    return self._map_response(data)
                else:
                    logger.error(f"[ML_API] ❌ Erro API {resp.status_code}: {resp.text}")
                    return None
        except Exception as e:
            logger.error(f"[ML_API] ❌ Excecao ML Items API: {e}")
            return None

    def _map_response(self, data: dict) -> dict:
        """Mapeia o JSON do Mercado Livre para o formato interno."""
        from bot.utils.price_utils import _clean_price
        
        product = {
            "titulo": data.get("title", "Produto Mercado Livre"),
            "preco": _clean_price(str(data.get("price"))) if data.get("price") else "Preco nao disponivel",
            "preco_original": _clean_price(str(data.get("original_price"))) if data.get("original_price") else None,
            "imagem": data.get("thumbnail") or (data.get("pictures", [{}])[0].get("url") if data.get("pictures") else None),
            "store": "Mercado Livre",
            "store_key": "mercadolivre",
            "source_method": "ML_API_OFICIAL"
        }
        
        # Tenta pegar uma imagem maior se possivel
        if data.get("pictures") and len(data["pictures"]) > 0:
            # Pega a primeira imagem de alta qualidade
            product["imagem"] = data["pictures"][0].get("secure_url") or data["pictures"][0].get("url")

        logger.info(f"[ML_API] Mapeado: {product['titulo'][:40]} | Preco: {product['preco']}")
        return product

# Instância global
mercadolivre_api = MercadoLivreAPI()
