"""
affiliate_link_service.py  Servico centralizado de geracao de links de afiliado.

Injecao via urllib.parse ( prova de falha).
Logs obrigatorios: LINK_AFILIADO_GERADO, LOJA_NAO_SUPORTADA, LOJA_NAO_CONFIGURADA.
"""
import logging
import os
import re
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse, quote

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

from bot.utils.affiliate_store import get_affiliate

def get_effective_affiliate_id(store_key: str) -> str:
    """
    Retorna o ID de afiliado priorizando o configurado via menu (JSON) 
    e usando o .env como fallback.
    """
    # 1. Tenta do JSON (configurado via menu /config_afiliado)
    config = get_affiliate(store_key)
    val = config.get("tag") if store_key == "amazon" else config.get("affiliate_url")
    if val and val.strip():
        return val.strip()
    
    # 2. Fallback para .env
    env_map = {
        "amazon":       "AFFILIATE_ID_AMAZON",
        "mercadolivre": "AFFILIATE_ID_ML",
        "magalu":       "AFFILIATE_ID_MAGALU",
        "netshoes":     "AFFILIATE_ID_NETSHOES",
        "shopee":       "AFFILIATE_ID_SHOPEE",
        "aliexpress":   "AFFILIATE_ID_ALIEXPRESS",
        "kabum":        "AFFILIATE_ID_KABUM",
        "casasbahia":   "AFFILIATE_ID_CASASBAHIA",
        "ponto":        "AFFILIATE_ID_PONTO",
        "extra":        "AFFILIATE_ID_EXTRA",
        "samsung":      "AFFILIATE_ID_SAMSUNG",
    }
    env_var = env_map.get(store_key)
    if env_var:
        return os.getenv(env_var, "").strip()
    
    return ""

def log_config_status():
    """Util para diagnostico no console."""
    logger.info(" AFILIADOS: STATUS DA CONFIGURACAO ")
    stores = ["amazon", "mercadolivre", "magalu", "netshoes", "shopee", "aliexpress", "kabum", "casasbahia", "ponto", "extra", "samsung"]
    for store in stores:
        aid = get_effective_affiliate_id(store)
        if aid:
            masked = aid[:4] + "***" + aid[-4:] if len(aid) > 8 else aid
            logger.info(f" {store.upper()}: Conectado ({masked})")
        else:
            logger.warning(f" {store.upper()}: ID nao configurado (use /config_afiliado)")

# Executa log no startup
log_config_status()


# ---------------------------------------------------------------------------
# Deteccao de loja pela URL
# ---------------------------------------------------------------------------

_STORE_DOMAINS = [
    ("amazon.com.br",        "amazon"),
    ("amazon.com",           "amazon"),
    ("amzn.to",              "amazon"),
    ("amzn.com",             "amazon"),
    ("mercadolivre.com.br",  "mercadolivre"),
    ("mercadolibre.com",     "mercadolivre"),
    ("produto.mercadolivre", "mercadolivre"),
    ("ml.tidd.ly",           "mercadolivre"),
    ("meli.la",              "mercadolivre"),
    ("mli.",                 "mercadolivre"),
    ("magazineluiza.com.br", "magalu"),
    ("magalu.com",           "magalu"),
    ("netshoes.com.br",      "netshoes"),
    ("shopee.com.br",        "shopee"),
    ("shp.ee",               "shopee"),
    ("aliexpress.com",       "aliexpress"),
    ("best.aliexpress",      "aliexpress"),
    ("kabum.com.br",         "kabum"),
    ("casasbahia.com.br",    "casasbahia"),
    ("ponto.com.br",         "ponto"),
    ("pontofrio.com.br",     "ponto"),
    ("extra.com.br",         "extra"),
    ("samsung.com/br",       "samsung"),
    ("adidas.com.br",        "adidas"),
    ("nike.com.br",          "nike"),
]


