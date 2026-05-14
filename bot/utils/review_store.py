import json
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_QUEUE_FILE = _DATA_DIR / "review_queue.json"

def save_review_queue(pending_offers: Dict):
    """Salva as ofertas pendentes em um JSON para o dashboard, preservando todos os campos."""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    
    # Prepara a lista para o JSON
    # Mantemos todos os campos originais para que o bot possa recuperar depois se necessário
    queue_list = []
    for oid, offer in pending_offers.items():
        item = offer.copy()
        item["id"] = oid
        # Garante campos básicos para a API/Dashboard
        if "titulo" not in item: item["titulo"] = item.get("nome", "Produto")
        if "preco" not in item: item["preco"] = item.get("dados_produto", {}).get("preco", "N/A")
        if "loja" not in item: item["loja"] = item.get("dados_produto", {}).get("store", "Loja")
        if "link" not in item: item["link"] = item.get("product_url", "")
        if "status" not in item: item["status"] = "pending"
        queue_list.append(item)
    
    try:
        with open(_QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue_list, f, indent=2, ensure_ascii=False)
        logger.info(f"[REVIEW_STORE] Fila de revisão salva com {len(queue_list)} itens.")
    except Exception as e:
        logger.error(f"[REVIEW_STORE] Erro ao salvar JSON: {e}")

def load_review_queue() -> Dict:
    """Carrega a fila de revisão do JSON."""
    if not _QUEUE_FILE.exists():
        return {}
    try:
        with open(_QUEUE_FILE, "r", encoding="utf-8") as f:
            queue_list = json.load(f)
            return {item["id"]: item for item in queue_list}
    except Exception as e:
        logger.error(f"[REVIEW_STORE] Erro ao carregar JSON: {e}")
        return {}
