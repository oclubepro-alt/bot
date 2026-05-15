"""
price_utils.py - Utilitarios para limpeza e formatacao de precos.
"""
import re
import logging

logger = logging.getLogger(__name__)

def _parse_price_to_float(price_str: str) -> float | None:
    """
    Converte strings de preco em float, lidando com formatos variados:
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
        # 1. Limpeza basica: remove parênteses e caracteres nao numericos (exceto , e .)
        text = re.sub(r"\(.*?\)", "", price_str)
        clean = re.sub(r'[^\d,.]', '', text)
        if not clean: return None

        # 2. Heuristica para decidir o formato (BR vs US)
        last_comma = clean.rfind(',')
        last_dot = clean.rfind('.')

        if last_comma > last_dot:
            # Formato BR: 1.249,00
            clean = clean.replace('.', '').replace(',', '.')
        elif last_dot > last_comma:
            # Formato US: 1,249.00
            clean = clean.replace(',', '')
        elif last_comma != -1:
            # So tem virgula: 49,90
            clean = clean.replace(',', '.')

        val = float(clean)
        # Sanity check: precos absurdos (> 1M) costumam ser erro de parsing
        if val > 1000000:
            return None
        return val
    except Exception:
        return None


def _clean_price(raw: str) -> str | None:
    """Normaliza preco para exibicao: R$ 1.299,90 (Para HTML)"""
    if not raw:
        return None
    val = _parse_price_to_float(raw)
    if val is None:
        return None
    # Re-formata no padrao BR
    reais = int(val)
    centavos = round((val - reais) * 100)
    reais_fmt = f"{reais:,}".replace(",", ".")
    return f"R$ {reais_fmt},{centavos:02d}"


def format_api_price(amount: any) -> str | None:
    """
    Formata um preco vindo de uma API (numero ou string puramente numerica com ponto).
    Evita a heuristica de _clean_price que pode confundir milhar com decimal.
    """
    if amount is None:
        return None
    try:
        # Se for string, remove simbolos mas mantem o ponto
        if isinstance(amount, str):
            # Remove R$, espacos, etc, mas preserva o ponto decimal
            amount = amount.replace("R$", "").replace(" ", "").replace(",", ".")
            # Se tiver multiplos pontos, remove todos exceto o ultimo
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
