"""
Модуль дедублікації — працює з будь-яким джерелом даних:
MyDrop, KeyCRM, будь-якою іншою CRM, або Telegram.

Логіка:
- Товар з CRM (є SKU) → перевірка по SKU
- Товар з Telegram (без SKU) → перевірка по хешу контенту
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "published.json"


def log(message: str):
    print(message)


def _load_db() -> dict:
    if DB_PATH.exists():
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"by_sku": {}, "by_hash": {}}


def _save_db(db: dict):
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


def make_hash(product: dict) -> str:
    """
    Хеш для товарів БЕЗ SKU (наприклад, з Telegram).
    Береться з назви, ціни та першого фото.
    """
    raw = f"{product.get('name','').strip().lower()}|{product.get('price','')}|{product.get('photos','').split(',')[0].strip()}"
    return hashlib.md5(raw.encode()).hexdigest()


def is_duplicate(product: dict, source: str = "crm") -> bool:
    """
    Перевіряє чи товар вже публікувався.

    source: "crm" або "telegram"
    """
    db = _load_db()

    if source == "crm" and product.get("sku"):
        return product["sku"] in db["by_sku"]
    else:
        return make_hash(product) in db["by_hash"]


def mark_as_published(product: dict, source: str = "crm", marketplaces: list = None):
    """
    Позначає товар як опублікований після успішного постингу.
    """
    db = _load_db()
    entry = {
        "name": product.get("name", ""),
        "published_at": datetime.now().isoformat(),
        "marketplaces": marketplaces or [],
        "source": source,
    }

    if source == "crm" and product.get("sku"):
        db["by_sku"][product["sku"]] = entry
    else:
        db["by_hash"][make_hash(product)] = entry

    _save_db(db)
    log(f"✅ Збережено: {product.get('name', '?')} [{source}]")


def filter_new(products: list, source: str = "crm") -> tuple[list, list]:
    """
    Приймає список товарів, повертає:
    - new_products: ті що ще не публікувались
    - skipped: ті що пропущені як дублікати
    """
    new_products, skipped = [], []
    for p in products:
        if is_duplicate(p, source):
            skipped.append(p)
        else:
            new_products.append(p)

    log(f"📦 Всього: {len(products)} | Нових: {len(new_products)} | Дублікатів: {len(skipped)}")
    return new_products, skipped


def show_stats():
    """Показує статистику опублікованих товарів."""
    db = _load_db()
    log(f"\n📊 Статистика бази:")
    log(f"  З CRM (по SKU):      {len(db['by_sku'])} товарів")
    log(f"  З Telegram (по хешу): {len(db['by_hash'])} товарів")
    log(f"  Всього:              {len(db['by_sku']) + len(db['by_hash'])} товарів\n")