# ---------------------------------------------------------------------------
# Dominios de encurtadores que precisam ser expandidos antes da injecao
# ---------------------------------------------------------------------------
_SHORT_DOMAINS = ["amzn.to", "amzn.com", "shope.ee", "shp.ee", "meli.la", "mli.", "bit.ly", "t.co", "is.gd", "cupom.cc", "descontinhodemamae.com", "divulgador.magalu.com"]


def _detectar_loja(url: str) -> str:
    url_lower = url.lower()
    for fragment, key in _STORE_DOMAINS:
        if fragment in url_lower:
            return key
    return "other"


# ---------------------------------------------------------------------------
# Injetores por loja  usando urllib.parse
# ---------------------------------------------------------------------------

def _injetar_amazon(url: str, tag: str) -> str:
    """
    Amazon: canonical /dp/ASIN?tag=ID.
    Extrai o ASIN e forca o formato cannico para evitar parmetros de rastreio de terceiros.
    """
    # Tenta extrair o ASIN (10 caracteres alfanumericos)
    asin_match = re.search(r"/(?:dp|gp/product|product-reviews|aw/d|vdp)/([A-Z0-9]{10})", url, re.I)
    if asin_match:
        asin = asin_match.group(1).upper()
        # Forca dominio .com.br para consistncia se for Amazon Brasil
        domain = "www.amazon.com.br" if "amazon.com.br" in url.lower() else "www.amazon.com"
        resultado = f"https://{domain}/dp/{asin}?tag={tag}"
        logger.info(f"[AFFILIATE_SERVICE] Amazon (Canonical) | ASIN={asin} | tag={tag}")
        return resultado
    
    # Fallback: apenas garante a tag via urllib.parse se o ASIN falhar
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["tag"] = [tag]
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Amazon (Fallback) | tag={tag} | URL={resultado[:100]}")
    return resultado


def _injetar_mercadolivre(url: str, id_ml: str) -> str:
    """
    Gera link social do Mercado Livre (Vitrine).
    Formato desejado: https://www.mercadolivre.com.br/social/{id_ml}/p/{code}
    """
    # 1. Tenta extrair o ID do produto (MLB123...)
    item_id_match = re.search(r"(ML[A-Z]\-?\d{8,15})", url, re.I)
    
    if item_id_match:
        code = item_id_match.group(1).replace("-", "").upper()
        # Se for um link de produto, usamos o formato social
        resultado = f"https://www.mercadolivre.com.br/social/{id_ml}/p/{code}"
        logger.info(f"[AFFILIATE_SERVICE] Mercado Livre Social | ID={id_ml} | Code={code}")
        return resultado

    # 2. Fallback para links que nao sao de produtos especificos (busca, landing pages)
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    # Remove parametros anteriores do ML
    for key in list(params.keys()):
        if key.startswith("matt_"):
            del params[key]
    
    # Adiciona matt_from= e matt_tool= (alguns links usam um ou outro)
    params["matt_from"] = [id_ml]
    params["matt_tool"] = [id_ml]
    
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Mercado Livre Fallback | ID={id_ml} | URL={resultado[:100]}")
    return resultado


def _injetar_magalu(url: str, id_magalu: str) -> str:
    """
    Magalu / Magazine Voce.
    Se o ID for um slug (ex: 'descontecas'), reconstroi a URL no formato Magazine Voce.
    """
    # 1. Tenta extrair o ID do produto (/p/1234567 ou final da URL)
    m_id = re.search(r"/p/(\d{5,15})", url)
    if not m_id:
        # Tenta pegar um numero longo no final da URL que parece ser o SKU
        m_id = re.search(r"/(\d{7,12})/?$", url)

    if m_id and not id_magalu.isdigit():
        product_id = m_id.group(1)
        slug = id_magalu.lower().strip()
        # No Magazine Voce, o slug geralmente e 'magazineseunome'
        if not slug.startswith("magazine"):
            slug = f"magazine{slug}"
        
        resultado = f"https://www.magazinevoce.com.br/{slug}/p/{product_id}/"
        logger.info(f"[AFFILIATE_SERVICE] Magalu Social | ID={id_magalu} | Slug={slug} | Code={product_id}")
        return resultado

    # 2. Fallback: Adiciona promoter_id e partner_id se for numerico
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    
    if id_magalu.isdigit():
        params["promoter_id"] = [id_magalu]
        params["partner_id"] = ["3440"]
    
    params["utm_medium"] = ["affiliate"]
    params["utm_source"]  = [id_magalu]
    
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Magalu Fallback | ID={id_magalu} | URL={resultado[:100]}")
    return resultado


