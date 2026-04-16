"""
link_converter.py - Serviço para converter e encurtar links em blocos de texto
"""
import re
import logging
from bot.utils.url_resolver import resolve_url
from bot.services.affiliate_injector import get_affiliate_url
from bot.services.link_shortener import shorten_for_publication
from bot.utils.detect_store import detect_store

logger = logging.getLogger(__name__)

# Regex para encontrar URLs em texto
URL_REGEX = re.compile(
    r'(https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*))'
)

async def convert_links_in_text(text: str) -> str:
    """
    Identifica URLs no texto, resolve, aplica afiliado e encurta.
    Retorna o texto com os links substituídos.
    """
    if not text:
        return text

    urls = URL_REGEX.findall(text)
    if not urls:
        return text

    # Remove duplicatas mantendo a ordem
    unique_urls = list(dict.fromkeys(urls))
    
    transformed_text = text
    
    for original_url in unique_urls:
        try:
            logger.info(f"[LINK_CONVERTER] Processando link: {original_url[:50]}")
            
            # 1. Resolve a URL (para saber a loja real e pegar a URL limpa)
            resolved_url = resolve_url(original_url)
            
            # 2. Detecta a loja
            _, store_key = detect_store(resolved_url)
            
            # 3. Injeta o ID de afiliado
            affiliate_url = get_affiliate_url(
                original_url=original_url,
                resolved_url=resolved_url,
                store_key=store_key
            )
            
            # 4. Encurta a URL final
            short_url = shorten_for_publication(affiliate_url)
            
            # 5. Substitui no texto original
            # Usar replace com cuidado para não quebrar links que são sub-strings de outros
            # (embora urls únicas resolvam isso na maioria dos casos)
            transformed_text = transformed_text.replace(original_url, short_url)
            
            logger.info(f"[LINK_CONVERTER] Sucesso: {original_url[:30]} -> {short_url}")
            
        except Exception as e:
            logger.error(f"[LINK_CONVERTER] Erro ao converter link {original_url}: {e}")
            continue
            
    return transformed_text

def extract_first_url(text: str) -> str | None:
    """Extrai a primeira URL encontrada no texto."""
    match = URL_REGEX.search(text)
    return match.group(1) if match else None
