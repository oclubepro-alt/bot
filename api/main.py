from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import json
from pathlib import Path
import os
from datetime import datetime

app = FastAPI(title="Bot de Achadinhos Admin API")

# CORS for Next.js
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
QUEUE_FILE = DATA_DIR / "review_queue.json"
STATS_FILE = DATA_DIR / "stats.json"

class Product(BaseModel):
    id: str
    titulo: str
    preco: str
    loja: str
    link: str
    imagem: Optional[str] = None
    created_at: str
    status: str = "pending" # pending, approved, rejected

def load_queue() -> List[dict]:
    if not QUEUE_FILE.exists():
        return []
    try:
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_queue(queue: List[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue, f, indent=2, ensure_ascii=False)

@app.get("/api/health")
async def get_health():
    # In a real scenario, we'd check the bot process status
    return {
        "status": "online",
        "bot_version": "5.0.0",
        "uptime": "24h 15m",
        "scrapers": {
            "amazon": "stable",
            "shopee": "stable",
            "magalu": "stable"
        },
        "timestamp": datetime.now().isoformat()
    }

@app.get("/api/queue", response_model=List[Product])
async def get_queue():
    return load_queue()

@app.post("/api/queue/{item_id}/approve")
async def approve_item(item_id: str):
    queue = load_queue()
    found = False
    for item in queue:
        if item["id"] == item_id:
            item["status"] = "approved"
            found = True
            # Here we would trigger the bot to publish
            break
    
    if not found:
        raise HTTPException(status_code=404, detail="Item not found")
    
    save_queue(queue)
    return {"message": "Item approved"}

@app.post("/api/queue/{item_id}/reject")
async def reject_item(item_id: str):
    queue = load_queue()
    queue = [item for item in queue if item["id"] != item_id]
    save_queue(queue)
    return {"message": "Item rejected"}

@app.get("/api/stats")
async def get_stats():
    return {
        "deals_today": 42,
        "deals_total": 1250,
        "approval_rate": "85%",
        "active_channels": 3
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
