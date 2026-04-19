"""
product_extractor_v2.py — Extrator de produtos em camadas.

Ordem de prioridade:
  Prioridade 0 — Preço PIX/à-vista (antes de tudo)
  Camada 1 — Playwright (renderização real de JS)
  Camada 2 — requests + BeautifulSoup (fallback HTML)
  Camada 3 — Retorno seguro mínimo (nunca quebra o fluxo)

Regra de preço:
  1. Se existe preço PIX/à-vista → usa ele (is_pix_price=True)
  2. Senão: pega o MENOR entre promocional e original.
  Log obrigatório: PRECO_TIPO=PIX | PROMOCIONAL | ORIGINAL
"""
import json
import logging
import re
import asyncio

import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive",
}

_MOBILE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Connection": "keep-alive",
}

_TIMEOUT_HTTP = 15
_TIMEOUT_PLAYWRIGHT = 20


# ---------------------------------------------------------------------------
# Helpers de preço
# ---------------------------------------------------------------------------

def _parse_price_to_float(text: str) -> float | None:
    """Converte 'R$ 1.299,90' ou 'R\u00a0189,90' ou '399.00' → float."""
    if not text:
        return None
    # Normaliza: remove espaço não-quebrável (\xa0) e parenteséticos
    text = str(text).replace('\u00a0', ' ').replace('\xa0', ' ')
    text = re.sub(r"\(.*?\)", "", text)
    cleaned = re.sub(r"[^\d,.]", "", text)
    if not cleaned:
        return None

    if "," in cleaned:
        # Padrão BR: 1.299,90 -> 1299.90
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        # Padrão Internacional ou BR sem decimal: 399.00 ou 1.200
        # Se houver apenas um ponto e ele estiver na posição de centavos (2 antes do fim),
        # e não for um número gigante, tratamos como decimal (comum em JSON-LD).
        parts = cleaned.split('.')
        if len(parts) == 2 and len(parts[1]) == 2:
            # Caso 399.00 -> mantém o ponto como decimal
            pass
        else:
            # Caso 1.200 -> remove o ponto (divisor de milhar)
            cleaned = cleaned.replace(".", "")
            
    try:
        val = float(cleaned)
        # Sanidade mínima: preços absurdos > 500k em itens comuns costumam ser erro de parsing
        # (A menos que seja um carro ou imóvel, mas pro bot de achadinhos 500k é safe limit)
        if val > 500000: return None
        return val
    except Exception:
        return None


def _clean_price(raw: str) -> str | None:
    """Normaliza preço para exibição: R$ 1.299,90"""
    if not raw:
        return None
    val = _parse_price_to_float(raw)
    if val is None:
        return None
    # Re-formata no padrão BR
    reais = int(val)
    centavos = round((val - reais) * 100)
    reais_fmt = f"{reais:,}".replace(",", ".")
    return f"R$ {reais_fmt},{centavos:02d}"


def _choose_lower_price(p1: str | None, p2: str | None) -> tuple[str | None, str | None]:
    """
    Retorna (preco_promocional, preco_original).
    Sempre coloca o MENOR como promocional.
    """
    v1 = _parse_price_to_float(p1) if p1 else None
    v2 = _parse_price_to_float(p2) if p2 else None

    if v1 is None and v2 is None:
        return None, None
    if v1 is None:
        return _clean_price(p2), None
    if v2 is None:
        return _clean_price(p1), None

    if v1 <= v2:
        return _clean_price(p1), _clean_price(p2)
    else:
        return _clean_price(p2), _clean_price(p1)


# ---------------------------------------------------------------------------
# Prioridade 0: Preço PIX / à vista — buscado ANTES dos seletores padrão
# ---------------------------------------------------------------------------

_PIX_PATTERN = re.compile(r'pix|à\s*vista', re.IGNORECASE)


def _find_price_near_text(soup: BeautifulSoup, text_pattern, price_selectors: list[str]) -> str | None:
    """
    Procura pelo texto que casa com text_pattern e tenta encontrar
    um preço nos elementos vizinhos (subindo até 6 níveis na árvore).
    Retorna o primeiro valor numérico válido encontrado.
    """
    for text_node in soup.find_all(string=text_pattern):
        parent = text_node.parent
        for _ in range(6):
            if parent is None:
                break
            for sel in price_selectors:
                tag = parent.select_one(sel)
                if tag:
                    val = tag.get_text(strip=True)
                    if _parse_price_to_float(val):
                        return val
            parent = parent.parent
    return None


