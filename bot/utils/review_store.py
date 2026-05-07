import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_QUEUE_FILE = _DATA_DIR / "review_queue.json"

def save_review_queue(pending_offers: Dict):
    """Salva as ofertas pendentes em um JSON para o dashboard."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Formata para o padrão da API
    api_list = []
    for oid, offer in pending_offers.items():
        api_list.append({
            "id": oid,
            "titulo": offer.get("nome", "Produto"),
            "preco": offer.get("preco", "N/A"),
            "loja": offer.get("source_name", "Loja"),
            "link": offer.get("product_url", ""),
            "imagem": offer.get("imagem"),
            "created_at": offer.get("created_at", ""),
            "status": "pending"
        })
    
    try:
        with open(_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(api_list, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[REVIEW_STORE] Erro ao salvar JSON: {e}")
