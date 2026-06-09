"""
Модуль для витягування кольору з назви та опису товару.
Використовує комбінований підхід:
1. Шукає колір в кінці назви (перед дужками)
2. Шукає по списку відомих кольорів
3. Витягує з поля "Кольори:" в описі
"""

import re

# Список відомих кольорів українською
KNOWN_COLORS = [
    "чорний", "білий", "сірий графіт", "сірий",
    "бежевий", "коричневий", "синій", "червоний",
    "зелений", "жовтий", "помаранчевий", "рожевий",
    "фіолетовий", "молочний", "хакі", "бордовий",
    "темно-синій", "світло-сірий", "темно-зелений",
    "салатовий", "бірюзовий", "персиковий", "лавандовий",
    "мятний", "графіт", "олива", "пудровий", "капучіно",
    "карамель", "шоколад", "слива", "марсала", "індиго",
    "електрик", "неон", "металік", "золотий", "срібний",
    "мокко", "латте", "айворі", "екрю", "тауп"
]

# Сортуємо по довжині (спочатку довші) щоб "сірий графіт" знаходився раніше ніж "сірий"
KNOWN_COLORS.sort(key=len, reverse=True)


def extract_color_from_end(name: str) -> str:
    """
    Витягує колір з кінця назви перед дужками.
    Приклад: "Костюм Air чорний (льон жатка)" → "чорний"
    """
    # Видаляємо емодзі та зайві символи
    name_clean = re.sub(r'[📄🔥💥✨🎉]', '', name).strip()

    # Шукаємо 1-3 останні слова перед дужками
    # Приклад: "шорти чорний (льон)" → "чорний"
    # Приклад: "шорти сірий графіт (льон)" → "сірий графіт"
    match = re.search(r'\s+([а-яіїєґА-ЯІЇЄҐ]+(?:\s+[а-яіїєґА-ЯІЇЄҐ]+){0,2})\s*(?:\([^)]*\))?\s*\([^)]*\)\s*$', name_clean)
    if match:
        potential_color = match.group(1).strip().lower()

        # Перевіряємо чи це відомий колір (шукаємо найдовший збіг)
        for color in KNOWN_COLORS:
            if potential_color == color or potential_color.endswith(' ' + color):
                return color
            # Якщо potential_color містить колір в кінці
            if potential_color.split()[-1] == color or potential_color.split()[-2:] == color.split():
                return color
    return ""


def extract_color_from_text(text: str) -> str:
    """
    Шукає колір по списку відомих кольорів в тексті.
    """
    text_lower = text.lower()
    for color in KNOWN_COLORS:
        if color in text_lower:
            return color
    return ""


def extract_color_from_description(description: str) -> str:
    """
    Витягує колір з поля "Кольори:" в описі.
    Приклад: "▫️Кольори: чорний, сірий графіт, бежевий, білий;" → "чорний"
    Повертає перший колір зі списку.
    """
    # Шукаємо рядок з "Кольори:" або "Колір:"
    match = re.search(r'(?:кольори?|colors?):\s*([^\n;]+)', description, re.IGNORECASE)
    if match:
        colors_text = match.group(1).strip().lower()
        # Витягуємо перший колір зі списку
        for color in KNOWN_COLORS:
            if color in colors_text:
                return color
    return ""


def extract_color(product: dict) -> str:
    """
    Комбінований підхід: витягує колір з товару.

    Пріоритет:
    1. З кінця назви (найточніше)
    2. З поля color якщо воно є
    3. З поля "Кольори:" в описі
    4. Пошук по всій назві
    5. Пошук по всьому опису
    """
    name = product.get("name", "")
    description = product.get("description", "")
    color_field = product.get("color", "")

    # 1. Спробувати витягти з кінця назви
    color = extract_color_from_end(name)
    if color:
        return color

    # 2. Якщо є поле color
    if color_field:
        color = extract_color_from_text(color_field)
        if color:
            return color

    # 3. З поля "Кольори:" в описі
    color = extract_color_from_description(description)
    if color:
        return color

    # 4. Пошук по всій назві
    color = extract_color_from_text(name)
    if color:
        return color

    # 5. Пошук по всьому опису (останній варіант)
    color = extract_color_from_text(description)
    return color


def extract_base_name(name: str) -> str:
    """
    Витягує базову назву товару без кольору.
    Приклад: "Костюм Air чорний (льон жатка)" → "Костюм Air (льон жатка)"
    """
    # Видаляємо колір перед дужками
    for color in KNOWN_COLORS:
        # Шукаємо колір перед дужками
        pattern = rf'\s+{re.escape(color)}\s*(\([^)]+\))'
        match = re.search(pattern, name, re.IGNORECASE)
        if match:
            # Замінюємо "колір (матеріал)" на "(матеріал)"
            return re.sub(pattern, r' \1', name, flags=re.IGNORECASE).strip()

    return name


def extract_sku(text: str) -> str:
    """
    Витягує код товару з тексту.
    Приклад: "Код товару: RD557" → "RD557"
    """
    match = re.search(r'(?:код\s+товару|артикул|sku):\s*([A-Z0-9]+)', text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return ""