def _extract_pix_price_amazon(soup: BeautifulSoup) -> str | None:
    """Amazon: busca preço 'no Pix' / 'à vista no Pix'."""
    price_selectors = [
        ".a-price .a-offscreen",
        ".a-price-whole",
        ".a-price .a-price-whole",
    ]
    val = _find_price_near_text(soup, _PIX_PATTERN, price_selectors)
    if val:
        logger.info(f"[EXTRACTOR_V2] Amazon PIX price encontrado: {val}")
        return _clean_price(val)
    return None


def _extract_pix_price_ml(soup: BeautifulSoup) -> str | None:
    """Mercado Livre: busca preço 'no Pix' na seção de desconto Pix."""
    # Tenta primeiro via seletor específico de desconto Pix
    pix_section = soup.select_one(".ui-pdp-price--pix, [data-testid='pix-price']")
    if pix_section:
        frac = pix_section.select_one(".andes-money-amount__fraction")
        if frac:
            val = frac.get_text(strip=True)
            cents = pix_section.select_one(".andes-money-amount__cents")
            if cents:
                val += f",{cents.get_text(strip=True)}"
            if _parse_price_to_float(val):
                logger.info(f"[EXTRACTOR_V2] ML PIX price (seletor direto): {val}")
                return _clean_price(val)
    return None


def _extract_price_from_schema(soup: BeautifulSoup) -> str | None:
    """Busca universal de preço usando JSON-LD Schema.org (Agressivo)."""
    scripts = soup.find_all('script', type='application/ld+json')
    for s in scripts:
        if not s.string: continue
        try:
            data = json.loads(s.string)
            if not isinstance(data, dict): continue
            
            # Normaliza para lista (mesmo se for um objeto só ou @graph)
            items = data.get('@graph', [data])
            if not isinstance(items, list): items = [items]
            
            for item in items:
                # Procura por Product ou MainEntity (comum na Magalu/Netshoes)
                if item.get('@type') in ('Product', 'ProductCollection'):
                    offers = item.get('offers')
                    if not offers: continue
                    
                    if isinstance(offers, dict):
                        # Padrão simples
                        p = offers.get('price') or offers.get('lowPrice')
                        if p: return _clean_price(str(p))
                    elif isinstance(offers, list):
                        # Lista de ofertas
                        for off in offers:
                            p = off.get('price')
                            if p: return _clean_price(str(p))
                            
                # Fallback: qualquer coisa que pareça uma oferta solta
                if item.get('@type') == 'Offer':
                    p = item.get('price')
                    if p: return _clean_price(str(p))
        except Exception:
            pass
    return None


def _extract_price_from_body_regex(soup: BeautifulSoup) -> str | None:
    """
    ULTIMATO: Busca qualquer padrão de R$ no corpo da página.
    Ideal para quando a Amazon bloqueia seletores mas deixa o texto.
    """
    text = soup.get_text()
    # Padrão: R$ seguido de números, pontos e vírgulas
    matches = re.findall(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text)
    if matches:
        # Pega o primeiro que não seja 0,00
        for m in matches:
            if m != "0,00":
                logger.info(f"[EXTRACTOR_V2] Preço minerado via Regex Body: R$ {m}")
                return f"R$ {m}"
    return None


def _extract_pix_price_magalu(soup: BeautifulSoup) -> str | None:
    """Magalu: busca preço 'no Pix' próximo ao label PIX."""
    price_selectors = [
        "[data-testid='price-value']",
        ".sc-kLojnp",
    ]
    val = _find_price_near_text(soup, _PIX_PATTERN, price_selectors)
    if val:
        logger.info(f"[EXTRACTOR_V2] Magalu PIX price encontrado: {val}")
        return _clean_price(val)
    return None


# ---------------------------------------------------------------------------
# Extração de preço por loja — seletores com prioridade por tipo
# ---------------------------------------------------------------------------

def _is_valid_price_tag(tag) -> bool:
    """Verifica se a tag não pertence a um preço unitário (ex: R$ 0,26 / unidade)."""
    if not tag: return False
    # Verifica o contexto do PAI (onde a Amazon coloca '/ unidade')
    # mas também o texto da própria tag para tags 'a-offscreen' que só contam o número
    text_context = tag.get_text(strip=True).lower()
    # Sobe até 4 níveis para buscar contexto de 'unidade'
    p = tag.parent
    for _ in range(4):
        if p is None: break
        text_context += ' ' + p.get_text(strip=True).lower()
        p = p.parent
    
    # Palavras-chave que indicam preço unitário
    unit_keywords = ["/ unidade", "/unidade", "por unidade", "/ unit", " ml", " kg"]
    return not any(k in text_context for k in unit_keywords)


