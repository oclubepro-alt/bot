import os
import requests
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

LOMADEE_BASE_URL = "https://api-beta.lomadee.com.br"

# Palavras a ignorar na busca
STOPWORDS = {
    "de", "do", "da", "em", "com", "para", "por", "e", "a", "o",
    "um", "uma", "no", "na", "os", "as", "se", "ao", "bar", "ml",
    "cm", "kg", "p", "s", "g", "l"
}

def extrair_termo_busca(url: str) -> str:
    path = urlparse(url).path
    slug = path.strip("/").split("/")[0]  # pegar só o primeiro segmento
    palavras = slug.replace("-", " ").split()
    palavras_filtradas = [p for p in palavras if p.lower() not in STOPWORDS and len(p) > 2]
    termo = " ".join(palavras_filtradas[:4])  # máximo 4 palavras
    logger.info(f"[LOMADEE] 🔍 Termo de busca gerado: '{termo}'")
    return termo

def get_headers():
    return {"x-api-key": os.getenv("LOMADEE_API_KEY")}

def buscar_produto_lomadee(search_term: str, limit: int = 10) -> list:
    """
    Busca produtos na Lomadee por nome.
    Retorna lista de produtos com nome, imagem, preço e link.
    """
    try:
        resp = requests.get(
            f"{LOMADEE_BASE_URL}/affiliate/products",
            headers=get_headers(),
            params={
                "search": search_term,
                "limit": limit,
                "isAvailable": True
            },
            timeout=15
        )
        if resp.status_code == 200:
            produtos = resp.json().get("data", [])
            resultado = []
            for p in produtos:
                preco_centavos = None
                try:
                    # Tenta pegar o preço da primeira opção
                    preco_centavos = p["options"][0]["pricing"][0]["price"]
                except Exception:
                    pass
                
                resultado.append({
                    "nome": p.get("name", "Produto"),
                    "imagem": p.get("images", [{}])[0].get("url"),
                    "link": p.get("url"),
                    "preco": f"R$ {preco_centavos/100:.2f}".replace(".", ",") if preco_centavos else "Preço indisponível",
                    "disponivel": p.get("available", False)
                })
            logger.info(f"[LOMADEE] ✅ {len(resultado)} produtos encontrados para '{search_term}'")
            return resultado
        else:
            logger.error(f"[LOMADEE] ❌ Erro {resp.status_code}: {resp.text[:200]}")
            return []
    except Exception as e:
        logger.error(f"[LOMADEE] ❌ Exceção: {e}")
        return []
