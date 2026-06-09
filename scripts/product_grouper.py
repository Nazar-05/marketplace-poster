"""
Модуль для групування варіацій товарів (різні кольори одного товару).

Логіка:
1. Парсимо товари по черзі
2. Групуємо товари з однаковою базовою назвою та описом
3. Об'єднуємо варіації в один пост з усіма кодами та фото
"""

import re
from typing import List, Dict
from difflib import SequenceMatcher

try:
    from scripts.color_extractor import extract_color, extract_base_name, extract_sku
except ModuleNotFoundError:
    from color_extractor import extract_color, extract_base_name, extract_sku


def similarity(a: str, b: str) -> float:
    """Повертає схожість двох рядків від 0 до 1."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def are_variations(product1: dict, product2: dict, threshold: float = 0.85) -> bool:
    """
    Перевіряє чи є два товари варіаціями одного товару.

    Критерії:
    - Базова назва схожа (без кольору)
    - Ціна однакова
    - Опис схожий (>85%)
    """
    # Порівнюємо базові назви
    base_name1 = extract_base_name(product1.get("name", ""))
    base_name2 = extract_base_name(product2.get("name", ""))

    if similarity(base_name1, base_name2) < threshold:
        return False

    # Порівнюємо ціни
    price1 = str(product1.get("price", "")).strip()
    price2 = str(product2.get("price", "")).strip()

    if price1 and price2 and price1 != price2:
        return False

    # Порівнюємо описи (без урахування кольору та коду товару)
    desc1 = product1.get("description", "")
    desc2 = product2.get("description", "")

    # Видаляємо коди товарів з описів для порівняння
    desc1_clean = re.sub(r'Код товару:\s*[A-Z0-9]+', '', desc1, flags=re.IGNORECASE)
    desc2_clean = re.sub(r'Код товару:\s*[A-Z0-9]+', '', desc2, flags=re.IGNORECASE)

    if similarity(desc1_clean, desc2_clean) < threshold:
        return False

    return True


def group_variations(products: List[dict]) -> List[dict]:
    """
    Групує товари-варіації в один товар.

    Повертає список товарів, де кожен товар може містити кілька варіацій.
    """
    if not products:
        return []

    grouped = []
    used = set()

    for i, product in enumerate(products):
        if i in used:
            continue

        # Створюємо групу для цього товару
        group = {
            "base_product": product,
            "variations": [product]
        }
        used.add(i)

        # Шукаємо варіації серед наступних товарів
        for j in range(i + 1, len(products)):
            if j in used:
                continue

            if are_variations(product, products[j]):
                group["variations"].append(products[j])
                used.add(j)

        grouped.append(group)

    return grouped


def merge_variations(group: dict) -> dict:
    """
    Об'єднує варіації в один товар.

    Повертає товар з:
    - Базовою назвою (без кольору)
    - Списком кодів товарів з кольорами
    - Всіма фото з усіх варіацій
    - Оригінальним описом (з першої варіації)
    """
    variations = group["variations"]
    base = group["base_product"]

    if len(variations) == 1:
        # Якщо тільки одна варіація, повертаємо як є
        return base

    # Витягуємо базову назву
    base_name = extract_base_name(base.get("name", ""))

    # Збираємо коди товарів з кольорами
    sku_color_pairs = []
    all_photos = []

    for var in variations:
        sku = extract_sku(var.get("description", ""))
        if not sku:
            sku = var.get("sku", "")

        color = extract_color(var)

        if sku:
            sku_color_pairs.append({"sku": sku, "color": color or "?"})

        # Збираємо фото
        photos = var.get("photos", "")
        if photos:
            all_photos.extend(photos.split(","))

    # Формуємо новий опис з кодами товарів
    description = base.get("description", "")

    # Видаляємо старий "Код товару:" якщо є
    description = re.sub(r'Код товару:\s*[A-Z0-9]+\s*\n?', '', description, flags=re.IGNORECASE)

    # Додаємо список кодів на початок опису
    if sku_color_pairs:
        codes_section = "Коди товару:\n"
        for pair in sku_color_pairs:
            codes_section += f"▫️{pair['sku']} - {pair['color']}\n"
        codes_section += "\n"

        # Вставляємо після першого рядка (назви)
        lines = description.split("\n")
        if lines:
            description = lines[0] + "\n\n" + codes_section + "\n".join(lines[1:])

    # Створюємо об'єднаний товар
    merged = base.copy()
    merged["name"] = base_name
    merged["description"] = description
    merged["photos"] = ",".join(all_photos)
    merged["variations_count"] = len(variations)
    merged["sku"] = ",".join([p["sku"] for p in sku_color_pairs])

    return merged


def process_products(products: List[dict]) -> List[dict]:
    """
    Основна функція: групує варіації та об'єднує їх.

    Приймає список товарів, повертає список де варіації об'єднані.
    """
    groups = group_variations(products)
    merged_products = []

    for group in groups:
        merged = merge_variations(group)
        merged_products.append(merged)

    return merged_products