def _extract_price_amazon(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Amazon: promocional < original."""
    preco_promo = None
    preco_orig  = None

    # Preço promocional (seletores em ordem de confiança)
    # PRIORIDADE: Usar .a-offscreen antes de .a-price-whole para capturar os centavos
    promo_selectors = [
        "#corePrice_feature_div .a-offscreen",
        "#corePrice_feature_div .a-price-whole",
        "#priceblock_dealprice",
        "#priceblock_ourprice",
        ".a-price.priceToPay .a-offscreen",
        ".a-price .a-offscreen",
    ]
    for sel in promo_selectors:
        # Pega todos os matches e filtra os de 'unidade'
        for tag in soup.select(sel):
            if not _is_valid_price_tag(tag):
                continue
                
            val = tag.get_text(strip=True)
            
            # Especial para Amazon: se pegou o 'whole', tenta achar os centavos no vizinho
            if "a-price-whole" in sel:
                parent = tag.parent
                fraction = parent.select_one(".a-price-fraction") if parent else None
                if fraction:
                    val = f"{val.replace(',', '').replace('.', '')},{fraction.get_text(strip=True)}"
            
            if _parse_price_to_float(val):
                preco_promo = val
                logger.info(f"[EXTRACTOR_V2] Amazon preço promo via '{sel}': {preco_promo}")
                break
        if preco_promo:
            break

    # Preço original/riscado
    orig_selectors = [".a-text-price .a-offscreen", "#listPrice", ".basisPrice .a-offscreen"]
    for sel in orig_selectors:
        for tag in soup.select(sel):
             if _is_valid_price_tag(tag):
                val = tag.get_text(strip=True)
                if _parse_price_to_float(val):
                    preco_orig = val
                    break
        if preco_orig:
            break

    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_ml(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Mercado Livre: usar .andes-money-amount--cents-superscript, nunca --previous."""
    preco_promo = None
    preco_orig  = None

    # Preço promocional
    promo_selectors = [
        ".ui-pdp-price__second-line .andes-money-amount__fraction",
        ".andes-money-amount--main .andes-money-amount__fraction",
        ".ui-pdp-price .andes-money-amount__fraction",
        ".andes-money-amount__fraction", # Genérico como última opção
    ]
    for sel in promo_selectors:
        # Pega todas as tags e filtra explicitly as que são "previous" (riscadas)
        for tag in soup.select(sel):
            parent_container = tag.find_parent(class_=re.compile(r"andes-money-amount"))
            if parent_container and "andes-money-amount--previous" in parent_container.get("class", []):
                continue # Pula preço riscado
            
            val = tag.get_text(strip=True)
            parent = tag.parent
            cents = parent.select_one(".andes-money-amount__cents") if parent else None
            if cents:
                val += f",{cents.get_text(strip=True)}"
            
            if _parse_price_to_float(val):
                preco_promo = val
                logger.info(f"[EXTRACTOR_V2] ML preço promo via '{sel}': {preco_promo}")
                break
        if preco_promo:
            break

    # Preço original riscado — seletor da classe "previous"
    orig_tag = soup.select_one(".andes-money-amount--previous .andes-money-amount__fraction")
    if orig_tag:
        preco_orig = orig_tag.get_text(strip=True)

    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_magalu(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Magalu: pegar preço do [data-testid='price-value'], ignorar 'no-price-value'."""
    preco_promo = None
    preco_orig  = None

    promo_tag = soup.select_one("[data-testid='price-value'], .sc-kLojnp")
    if promo_tag:
        preco_promo = promo_tag.get_text(strip=True)

    orig_tag = soup.select_one("[data-testid='no-price-value'], .sc-jJoQJp")
    if orig_tag:
        preco_orig = orig_tag.get_text(strip=True)

    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_netshoes(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Netshoes: .product-final-price é o promo, .old-price é o original."""
    promo_tag = soup.select_one(".product-final-price, .best-price")
    orig_tag  = soup.select_one(".old-price")
    preco_promo = promo_tag.get_text(strip=True) if promo_tag else None
    preco_orig  = orig_tag.get_text(strip=True)  if orig_tag  else None
    return _choose_lower_price(preco_promo, preco_orig)


def _extract_price_generic(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Genérico: meta tags de preço de venda têm prioridade."""
    preco_promo = None
    preco_orig  = None

    # 1. Meta sale_price → promo; price:amount → original ou fallback
    sale_meta = soup.find("meta", attrs={"property": "product:sale_price:amount"})
    price_meta = soup.find("meta", attrs={"property": "product:price:amount"})

    if sale_meta and sale_meta.get("content"):
        preco_promo = sale_meta["content"]
    if price_meta and price_meta.get("content"):
        candidate = price_meta["content"]
        if preco_promo:
            preco_orig = candidate
        else:
            preco_promo = candidate

    if preco_promo:
        logger.info(f"[EXTRACTOR_V2] Preço via meta tag: promo={preco_promo}, orig={preco_orig}")
        return _choose_lower_price(preco_promo, preco_orig)

    # 2. JSON-LD
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            js = json.loads(script.string or "")
            items = js if isinstance(js, list) else [js]
            for item in items:
                product = item if item.get("@type") == "Product" else item.get("mainEntity")
                if isinstance(product, dict) and product.get("@type") == "Product":
                    offers = product.get("offers", {})
                    price = (
                        offers.get("price") if isinstance(offers, dict)
                        else offers[0].get("price") if isinstance(offers, list) and offers
                        else None
                    )
                    if price:
                        logger.info(f"[EXTRACTOR_V2] Preço via JSON-LD: {price}")
                        return _clean_price(str(price)), None
        except Exception:
            continue

    # 3. Regex bruto no HTML
    match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", str(soup))
    if match:
        val = f"R$ {match.group(1)}"
        logger.info(f"[EXTRACTOR_V2] Preço via regex bruto: {val}")
        return val, None

    return None, None


# ---------------------------------------------------------------------------
# Extração completa da página
# ---------------------------------------------------------------------------

def _extract_from_soup(soup: BeautifulSoup, base_url: str, store_key: str = "other") -> dict:
    """Extrai título, preço promocional, preço original, imagem e flag PIX."""
    data = {"titulo": None, "preco": None, "preco_original": None, "imagem": None, "is_pix_price": False}

    # ── DETECÇÃO DE BLOQUEIO / CAPTCHA ─────────────────────────────────────
    blocked_patterns = [
        "captcha", "blocked", "bot manager", "perfdrive", "shieldsquare", 
        "acesso negado", "access denied", "validate.perfdrive.com"
    ]
    page_text_lower = soup.get_text().lower()
    page_title_lower = (soup.title.string.lower() if soup.title else "")
    
    if any(p in page_title_lower for p in blocked_patterns) or \
       any(p in page_text_lower for p in ["radware bot manager", "please verify you are a human"]):
        logger.warning(f"[EXTRACTOR_V2] Bloqueio detectado: {page_title_lower}")
        return {
            "titulo": f"BLOQUEIO: {page_title_lower or 'Acesso Negado'}",
            "preco": "Erro: Captcha/Block",
            "imagem": None,
            "source_method": "BLOCKED"
        }

    # ── TÍTULO ──────────────────────────────────────────────────────────────
    title_selectors = [
        "#productTitle",             # Amazon
        ".ui-pdp-title",             # Mercado Livre
        "h1[itemprop='name']",       # Magalu / genérico
        ".header-product__title",    # Netshoes
        "h1.product-name", "h1",
    ]
    for sel in title_selectors:
        tag = soup.select_one(sel)
        if tag:
            text = tag.get_text(strip=True)
            if len(text) > 10:
                raw = re.sub(r"^(Amazon\.com\.br|Mercado Livre|Magalu|Magazine Luiza)\s*[:\-]\s*", "", text, flags=re.I)
                raw = re.sub(r"\s*[|–\-]\s*(Amazon|Mercado Livre|Magalu|Magazine Luiza|Shopee).*", "", raw, flags=re.I)
                data["titulo"] = raw.strip()
                logger.info(f"[EXTRACTOR_V2] Título via '{sel}': {data['titulo'][:60]}")
                break

    # Detecção de bloqueio Industrial (Magalu/Amazon/Geral)
    block_keywords = [
        "parece que você acessou", "acesso incomum", "acesso negado", 
        "forbidden", "access denied", "robot", "bot detection", "captcha",
        "human verification", "segurança", "desculpe"
    ]
    if data["titulo"]:
        lower_title = data["titulo"].lower()
        if any(k in lower_title for k in block_keywords):
            logger.warning(f"[EXTRACTOR_V2] BLOQUEIO DETECTADO no título: '{data['titulo']}'. Anulando título.")
            data["titulo"] = None

    if not data["titulo"]:
        # Fallback 2: Meta tags
        for attr_name, attr_val in [("property", "og:title"), ("name", "twitter:title")]:
            meta = soup.find("meta", attrs={attr_name: attr_val})
            if meta and meta.get("content"):
                raw = meta["content"]
                raw = re.sub(r"^(Amazon\.com\.br|Mercado Livre|Magalu)\s*[:\-]\s*", "", raw, flags=re.I)
                raw = re.sub(r"\s*[|–\-]\s*(Amazon|Mercado Livre|Magalu).*", "", raw, flags=re.I)
                data["titulo"] = raw.strip()
                break

    # Fallback extra: Tag <title> bruta
    if not data["titulo"] and soup.title:
        raw = soup.title.get_text(strip=True)
        raw = re.sub(r"^(Amazon\.com\.br|Mercado Livre|Magalu)\s*[:\-]\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*[|–\-]\s*(Amazon|Mercado Livre|Magalu).*", "", raw, flags=re.I)
        if len(raw) > 10:
            data["titulo"] = raw.strip()

    if not data["titulo"] or data["titulo"] in ("Produto", "Amazon.com.br", "Magazine Luiza", "Magalu", "Mercado Livre"):
        # Fallback 3: Extração pela URL (Mergulha na slug estruturada)
        try:
            from urllib.parse import urlparse
            path = urlparse(base_url).path
            
            # Padrão Amazon: /NOME-DO-PRODUTO/dp/ID ou /gp/product/ID
            if "/dp/" in path or "/gp/" in path:
                # O slug costuma vir antes do /dp/
                parts = [p for p in path.split('/') if p]
                idx = -1
                if "dp" in parts: idx = parts.index("dp")
                elif "product" in parts: idx = parts.index("product")
                
                if idx > 0:
                    slug = parts[idx-1]
                    if len(slug) > 5 and '-' in slug:
                        raw = slug.replace('-', ' ')
                        data["titulo"] = raw.strip().title()
                        logger.info(f"[EXTRACTOR_V2] Título via URL (Amazon): {data['titulo']}")

            if not data["titulo"] or data["titulo"] == "Produto":
                # Padrão Geral (ML / Outros)
                parts = [p for p in path.split('/') if len(p) > 10 and '-' in p]
                if parts:
                    raw = parts[0].replace('-', ' ')
                    raw = re.sub(r'mlb\s*\d+', '', raw, flags=re.I)
                    raw = re.sub(r'[_+\-]?jm\s*$', '', raw, flags=re.I)
                    raw = raw.strip().title()
                    # Corrige pequenos erros gramaticais comuns na url
                    raw = raw.replace('Tnis', 'Tênis')
                    if len(raw) > 5:
                        data["titulo"] = raw
                        logger.info(f"[EXTRACTOR_V2] Título extraído via URL: {data['titulo']}")
        except Exception:
            pass

    # ── PREÇO PRIORIDADE 0: PIX / à vista ───────────────────────────────────
    pix_price = None
    if store_key == "amazon":
        pix_price = _extract_pix_price_amazon(soup)
    elif store_key == "mercadolivre":
        pix_price = _extract_pix_price_ml(soup)
    elif store_key == "magalu":
        pix_price = _extract_pix_price_magalu(soup)

    if pix_price:
        data["preco"]       = pix_price
        data["is_pix_price"] = True
        logger.info(f"[EXTRACTOR_V2] PRECO_TIPO=PIX | pix={pix_price}")
        # Ainda busca preço original (riscado) para comparação
        if store_key == "amazon":
            _, preco_orig = _extract_price_amazon(soup)
        elif store_key == "mercadolivre":
            _, preco_orig = _extract_price_ml(soup)
        elif store_key == "magalu":
            _, preco_orig = _extract_price_magalu(soup)
        else:
            preco_orig = None
        if preco_orig and preco_orig != pix_price:
            data["preco_original"] = preco_orig
    else:
        # ── PREÇO padrão (por loja, com prioridade promocional) ───────────────
        if store_key == "amazon":
            preco, preco_orig = _extract_price_amazon(soup)
        elif store_key == "mercadolivre":
            preco, preco_orig = _extract_price_ml(soup)
        elif store_key == "magalu":
            preco, preco_orig = _extract_price_magalu(soup)
        elif store_key == "netshoes":
            preco, preco_orig = _extract_price_netshoes(soup)
        else:
            preco, preco_orig = _extract_price_generic(soup)

        if preco:
            data["preco"]          = preco
            data["preco_original"] = preco_orig
            tipo = "PROMOCIONAL" if preco_orig else "ORIGINAL"
            logger.info(f"[EXTRACTOR_V2] PRECO_TIPO={tipo} | promo={preco} | orig={preco_orig}")
        else:
            # ── ULTIMATO 0: Tenta extrair via JSON-LD Schema.org ──────────────
            schema_p = _extract_price_from_schema(soup)
            if schema_p:
                data["preco"] = schema_p
                logger.info(f"[EXTRACTOR_V2] Salva-vidas: Preço extraído via Schema.org -> {schema_p}")

            # ── ULTIMATO 1: Tenta extrair do <title> ─────────────────────────
            if not data.get("preco"):
                html_title = soup.title.string if soup.title else ""
                if html_title:
                    title_match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", html_title)
                    if title_match:
                        found_title_p = f"R$ {title_match.group(1)}"
                        data["preco"] = found_title_p
                        logger.info(f"[EXTRACTOR_V2] Salva-vidas: Preço extraído do <title> -> {found_title_p}")

            # ── ULTIMATO 2: Tenta extrair do Título do Produto ───────────────
            if not data.get("preco") and data.get("titulo"):
                price_match = re.search(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})", data["titulo"])
                if price_match:
                    found_p = f"R$ {price_match.group(1)}"
                    data["preco"] = found_p
                    logger.info(f"[EXTRACTOR_V2] Salva-vidas: Preço extraído do h1/titulo -> {found_p}")

            # ── ULTIMATO 3: Mineração Regex no Body ──────────────────────────
            if not data.get("preco"):
                regex_p = _extract_price_from_body_regex(soup)
                if regex_p:
                    data["preco"] = regex_p

            if not data.get("preco"):
                logger.warning(f"[EXTRACTOR_V2] ERRO_EXTRAINDO_PRECO para store_key={store_key}")

    # ── IMAGEM ──────────────────────────────────────────────────────────────
    for og_prop in ["og:image", "twitter:image"]:
        meta = (
            soup.find("meta", attrs={"property": og_prop})
            or soup.find("meta", attrs={"name": og_prop})
        )
        if meta and meta.get("content"):
            img = meta["content"]
            data["imagem"] = img if img.startswith("http") else urljoin(base_url, img)
            break

    if not data["imagem"]:
        img_tag = soup.select_one(".ui-pdp-gallery__figure__image, #imgBlkFront, #landingImage")
        if img_tag:
            src = img_tag.get("src") or img_tag.get("data-src")
            if src:
                data["imagem"] = src if src.startswith("http") else urljoin(base_url, src)

    # ── HIGIENIZAÇÃO DA IMAGEM ──────────────────────────────────────────────
    # Se a URL da imagem tiver variáveis de template "{...}", o Telegram recusa (ex: Mercado Livre)
    if data["imagem"] and ("{" in data["imagem"] or "}" in data["imagem"]):
        logger.warning(f"[EXTRACTOR_V2] Imagem ignorada por conter template inválido: {data['imagem']}")
        data["imagem"] = None

    return data


# ---------------------------------------------------------------------------
# Camada 1 — Playwright
# ---------------------------------------------------------------------------

async def _extract_with_playwright(url: str, store_key: str = "other") -> dict | None:
    try:
        from playwright.async_api import async_playwright
        import os

        # Força Magalu Desktop (menos agressivo no bloqueio que a versão Mobile)
        if "magazineluiza.com.br" in url:
            url = url.replace("m.magazineluiza.com.br", "www.magazineluiza.com.br")

        logger.info(f"[EXTRACTOR_V2] PLAYWRIGHT iniciando | loja={store_key} | url={url[:80]}")
        async with async_playwright() as pw:
            proxy_config = None
            http_proxy = os.getenv("HTTP_PROXY", "").strip()
            if http_proxy and http_proxy.lower() not in ("none", "null", "undefined"):
                proxy_config = {"server": http_proxy}

            browser = await pw.chromium.launch(
                headless=True,
                proxy=proxy_config,
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            # Escolha inteligente de User-Agent
            ua = _MOBILE_HEADERS["User-Agent"] if "m.magazineluiza" in url else _HEADERS["User-Agent"]
            logger.info(f"[EXTRACTOR_V2] PLAYWRIGHT: Usando UA {'MOBILE' if 'm.magazineluiza' in url else 'DESKTOP'}")
            
            page = await browser.new_page(
                user_agent=ua, 
                locale="pt-BR",
                timezone_id="America/Sao_Paulo"
            )
            
            # ── STEALTH MODE (Bypass Fingerprinting) ──────────────────────────────
            try:
                from playwright_stealth import stealth_async
                await stealth_async(page)
                logger.info("[EXTRACTOR_V2] PLAYWRIGHT: Stealth Mode ativado.")
            except ImportError:
                logger.warning("[EXTRACTOR_V2] playwright-stealth não disponível.")

            # Cabeçalhos extras para Magalu
            if "magazineluiza" in url:
                await page.set_extra_http_headers({
                    "Referer": "https://www.google.com/",
                    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "cross-site",
                    "Sec-Fetch-User": "?1"
                })

            # Timeout aumentado para ambiente de cloud (Railway)
            await page.goto(url, wait_until="networkidle", timeout=45000)
            # Simulação de comportamento humano (Scroll)
            try:
                await page.evaluate("window.scrollTo(0, 400)")
                await page.wait_for_timeout(1000)
            except: pass

            html = await page.content()
            final_url = page.url
            await browser.close()

            soup = BeautifulSoup(html, "html.parser")
            data = _extract_from_soup(soup, final_url, store_key)
            data["source_method"] = "PLAYWRIGHT"
            data["final_url"] = final_url
            data["debug_info"] = f"PW {store_key} | UA: {ua[:20]}..."
            return data

    except ImportError:
        logger.warning("[EXTRACTOR_V2] Playwright não instalado. Fallback HTML.")
        return {"debug_info": "Playwright não instalado"}
    except Exception as e:
        import traceback
        err_msg = str(e).split('\n')[0] # Pega a primeira linha do erro
        logger.warning(f"[EXTRACTOR_V2] PLAYWRIGHT ERRO: {e}")
        return {"debug_info": f"PW_ERROR: {err_msg}"}


# ---------------------------------------------------------------------------
# Camada 2 — HTML + BeautifulSoup
# ---------------------------------------------------------------------------

def _extract_with_httpx(url: str, store_key: str = "other") -> dict | None:
    """Fallback usando HTTP/2 (mais difícil de detectar que requests)"""
    try:
        import httpx
        logger.info(f"[EXTRACTOR_V2] HTTPX_FALLBACK iniciando | loja={store_key} | url={url[:80]}")
        
        # Força Magalu Desktop no HTTPX também
        if "magazineluiza.com.br" in url:
            url = url.replace("m.magazineluiza.com.br", "www.magazineluiza.com.br")

        headers = _HEADERS.copy() # Sempre desktop para evitar bloqueio agressivo mobile
        headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8",
            "Cache-Control": "max-age=0",
            "Referer": "https://www.google.com.br/",
            "Sec-Ch-Ua": '"Not?A_Brand";v="8", "Chromium";v="124", "Google Chrome";v="124"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1"
        })

        with httpx.Client(http2=True, timeout=_TIMEOUT_HTTP, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            
            final_url = str(resp.url)
            soup = BeautifulSoup(resp.text, "html.parser")
            data = _extract_from_soup(soup, final_url, store_key)
            data["source_method"] = "HTTPX_FALLBACK"
            data["final_url"] = final_url
            data["debug_info"] = f"H2 {resp.status_code} | UA: Desktop"
            return data
    except Exception as e:
        msg = f"HTTPX_FALLBACK ERRO: {e}"
        logger.warning(f"[EXTRACTOR_V2] {msg}")
        return {"debug_info": msg}


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------

async def extract_product_data_v2(url: str) -> dict:
    """
    Pipeline em camadas: Playwright → HTML → mínimo seguro.
    Sempre retorna dict completo, nunca levanta exceção para o chamador.
    """
    from bot.utils.detect_store import detect_store
    from bot.utils.url_resolver import resolve_url

    logger.info(f"[EXTRACTOR_V2] ── INÍCIO PIPELINE ── url={url[:100]}")

    result = {
        "store": "desconhecida", "store_key": "other",
        "final_url": url, "affiliate_url": url,
        "titulo": "Produto", "imagem": None,
        "preco": "Preço não disponível", "preco_original": None,
        "source_method": "FALLBACK_SEM_PRECO", "erro": None,
        "is_pix_price": False,
    }

    # Resolve URL final: Se for Amazon, não usa `requests` porque a Amazon bloqueia o bot.
    # O Playwright resolverá o redirecionamento com integridade depois.
    if "amzn.to" not in url and "amazon.com" not in url:
        try:
            final_url = await asyncio.to_thread(resolve_url, url)
            result["final_url"] = final_url
            logger.info(f"[EXTRACTOR_V2] URL_RESOLVIDA: {final_url[:100]}")
        except Exception as e:
            final_url = url
            logger.warning(f"[EXTRACTOR_V2] Falha ao resolver URL: {e}")
    else:
        final_url = url
        logger.info(f"[EXTRACTOR_V2] URL amazon será resolvida no Playwright: {final_url}")

    # Detecta loja
    store_display, store_key = detect_store(final_url)
    result["store"]     = store_display
    result["store_key"] = store_key
    logger.info(f"[EXTRACTOR_V2] LOJA_DETECTADA: {store_display} (key={store_key})")

    # Camada 1: Playwright
    data = await _extract_with_playwright(final_url, store_key)

    # Camada 2: HTML Fallback
    # Camada 2: HTTPX (HTTP/2) Fallback
    if not data or not data.get("titulo") or "BLOQUEIO" in data.get("titulo", ""):
        logger.info("[EXTRACTOR_V2] Playwright insuficiente/bloqueado → HTTPX_FALLBACK")
        data = await asyncio.to_thread(_extract_with_httpx, final_url, store_key)

    # Camada 3: mínimo seguro
    if not data:
        logger.error("[EXTRACTOR_V2] Todas as camadas falharam. Retornando mínimo.")
        result["erro"] = "Todas as camadas de extração falharam."
        return result

    # Merge
    for key in ["titulo", "preco", "preco_original", "imagem"]:
        if data.get(key):
            result[key] = data[key]

    # Propaga flag PIX (True tem prioridade)
    if data.get("is_pix_price"):
        result["is_pix_price"] = True

    result["source_method"] = data.get("source_method", "HTML_FALLBACK")
    result["final_url"]     = data.get("final_url", final_url)
    result["debug_info"]    = data.get("debug_info", "N/A")

    # ── FALLBACK DE TÍTULO VIA URL SLUG ─────────────────────────────────────
    if not result.get("titulo") or result["titulo"] == "Produto":
        import urllib.parse
        path = urllib.parse.urlparse(result["final_url"]).path
        
        slug = ""
        if store_key == "amazon" and "/dp/" in path:
            slug = path.split("/dp/")[0].strip("/")
        elif store_key == "mercadolivre" and "/MLB-" in path:
            # ex: /MLB-1234-nome-do-produto-aqui-_JM -> nome-do-produto-aqui
            parts = path.split("-")
            if len(parts) > 2:
                # Remove MLB, id e _JM se houver
                clean_parts = [p for p in parts[2:] if p != "_JM"]
                slug = "-".join(clean_parts)
        elif store_key == "magalu":
            # ex: /nome-do-produto/p/123/
            slug = path.split("/p/")[0].strip("/")

        if slug:
            titulo_from_slug = urllib.parse.unquote(slug).replace("-", " ").title().strip()
            result["titulo"] = titulo_from_slug
            logger.info(f"[EXTRACTOR_V2] Fallback de Título via URL Slug: {titulo_from_slug}")

    if not result.get("preco") or result["preco"] == "Preço não disponível":
        result["source_method"] = "FALLBACK_SEM_PRECO"
        logger.warning(f"[EXTRACTOR_V2] ERRO_EXTRAINDO_PRECO | url={final_url[:60]}")

    logger.info(
        f"[EXTRACTOR_V2] EXTRACAO_SUCESSO | método={result['source_method']} | "
        f"título={result['titulo'][:40]} | preço={result['preco']} | "
        f"orig={result['preco_original']} | pix={result['is_pix_price']}"
    )
    return result
