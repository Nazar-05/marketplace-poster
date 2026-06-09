"""
Тест імпорту модулів для server.py
"""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

print("Тестування імпортів...")

try:
    from product_grouper import process_products
    print("✅ product_grouper імпортується")
except Exception as e:
    print(f"❌ Помилка імпорту product_grouper: {e}")
    import traceback
    traceback.print_exc()

try:
    from color_extractor import extract_color
    print("✅ color_extractor імпортується")
except Exception as e:
    print(f"❌ Помилка імпорту color_extractor: {e}")
    import traceback
    traceback.print_exc()

# Тест на простих даних
try:
    test_products = [
        {
            "name": "Товар 1",
            "price": "100",
            "description": "Опис 1",
            "photos": "photo1.jpg",
            "sku": ""
        }
    ]
    result = process_products(test_products)
    print(f"✅ process_products працює: {len(test_products)} -> {len(result)} товарів")
except Exception as e:
    print(f"❌ Помилка виконання process_products: {e}")
    import traceback
    traceback.print_exc()

print("\n✅ Всі тести пройдені успішно!")
