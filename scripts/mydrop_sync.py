"""
MyDrop CRM — отримання товарів та синхронізація (дропшипер)
API docs: https://api.mydrop.com.ua/

НАЛАШТУВАННЯ:
1. Вкажи свій API токен нижче (MyDrop → Інтеграції → API ключ)
2. Запусти: python mydrop_sync.py
"""

import requests
import json
from deduplication import filter_new, mark_as_published, show_stats

MYDROP_BASE  = "https://backend.mydrop.com.ua/api"
MYDROP_TOKEN = "ВАШ_API_ТОКЕН_ТУТ"

HEADERS = {
    "X-API-KEY": MYDROP_TOKEN,
    "Content-Type": "application/json",
}


def get_products():
    """Отримати каталог товарів від постачальників."""
    response = requests.get(f"{MYDROP_BASE}/products", headers=HEADERS)
    response.raise_for_status()
    products = response.json()
    print(f"✅ Отримано {len(products)} товарів з MyDrop")
    return products


def to_marketplace_format(product: dict) -> dict:
    """Конвертує товар MyDrop у спільний формат."""
    sizes = product.get("sizes", [])
    size_str = ", ".join([s["title"] for s in sizes if s.get("amount", 0) > 0])

    return {
        "sku":         product.get("sku", ""),
        "name":        product.get("title", ""),
        "brand":       product.get("brand", ""),
        "price":       str(product.get("price", "")),
        "size":        size_str,
        "color":       product.get("color", ""),
        "material":    product.get("material", ""),
        "gender":      product.get("gender", ""),
        "condition":   "Нове",
        "photos":      ", ".join(product.get("images", [])),
        "description": product.get("description", ""),
    }


def create_order(product_sku: str, quantity: int = 1, customer: dict = None):
    """Створити замовлення у постачальника після продажу."""
    payload = {
        "sku": product_sku,
        "quantity": quantity,
        "customer": customer or {},
    }
    response = requests.post(f"{MYDROP_BASE}/orders", headers=HEADERS, json=payload)
    response.raise_for_status()
    print(f"✅ Замовлення створено для SKU: {product_sku}")
    return response.json()


if __name__ == "__main__":
    print("🔄 MyDrop: отримуємо товари...")

    try:
        raw = get_products()
        products = [to_marketplace_format(p) for p in raw]

        # Фільтрація дублікатів (по SKU — працює для будь-якої CRM)
        new_products, skipped = filter_new(products, source="crm")

        if new_products:
            print(f"\n📋 Нові товари для публікації:")
            for p in new_products:
                print(f"  - {p['name']} (SKU: {p['sku']})")
        else:
            print("✓ Нових товарів немає — всі вже опубліковані")

        show_stats()

    except requests.exceptions.HTTPError as e:
        print(f"❌ Помилка API MyDrop: {e}")
    except Exception as e:
        print(f"❌ Помилка: {e}")
