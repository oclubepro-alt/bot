"""
data_pipeline.py — Limpeza e validação de dados de e-commerce.

Responsabilidades:
  1. Limpar o nome do produto (remove ruídos de scraping).
  2. Converter preço bruto em float.
  3. Validar se o preço não é suspeito (>50% de desvio da média histórica).
  4. Retornar dict padronizado com status "valid" ou "ERRO: PREÇO_SUSPEITO".

Usage:
    from bot.services.data_pipeline import process_product_data
    result = process_product_data(raw_nome, raw_preco, loja, store_key)
"""
import re
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ruídos comuns que devem ser removidos do nome
# ---------------------------------------------------------------------------
_NOISE_PATTERNS: list[str] = [
    r"frete\s+gr[aá]tis",
    r"em\s+estoque",
    r"promo[çc][aã]o\s+limitada",
    r"oferta\s+limitada",
    r"limited\s+offer",
    r"\bfree\s+shipping\b",
    r"\bstock\b",
    r"\bPromo[çc][aã]o\b",
    r"\bPromo\b",
    r"\|\s*$",            # pipe no final
    r"-\s*$",            # traço no final
]
_NOISE_RE = re.compile(
    "|".join(_NOISE_PATTERNS), re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Histórico de preços médios por loja/categoria (seed inicial)
# Caminho: data/price_history.json
# Estrutura: { "amazon": {"iphone": 5000.0, ...}, ... }
# ---------------------------------------------------------------------------
_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_HISTORY_FILE = _DATA_DIR / "price_history.json"

_DEFAULT_HISTORY: dict = {
    "amazon":        {},
    "mercadolivre":  {},
    "magalu":        {},
    "netshoes":      {},
    "other":         {},
}

SUSPICIOUS_DEVIATION = 0.50   # 50 % de desvio máximo


# ── Helpers ─────────────────────────────────────────────────────────────────

def _load_history() -> dict:
    """Carrega histórico de preços do JSON (cria se não existir)."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _HISTORY_FILE.exists():
        _HISTORY_FILE.write_text(
            json.dumps(_DEFAULT_HISTORY, indent=2, ensure_ascii=False)
        )
        logger.info("[PIPELINE] price_history.json criado.")
    try:
        with open(_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"[PIPELINE] Erro ao ler histórico: {e}. Usando padrão vazio.")
        return dict(_DEFAULT_HISTORY)


def _save_history(history: dict) -> None:
    try:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[PIPELINE] Erro ao salvar histórico: {e}")


def _normalize_key(nome: str) -> str:
    """Gera chave simples de produto para lookup no histórico."""
    return re.sub(r"[^a-z0-9]", "_", nome.lower().strip())[:60]


def clean_name(raw: str) -> str:
    """
    Limpa o nome do produto removendo strings de ruído.

    Args:
        raw: Nome bruto capturado pelo scraper (pode conter lixo).

    Returns:
        Nome limpo e normalizado.
    """
    if not raw:
        return ""
    cleaned = _NOISE_RE.sub("", raw)
    # Normaliza espaços múltiplos e remove pontuação solta no final
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" |,-")
    logger.debug(f"[PIPELINE] Nome limpo: '{raw[:60]}' → '{cleaned[:60]}'")
    return cleaned


def parse_price(raw_preco: str) -> float | None:
    """
    Converte string de preço PT-BR em float.

    Exemplos:
        "R$ 1.299,99" → 1299.99
        "R$ 49,90"    → 49.90
        "3500"        → 3500.0

    Returns:
        float ou None se não for possível converter.
    """
    if not raw_preco:
        return None
    # Remove símbolo e espaços
    s = re.sub(r"[R$\s]", "", raw_preco)
    # Formato PT-BR: 1.299,99 → 1299.99
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d{2})?$", s):
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        # 49,90 → 49.90
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        logger.warning(f"[PIPELINE] Não foi possível converter preço: '{raw_preco}'")
        return None


def validate_price(
    price_float: float,
    store_key: str,
    product_key: str,
    *,
    update_history: bool = True,
) -> str:
    """
    Valida o preço contra o histórico.

    Se o preço estiver >50% diferente da média histórica, marca como suspeito.
    Se não houver histórico, aceita e registra o preço.

    Args:
        price_float:    Preço em float.
        store_key:      Chave da loja (ex: "amazon").
        product_key:    Chave normalizada do produto.
        update_history: Se True, atualiza a média histórica após validar.

    Returns:
        "valid" ou "ERRO: PREÇO_SUSPEITO"
    """
    history = _load_history()
    store_hist = history.setdefault(store_key, {})
    avg = store_hist.get(product_key)

    if avg is not None:
        diff = abs(price_float - avg) / avg
        if diff > SUSPICIOUS_DEVIATION:
            logger.warning(
                f"[PIPELINE] ⚠️ PREÇO SUSPEITO — {store_key}/{product_key}: "
                f"atual={price_float:.2f} | média={avg:.2f} | desvio={diff:.0%}"
            )
            return "ERRO: PREÇO_SUSPEITO"

    # Atualiza média histórica (média móvel simples com peso 0.3)
    if update_history:
        if avg is None:
            store_hist[product_key] = price_float
        else:
            store_hist[product_key] = round(avg * 0.7 + price_float * 0.3, 2)
        _save_history(history)

    return "valid"


# ── Ponto de entrada principal ───────────────────────────────────────────────

def process_product_data(
    raw_nome: str | None,
    raw_preco: str | None,
    loja: str,
    store_key: str,
) -> dict:
    """
    Pipeline principal: limpa, converte e valida dados de produto.

    Args:
        raw_nome:   Nome bruto do produto.
        raw_preco:  Preço bruto (string PT-BR).
        loja:       Nome de exibição da loja.
        store_key:  Chave interna da loja.

    Returns:
        {
            "nome":       str (limpo),
            "preco":      str (formatado) | None,
            "preco_float": float | None,
            "loja":       str,
            "store_key":  str,
            "status":     "valid" | "ERRO: PREÇO_SUSPEITO",
        }
    """
    # 1. Limpeza do nome
    nome_limpo = clean_name(raw_nome or "")

    # 2. Conversão de preço
    preco_float = parse_price(raw_preco or "")
    preco_formatado = None
    if preco_float is not None:
        preco_formatado = f"R$ {preco_float:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # 3. Validação de preço suspeito
    status = "valid"
    if preco_float is not None and nome_limpo:
        product_key = _normalize_key(nome_limpo)
        status = validate_price(preco_float, store_key, product_key)

    result = {
        "nome":        nome_limpo,
        "preco":       preco_formatado or raw_preco,  # mantém original se não converteu
        "preco_float": preco_float,
        "loja":        loja,
        "store_key":   store_key,
        "status":      status,
    }

    logger.info(
        f"[PIPELINE] ── Resultado do pipeline ──────────────────────\n"
        f"[PIPELINE] Nome    : {result['nome'][:60]}\n"
        f"[PIPELINE] Preço   : {result['preco']} ({preco_float})\n"
        f"[PIPELINE] Status  : {status}"
    )

    return result