def _injetar_shopee(url: str, shopee_id: str) -> str:
    """Adiciona af_id= para Shopee."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["af_id"] = [shopee_id]
    nova_query = urlencode(params, doseq=True)
    resultado = urlunparse(parsed._replace(query=nova_query))
    logger.info(f"[AFFILIATE_SERVICE] Shopee | af_id={shopee_id} | URL={resultado[:100]}")
    return resultado


def _injetar_netshoes(url: str, ns_id: str) -> str:
    """Netshoes via Rakuten. O * no ID e URL-encoded como %2A."""
    encoded_url = quote(url, safe="")
    encoded_id  = quote(ns_id, safe="")  # Codifica o *  %2A
    resultado = f"https://click.linksynergy.com/deeplink?id={encoded_id}&mid=43984&murl={encoded_url}"
    logger.info(f"[AFFILIATE_SERVICE] Netshoes | gateway Rakuten | ID={ns_id[:8]}...")
    return resultado

def _injetar_aliexpress(url: str, id_ali: str) -> str:
    """Adiciona aff_id= para AliExpress."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    params["aff_id"] = [id_ali]
    params["aff_platform"] = ["api-v2"]
    nova_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=nova_query))

def _injetar_generic(url: str, aff_id: str, store_key: str) -> str:
    """Injetor generico que usa UTMs ou parmetros comuns."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    
    # Mapeamento de parmetros comuns por loja
    param_map = {
        "kabum": "utm_source",
        "casasbahia": "utm_source",
        "ponto": "utm_source",
        "extra": "utm_source",
        "samsung": "utm_source",
        "adidas": "utm_source",
        "nike": "utm_source",
    }
    
    p_name = param_map.get(store_key, "aff_id")
    params[p_name] = [aff_id]
    params["utm_medium"] = ["affiliate"]
    
    nova_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=nova_query))


# ---------------------------------------------------------------------------
# Funcao publica central
# ---------------------------------------------------------------------------

async def injetar_link_afiliado(url: str, store_key: str | None = None) -> str:
    """
    Injeta o link de afiliado correto por loja.

    IMPORTANTE: Agora e ASYNC para permitir expansao de links curtos via Playwright.

    Args:
        url:        URL (pode ser curta ou longa).
        store_key:  Loja (detectada automaticamente se None).

    Returns:
        URL com parmetros de afiliado corretos.
    """
    if not url or not isinstance(url, str):
        logger.warning("[AFFILIATE_SERVICE] ERRO_GERANDO_LINK_AFILIADO: URL invalida.")
        return url or ""

    # 1. Detectar loja se nao informado
    if not store_key:
        store_key = _detectar_loja(url)

    # 2. SE FOR LINK CURTO: Obrigatorio esticar antes de injetar
    is_short = any(s in url.lower() for s in _SHORT_DOMAINS)
    if is_short:
        logger.info(f"[AFFILIATE_SERVICE] Link curto detectado ({url[:30]}). Expandindo...")
        try:
            expanded = await resolve_short_url_httpx(url)
            if expanded and expanded != url:
                url = expanded
                # Redetecta loja apos expansao
                store_key = _detectar_loja(url)
                logger.info(f"[AFFILIATE_SERVICE] Expandido  {url[:80]}... | Loja: {store_key}")
        except Exception as e:
            logger.warning(f"[AFFILIATE_SERVICE] Falha ao expandir link curto: {e}")

    # 2.5 Tratamento especial para paginas /social/ do Mercado Livre (Vitrines de terceiros)
    if store_key == "mercadolivre" and "/social/" in url.lower():
        logger.info(f"[AFFILIATE_SERVICE] Detectado link /social/. Extraindo produto real para garantir sua comissao...")
        try:
            import httpx
            from urllib.parse import quote, urlparse, urlunparse
            html = ""
            
            # Tenta Scrapingdog se houver chave (evita block de IP do Mercado Livre)
            sd_key = os.getenv("SCRAPINGDOG_API_KEY", "").strip()
            if sd_key:
                try:
                    logger.info("[AFFILIATE_SERVICE] Usando Scrapingdog para abrir pagina social...")
                    # dynamic=false e suficiente para o HTML estatico que contem os links
                    sd_url = f"https://api.scrapingdog.com/scrape?api_key={sd_key}&url={quote(url)}&dynamic=false"
                    async with httpx.AsyncClient(timeout=20.0) as client:
                        resp = await client.get(sd_url)
                        if resp.status_code == 200:
                            html = resp.text
                except Exception as e:
                    logger.warning(f"[AFFILIATE_SERVICE] Scrapingdog falhou: {e}")

            if not html:
                # Fallback para direto com Googlebot se Scrapingdog falhar ou nao existir
                headers_social = {
                    "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                    "Accept-Language": "pt-BR,pt;q=0.9",
                }
                async with httpx.AsyncClient(follow_redirects=True, timeout=15.0, headers=headers_social) as client:
                    resp = await client.get(url)
                    html = resp.text

            # 1. Busca codigo do produto (MLB...) no HTML ou na URL
            m_code = re.search(r'MLB-?\d+', html)
            if not m_code:
                 # Tenta buscar na propria URL social se houver algum ID
                 m_code = re.search(r'MLB-?\d+', url)
            
            if m_code:
                code = m_code.group(0)
                # 2. Busca o link real do produto que contem esse codigo
                # Procuramos um link que contenha o codigo e nao seja o proprio link social
                links_no_html = re.findall(fr'https?://[^"\s]*{code}[^"\s]*', html)
                
                real_url = None
                for l in links_no_html:
                    if "/social/" not in l and ("/p/" in l or "/produto" in l or "MLB" in l):
                        real_url = l.replace("&amp;", "&")
                        break
                
                if real_url:
                    # Limpa a URL de lixo do social para injetar o novo afiliado limpo
                    p = urlparse(real_url)
                    url = urlunparse(p._replace(query="", fragment=""))
                    logger.info(f"[AFFILIATE_SERVICE] /social/ convertido para produto direto: {url[:80]}")
                else:
                    # Se nao achou link completo, mas tem o codigo, monta o link padrao do produto
                    url = f"https://www.mercadolivre.com.br/p/{code.replace('-', '')}"
                    logger.info(f"[AFFILIATE_SERVICE] /social/ convertido via ID direto: {url}")
            else:
                logger.warning("[AFFILIATE_SERVICE] Nao foi possivel encontrar um produto MLB na pagina social.")
        except Exception as e:
            logger.warning(f"[AFFILIATE_SERVICE] Falha ao processar /social/: {e}")

    # 3. Limpeza preventiva de rastreadores de terceiros
    for param in ["fbclid", "gclid", "aff_id", "clickid"]:
        url = re.sub(rf"[?&]{param}=[^&]*", "", url)
    url = re.sub(r"\?&", "?", url).rstrip("?&")

    logger.info(f"[AFFILIATE_SERVICE] Iniciando injecao | loja={store_key} | url={url[:80]}")

    affiliate_id = get_effective_affiliate_id(store_key)

    if not affiliate_id:
        if store_key != "other":
            logger.warning(
                f"[AFFILIATE_SERVICE] LOJA_NAO_CONFIGURADA: {store_key} "
                f" verifique as variaveis de ambiente no Railway"
            )
        else:
            logger.info(f"[AFFILIATE_SERVICE] LOJA_NAO_SUPORTADA | url={url[:60]}")
        return url

    try:
        if store_key == "amazon":
            resultado = _injetar_amazon(url, affiliate_id)
        elif store_key == "mercadolivre":
            resultado = _injetar_mercadolivre(url, affiliate_id)
        elif store_key == "magalu":
            resultado = _injetar_magalu(url, affiliate_id)
        elif store_key == "shopee":
            resultado = _injetar_shopee(url, affiliate_id)
        elif store_key == "netshoes":
            resultado = _injetar_netshoes(url, affiliate_id)
        elif store_key == "aliexpress":
            resultado = _injetar_aliexpress(url, affiliate_id)
        elif store_key in ["kabum", "casasbahia", "ponto", "extra", "samsung", "adidas", "nike"]:
            resultado = _injetar_generic(url, affiliate_id, store_key)
        else:
            return url

        logger.info(f"[LINK_AFILIADO_GERADO] Loja: {store_key} | URL Final: {resultado}")
        return resultado

    except Exception as e:
        logger.error(f"[AFFILIATE_SERVICE] ERRO_GERANDO_LINK_AFILIADO: {e} | loja={store_key}")
        return url


# ---------------------------------------------------------------------------
# Resolver via Playwright (para shorteners que bloqueiam requests.get)
# ---------------------------------------------------------------------------

async def resolve_short_url_httpx(url: str) -> str:
    """
    Resolve URLs curtas (amzn.to, shope.ee, meli.la, etc.) via httpx.
    Detecta redirecionamentos via Meta Refresh ou JavaScript.
    """
    try:
        import httpx
        logger.info(f"[AFFILIATE_SERVICE] Resolvendo link curto: {url[:80]}")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }

        async with httpx.AsyncClient(follow_redirects=True, max_redirects=10, timeout=15.0, headers=headers) as client:
            resp = await client.get(url)
            final_url = str(resp.url)

            # Se o status e 200 mas o link nao mudou, checa se ha redirecionamento no corpo (JS/Meta)
            if final_url == url and resp.status_code == 200:
                html = resp.text
                # Meta refresh
                m_meta = re.search(r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=([^"\'>]+)["\']', html, re.I)
                # JS Location
                m_js = re.search(r'window\.location\.href\s*=\s*["\']([^"\']+)["\']', html) or \
                       re.search(r'location\.replace\(["\']([^"\']+)["\']\)', html)
                
                target = (m_meta.group(1) if m_meta else None) or (m_js.group(1) if m_js else None)
                if target:
                    if not target.startswith("http"):
                        from urllib.parse import urljoin
                        target = urljoin(url, target)
                    logger.info(f"[AFFILIATE_SERVICE] Detectado redirecionamento interno para: {target[:80]}")
                    return await resolve_short_url_httpx(target)

        if final_url and final_url != url:
            logger.info(f"[AFFILIATE_SERVICE] Link resolvido: {final_url[:100]}")
            return final_url
        
        # Se falhou e for um encurtador conhecido, tenta via Scrapingdog como ultimo recurso
        if any(s in url.lower() for s in ["meli.la", "ml.tidd.ly", "amzn.to", "shope.ee"]):
            sd_key = os.getenv("SCRAPINGDOG_API_KEY", "").strip()
            if sd_key:
                try:
                    logger.info(f"[AFFILIATE_SERVICE] Tentando Scrapingdog para expansao de {url[:40]}...")
                    sd_url = f"https://api.scrapingdog.com/scrape?api_key={sd_key}&url={quote(url)}&dynamic=true"
                    async with httpx.AsyncClient(timeout=25.0) as client:
                        resp_sd = await client.get(sd_url)
                        # O Scrapingdog com dynamic=true nos dara a URL final no header ou podemos extrair do HTML
                        if resp_sd.status_code == 200:
                            # Tenta pegar link de produto no HTML resultante
                            m_mlb = re.search(r'https?://[^"\s]*MLB-?\d+[^"\s]*', resp_sd.text)
                            if m_mlb:
                                logger.info(f"[AFFILIATE_SERVICE] Link extraido via Scrapingdog: {m_mlb.group(0)[:80]}")
                                return m_mlb.group(0)
                except: pass

        return url

    except Exception as e:
        logger.warning(f"[AFFILIATE_SERVICE] Falha ao resolver link ({e}).")
        return url
