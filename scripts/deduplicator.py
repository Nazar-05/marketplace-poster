"""
deduplicator.py — універсальна перевірка дублікатів

Працює для будь-якої CRM або Telegram:
  - Товари з CRM  → перевірка по SKU / ID
  - Товари з Telegram → перевірка по хешу (назва + ціна + фото)

Зберігає стан у published.json (локальний файл, нічого платити).
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "published.json"


def _load() -> dict:
    if DB_PATH.exists():
        return json.loads(DB_PATH.read_text(encoding="utf-8"))
    return {"by_sku": {}, "by_hash": {}}


def _save(db: dict):
    DB_PATH.write_text(
        json.dumps(db, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def make_hash(product: dict) -> str:
    """
    Унікальний відбиток для товарів БЕЗ SKU (Telegram-пости).
    Рахується від назви + ціни + першого фото.
    """
    raw = "|".join([
        str(product.get("name", "")).strip().lower(),
        str(product.get("price", "")).strip(),
        str(product.get("photos", "").split(",")[0]).strip(),
    ])
    return hashlib.md5(raw.encode()).hexdigest()


def is_duplicate(product: dict, source: str = "crm") -> bool:
    """
    Перевіряє чи товар вже публікувався.

    product — словник з полями name, price, photos, sku (опційно)
    source  — "crm" або "telegram"

    Повертає True якщо дублікат, False якщо новий.
    """
    db = _load()
    sku = str(product.get("sku", "")).strip()

    if source == "crm" and sku:
        return sku in db["by_sku"]
    else:
        return make_hash(product) in db["by_hash"]


def mark_published(product: dict, source: str = "crm", marketplaces: list = None):
    """
    Записує товар як опублікований після успішного постингу.
    """
    db = _load()
    sku = str(product.get("sku", "")).strip()
    entry = {
        "name":        product.get("name", ""),
        "price":       product.get("price", ""),
        "source":      source,
        "marketplaces": marketplaces or [],
        "published_at": datetime.now().isoformat(),
    }

    if source == "crm" and sku:
        db["by_sku"][sku] = entry
    else:
        db["by_hash"][make_hash(product)] = entry

    _save(db)
    log(f"✅ Записано: {product.get('name', '')} [{source}]")


def get_stats() -> dict:
    """Статистика опублікованих товарів."""
    db = _load()
    return {
        "crm_products":      len(db["by_sku"]),
        "telegram_products": len(db["by_hash"]),
        "total":             len(db["by_sku"]) + len(db["by_hash"]),
    }


def reset(confirm: bool = False):
    """Очистити базу (тільки якщо confirm=True)."""
    if confirm:
        _save({"by_sku": {}, "by_hash": {}})
        log("🗑 База дублікатів очищена")
    else:
        log("⚠ Передай confirm=True щоб очистити базу")
