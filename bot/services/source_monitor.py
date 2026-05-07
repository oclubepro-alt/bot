"""
source_monitor.py - Monitora fontes cadastradas em data/sources.json,
coleta links de produtos encontrados e retorna os novos (não vistos).
"""
import logging
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from bot.services.dedup_store import is_seen
# Importamos o buscador de HTML robusto para fontes protegidas como Amazon
from bot.services.product_extractor_v2 import get_page_html

logger = logging.getLogger(__name__)

_SOURCES_PATH = Path(__file__).resolve().parents[2] / "data" / "sources.json"

# Padrões de URL que sugerem uma página de produto individual
_PRODUCT_URL_PATTERNS = re.compile(
    r"(/produto|/p/|/item/|/pd/|/product|/oferta|/-/|/dp/|/gp/|jm/|[?&]id=|/MLB-|/shopee\.com\.br/.*-i\.)",
    re.IGNORECASE
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/114.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
}


def load_sources() -> list[dict]:
    """Carrega a lista de fontes de data/sources.json."""
    logger.info(f"[MONITOR] Localizando fontes em: {_SOURCES_PATH.absolute()}")
    try:
        if _SOURCES_PATH.exists():
            content = _SOURCES_PATH.read_text(encoding="utf-8")
            sources = json.loads(content)
            active = [s for s in sources if s.get("active", False)]
            logger.info(f"[MONITOR] Sucesso: {len(sources)} totais, {len(active)} ativas.")
            return sources
        else:
            logger.error(f"[MONITOR] ERRO: Arquivo não existe em {_SOURCES_PATH}")
    except Exception as e:
        logger.error(f"[MONITOR] Erro ao carregar sources.json: {e}")
    return []


def _is_product_link(url: str) -> bool:
    """Heurística simples para identificar links de produto vs links de navegação."""
    return bool(_PRODUCT_URL_PATTERNS.search(url))


async def _extract_amazon_links_from_soup(soup: BeautifulSoup, base_url: str) -> list[str]:
    """
    Extrai links de produtos da Amazon de forma robusta, 
    olhando para ASINs e padrões de widgets de ofertas.
    """
    collected = set()
    
    # 1. Busca por links diretos que contenham ASIN (padrão /dp/ ou /gp/product/)
    # Ex: https://www.amazon.com.br/dp/B0C2RWN59H
    for tag in soup.find_all("a", href=True):
        href = tag["href"]
        # Tenta extrair ASIN da URL
        asin_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", href)
        if asin_match:
            asin = asin_match.group(1)
            collected.add(f"https://www.amazon.com.br/dp/{asin}")
            continue
            
        # Tenta extrair da query string se for um redirect interno (comum em ads)
        if "pd_rd_i=" in href:
            asin_match = re.search(r"pd_rd_i=([A-Z0-9]{10})", href)
            if asin_match:
                collected.add(f"https://www.amazon.com.br/dp/{asin_match.group(1)}")
                continue

    # 2. Busca por elementos com data-asin (comum em grids de ofertas Goldbox)
    for tag in soup.find_all(attrs={"data-asin": True}):
        asin = tag["data-asin"].strip()
        if len(asin) == 10 and asin.isalnum():
            collected.add(f"https://www.amazon.com.br/dp/{asin}")

    # 3. Busca em widgets de deals (às vezes o link está em um data-attribute)
    # Procuramos por qualquer coisa que pareça um ASIN de 10 caracteres em atributos
    for tag in soup.find_all(True):
        for attr, value in tag.attrs.items():
            if isinstance(value, str) and len(value) == 10 and value.isalnum() and value.isupper():
                # Heurística: ASINs da Amazon BR costumam começar com B0
                if value.startswith("B0") or value.startswith("85"):
                    collected.add(f"https://www.amazon.com.br/dp/{value}")

    return list(collected)


async def _collect_links_from_page(source_url: str) -> list[str]:
    """
    Visita uma URL de fonte e coleta links de produto.
    Usa pipeline robusto para Amazon e httpx para o resto.
    """
    collected = []
    base = f"{urlparse(source_url).scheme}://{urlparse(source_url).netloc}"
    is_amazon = "amazon" in source_url.lower()

    try:
        html = None
        if is_amazon:
            logger.info(f"[MONITOR] 🛡️ Usando pipeline robusto para fonte Amazon: {source_url[:50]}")
            # get_page_html já lida com ScraperAPI e Playwright
            html, method = await get_page_html(source_url)
        else:
            async with httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True) as client:
                resp = await client.get(source_url)
                if resp.status_code == 200:
                    html = resp.text

        if not html:
            logger.warning(f"[MONITOR] ❌ Falha ao obter HTML da fonte: {source_url}")
            return []

        soup = BeautifulSoup(html, "html.parser")
        
        if is_amazon:
            # Lógica especializada para Amazon
            amazon_links = await _extract_amazon_links_from_soup(soup, base)
            collected.extend(amazon_links)
        else:
            # Lógica genérica para outras lojas
            seen_hrefs: set[str] = set()
            for tag in soup.find_all("a", href=True):
                href = tag["href"].strip()
                if not href or href.startswith("#") or href.startswith("javascript"):
                    continue

                full_url = urljoin(base, href)
                clean = full_url.split("#")[0].split("?")[0]

                if clean in seen_hrefs:
                    continue
                seen_hrefs.add(clean)

                if _is_product_link(full_url):
                    collected.append(full_url)

        logger.info(
            f"[MONITOR] Fonte '{source_url}': {len(collected)} links encontrados."
        )
    except Exception as e:
        logger.error(f"[MONITOR] Erro na fonte '{source_url}': {e}")

    return collected


async def scan_sources() -> list[dict]:
    """
    Verifica todas as fontes ativas (Async).
    Retorna lista de links novos.
    """
    sources = load_sources()
    active = [s for s in sources if s.get("active", False)]

    if not active:
        logger.info("[MONITOR] Nenhuma fonte ativa encontrada.")
        return []

    logger.info(f"[MONITOR] Iniciando varredura de {len(active)} fonte(s)...")
    new_items = []

    for source in active:
        source_name = source.get("name", source["url"])
        logger.info(f"[MONITOR] Varrendo: {source_name}")

        links = await _collect_links_from_page(source["url"])

        for link in links:
            if is_seen(link):
                continue
            new_items.append({"url": link, "source_name": source_name})

    return new_items
