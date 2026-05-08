"""
affiliate_store.py - Persistência e leitura das configurações de afiliado por loja.

Arquivo de dados: data/affiliate_config.json

Estrutura:
{
    "amazon":        { "tag": "seutag-20" },
    "magalu":        { "affiliate_url": "https://..." },
    "netshoes":      { "affiliate_url": "https://..." },
    "mercadolivre":  { "affiliate_url": "https://..." },
    "other":         { "affiliate_url": "" }
}
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Caminho do arquivo de configuração (relativo ao projeto)
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_CONFIG_FILE = _DATA_DIR / "affiliate_config.json"

# Estrutura padrão vazia
_DEFAULT_CONFIG: dict = {
    "amazon":       {"tag": ""},
    "magalu":       {"affiliate_url": ""},
    "netshoes":     {"affiliate_url": ""},
    "mercadolivre": {"affiliate_url": ""},
    "shopee":       {"affiliate_url": ""},
    "other":        {"affiliate_url": ""},
}


def _ensure_file() -> None:
    """Garante que o arquivo e o diretório existem."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _CONFIG_FILE.exists():
        _CONFIG_FILE.write_text(json.dumps(_DEFAULT_CONFIG, indent=2, ensure_ascii=False))
        logger.info(f"[AFFILIATE_STORE] Arquivo criado: {_CONFIG_FILE}")


def load_config() -> dict:
    """Carrega e retorna o JSON completo de configuração de afiliados."""
    _ensure_file()
    try:
        with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Garante que todas as lojas existem no arquivo (migrate graceful)
        changed = False
        for key, default in _DEFAULT_CONFIG.items():
            if key not in data:
                data[key] = default
                changed = True
        if changed:
            save_config(data)
        return data
    except Exception as e:
        logger.error(f"[AFFILIATE_STORE] Erro ao carregar config: {e}")
        return dict(_DEFAULT_CONFIG)


def save_config(config: dict) -> bool:
    """Salva o dicionário completo de configuração no arquivo JSON."""
    _ensure_file()
    try:
        with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("[AFFILIATE_STORE] Config salva com sucesso.")
        return True
    except Exception as e:
        logger.error(f"[AFFILIATE_STORE] Erro ao salvar config: {e}")
        return False


def get_affiliate(store_key: str) -> dict:
    """
    Retorna a configuração de afiliado de uma loja específica.

    Args:
        store_key: "amazon" | "magalu" | "netshoes" | "mercadolivre" | "other"

    Returns:
        dict com a configuração. Ex.: {"tag": "seutag-20"} ou {"affiliate_url": "..."}
    """
    config = load_config()
    return config.get(store_key, {})


def set_affiliate(store_key: str, data: dict) -> bool:
    """
    Atualiza a configuração de afiliado de uma loja.

    Args:
        store_key: chave da loja
        data: dict com os campos a salvar

    Returns:
        True se salvou com sucesso.
    """
    config = load_config()
    if store_key not in config:
        config[store_key] = {}
    config[store_key].update(data)
    return save_config(config)


def build_affiliate_link(original_url: str, store_key: str) -> str | None:
    """
    Constrói o link de afiliado automático baseado na loja e config salva.

    Amazon:
        Adiciona ?tag=... ou &tag=... na URL resolvida do produto.
    Outras lojas:
        Retorna o affiliate_url configurado (substituindo o link original).
    Fallback:
        Retorna None se não houver afiliado configurado para a loja.

    Args:
        original_url: URL do produto (após resolução de redirects, para Amazon)
        store_key: chave interna da loja

    Returns:
        Link de afiliado pronto, ou None se não configurado.
    """
    aff = get_affiliate(store_key)
    if not aff:
        return None

    if store_key == "amazon":
        tag = aff.get("tag", "").strip()
        if not tag:
            logger.info("[AFFILIATE_STORE] Amazon: tag não configurada.")
            return None
        # Adiciona tag mantendo outros parâmetros
        separator = "&" if "?" in original_url else "?"
        link = f"{original_url}{separator}tag={tag}"
        logger.info(f"[AFFILIATE_STORE] Amazon: tag '{tag}' adicionada → {link[:80]}")
        return link

    # Outras lojas: usa o affiliate_url como link final
    aff_url = aff.get("affiliate_url", "").strip()
    if not aff_url:
        logger.info(f"[AFFILIATE_STORE] {store_key}: affiliate_url não configurada.")
        return None
    logger.info(f"[AFFILIATE_STORE] {store_key}: usando affiliate_url → {aff_url[:80]}")
    return aff_url
