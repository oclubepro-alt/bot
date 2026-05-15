"""
price_utils.py - Utilitários para limpeza e formatação de preços.
"""
import re
import logging

logger = logging.getLogger(__name__)

def _parse_price_to_float(price_str: str) -> float | None:
    """
    Converte strings de preço em float, lidando com formatos variados:
    - R$ 49,90 -> 49.9
    - 1.249,00 -> 1249.0
    - 1,249.00 -> 1249.0 (Internacional)
    - 49 -> 49.0
    """
    if not price_str:
        return None
        
    if isinstance(price_str, (int, float)):
        return float(price_str)

    if not isinstance(price_str, str):
        return None

    try:
        # 1. Limpeza básica: remove parênteses e caracteres não numéricos (exceto , e .)
        text = re.sub(r"\(.*?\)", "", price_str)
        clean = re.sub(r'[^\d,.]', '', text)
        if not clean: return None

        # 2. Heurística para decidir o formato (BR vs US)
        last_comma = clean.rfind(',')
        last_dot = clean.rfind('.')

        if last_comma > last_dot:
            # Formato BR: 1.249,00
            clean = clean.replace('.', '').replace(',', '.')
        elif last_dot > last_comma:
            # Formato US: 1,249.00
            clean = clean.replace(',', '')
        elif last_comma != -1:
            # Só tem vírgula: 49,90
            clean = clean.replace(',', '.')

        val = float(clean)
        # Sanity check: preços absurdos (> 1M) costumam ser erro de parsing
        if val > 1000000:
            return None
        return val
    except Exception:
        return None


def _clean_price(raw: str) -> str | None:
    """Normaliza preço para exibição: R$ 1.299,90 (Para HTML)"""
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


def format_api_price(amount: any) -> str | None:
    """
    Formata um preço vindo de uma API (número ou string puramente numérica com ponto).
    Evita a heurística de _clean_price que pode confundir milhar com decimal.
    """
    if amount is None:
        return None
    try:
        # Se for string, remove símbolos mas mantém o ponto
        if isinstance(amount, str):
            # Remove R$, espaços, etc, mas preserva o ponto decimal
            amount = amount.replace("R$", "").replace(" ", "").replace(",", ".")
            # Se tiver múltiplos pontos, remove todos exceto o último
            if amount.count(".") > 1:
                parts = amount.split(".")
                amount = "".join(parts[:-1]) + "." + parts[-1]
        
        val = float(amount)
        reais = int(val)
        centavos = round(abs(val - reais) * 100)
        # Ajuste se centavos arredondar para 100
        if centavos == 100:
            reais += 1
            centavos = 0
            
        reais_fmt = f"{reais:,}".replace(",", ".")
        return f"R$ {reais_fmt},{centavos:02d}"
    except (ValueError, TypeError):
        return None
