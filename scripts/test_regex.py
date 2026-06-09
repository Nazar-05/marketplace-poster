import sys
import io
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

KNOWN_COLORS = [
    "чорний", "білий", "сірий графіт", "сірий",
    "бежевий", "коричневий", "синій", "червоний",
    "зелений", "жовтий", "помаранчевий", "рожевий",
    "фіолетовий", "молочний", "хакі", "бордовий",
]
KNOWN_COLORS.sort(key=len, reverse=True)

names = [
    '📄Чоловічий літній костюм Air сорочка шорти чорний (льон жатка)📄',
    '📄Чоловічий літній костюм Air сорочка шорти сірий графіт (льон жатка)📄',
    '📄Чоловічий літній костюм Air сорочка шорти бежевий (льон жатка)📄',
    '📄Чоловічий літній костюм Air сорочка шорти білий (молочний) (льон жатка)📄'
]

print("Аналіз витягування кольорів:\n")

for i, name in enumerate(names, 1):
    print(f"{i}. Назва: {name}")

    # Видаляємо емодзі
    clean = re.sub(r'[📄🔥💥✨🎉]', '', name).strip()

    # Шукаємо 1-3 останні слова перед дужками
    match = re.search(r'\s+([а-яіїєґА-ЯІЇЄҐ]+(?:\s+[а-яіїєґА-ЯІЇЄҐ]+){0,2})\s*(?:\([^)]*\))?\s*\([^)]*\)\s*$', clean)
    if match:
        potential = match.group(1).strip().lower()
        print(f"   Знайдено: '{potential}'")

        # Перевіряємо чи це колір
        found_color = None
        for color in KNOWN_COLORS:
            if potential == color or potential.endswith(' ' + color):
                found_color = color
                break
            if potential.split()[-1] == color or potential.split()[-2:] == color.split():
                found_color = color
                break

        if found_color:
            print(f"   ✅ Колір: {found_color}")
        else:
            print(f"   ❌ Колір не розпізнано")
    else:
        print(f"   ❌ Не знайдено")
    print()

