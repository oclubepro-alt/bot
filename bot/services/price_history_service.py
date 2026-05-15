"""
price_history_service.py - Registra e consulta o historico de precos de produtos.
Util para identificar 'Menor Preco' e variacoes significativas.
"""
import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

_HISTORY_PATH = Path(__file__).resolve().parents[2] / "data" / "price_history.json"

def _load_history() -> dict:
    try:
        if _HISTORY_PATH.exists():
            return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error(f"[PRICE_HISTORY] Erro ao carregar: {e}")
    return {}

def _save_history(data: dict) -> None:
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _HISTORY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error(f"[PRICE_HISTORY] Erro ao salvar: {e}")

def log_price(url: str, price_str: str) -> dict:
    """
    Registra o preco atual para a URL. 
    Retorna info se e o menor preco historico.
    """
    history = _load_history()
    
    # Limpeza basica do preco para comparacao numerica
    # Ex: "R$ 1.299,00" -> 1299.0
    try:
        clean_price = price_str.replace("R$", "").replace(".", "").replace(",", ".").strip()
        numeric_price = float(clean_price)
    except:
        numeric_price = None

    if url not in history:
        history[url] = {
            "lowest": numeric_price,
            "last": numeric_price,
            "history": []
        }
    
    is_lowest = False
    if numeric_price is not None:
        if history[url]["lowest"] is None or numeric_price < history[url]["lowest"]:
            history[url]["lowest"] = numeric_price
            is_lowest = True
        
        history[url]["last"] = numeric_price
        # Mantem apenas os ultimos 10 registros para nao inflar o JSON
        history[url]["history"].append({
            "p": numeric_price,
            "d": datetime.now().strftime("%Y-%m-%d")
        })
        history[url]["history"] = history[url]["history"][-10:]

    _save_history(history)
    
    return {
        "is_lowest": is_lowest,
        "lowest_price": history[url]["lowest"]
    }

def get_lowest_price(url: str) -> float | None:
    history = _load_history()
    if url in history:
        return history[url].get("lowest")
    return None
