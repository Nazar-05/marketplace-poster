"""
KeyCRM — отримання товарів та замовлень
API docs: https://help.keycrm.app/uk/api

НАЛАШТУВАННЯ:
1. Вкажи свій API ключ нижче (KeyCRM → Налаштування → API)
2. Запусти: python keycrm_sync.py
"""

import requests
import json
from deduplication import filter_new, mark_as_published, show_stats

KEYCRM_BASE = "https://openapi.keycrm.app/v1"
KEYCRM_KEY  = "ВАШ_API_КЛЮЧ_ТУТ"

HEADERS = {
    "Authorization": f"Bearer {KEYCRM_KEY}",
    "Content-Type": "application/json",
}


def get_products(page: int = 1, limit: int = 50):
    response = requests.get(
        f"{KEYCRM_BASE}/products",
        headers=HEADERS,
        params={"page": page, "limit": limit}
    )
    response.raise_for_status()
    return response.json().get("data", [])


def get_all_products():
    """Отримати всі товари (всі сторінки)."""
    all_products, page = [], 1
    while True:
        batch = get_products(page=page)
        if not batch:
            break
        all_products.extend(batch)
        page += 1
    print(f"✅ Отримано {len(all_products)} товарів з KeyCRM")
    return all_products


def to_marketplace_format(product: dict) -> dict:
    """Конвертує товар KeyCRM у спільний формат."""
    offers = product.get("offers", [])
    sizes = [o.get("properties", {}).get("size", "") for o in offers if o.get("quantity", 0) > 0]
    photos = [a.get("url", "") for a in product.get("attachments", []) if a.get("url")]

    return {
        "sku":         product.get("sku", ""),       # SKU є в KeyCRM — перевірка по ньому
        "name":        product.get("name", ""),
        "brand":       product.get("brand", ""),
        "price":       str(product.get("price", "")),
        "size":        ", ".join(filter(None, sizes)),
        "color":       product.get("properties", {}).get("color", ""),
        "material":    "",
        "gender":      "",
        "condition":   "Нове",
        "photos":      ", ".join(photos),
        "description": product.get("description", ""),
    }


if __name__ == "__main__":
    print("🔄 KeyCRM: отримуємо товари...")

    try:
        raw = get_all_products()
        products = [to_marketplace_format(p) for p in raw]

        # Та ж сама логіка дедублікації по SKU — як і для MyDrop, і для будь-якої CRM
        new_products, skipped = filter_new(products, source="crm")

        if new_products:
            print(f"\n📋 Нові товари для публікації:")
            for p in new_products:
                print(f"  - {p['name']} (SKU: {p['sku']})")
        else:
            print("✓ Нових товарів немає — всі вже опубліковані")

        show_stats()

    except requests.exceptions.HTTPError as e:
        print(f"❌ Помилка API KeyCRM: {e}")
    except Exception as e:
        print(f"❌ Помилка: {e}")
