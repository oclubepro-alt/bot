
import re

def _parse_price_to_float(text: str) -> float | None:
    if not text: return None
    # Normaliza: remove espaço não-quebrável (\xa0) e parenteséticos
    text = str(text).replace('\u00a0', ' ').replace('\xa0', ' ')
    text = re.sub(r"\(.*?\)", "", text)
    cleaned = re.sub(r"[^\d,.]", "", text)
    if not cleaned: return None
    
    if "," in cleaned:
        # Padrão BR: 1.299,90 -> 1299.90
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        # Padrão Internacional ou BR sem decimal: 399.00 ou 1.200
        # Se houver apenas um ponto e ele estiver na posição de centavos (2 antes do fim), 
        # é provável que seja decimal (comum em JSON-LD).
        parts = cleaned.split('.')
        if len(parts) == 2 and len(parts[1]) == 2:
            # Caso 399.00 -> mantém o ponto
            pass
        else:
            # Caso 1.200 -> remove o ponto (milhar)
            cleaned = cleaned.replace(".", "")
            
    try:
        return float(cleaned)
    except Exception:
        return None

# Test cases
tests = [
    ("R$ 1.299,90", 1299.9),
    ("399.00", 399.0),
    ("91,99", 91.99),
    ("R$ 1.020", 1020.0),
    ("R$ 189,90", 189.9),
    ("R$ 1,28", 1.28),
]

for inp, expected in tests:
    res = _parse_price_to_float(inp)
    print(f"Input: {inp:15} | Expected: {expected:8} | Result: {res:8} | {'OK' if res == expected else 'FAIL'}")
