"""
Telegram — парсинг товарів з каналу постачальника
Дедублікація по хешу контенту (назва + ціна + фото).

НАЛАШТУВАННЯ:
1. Вкажи API_ID та API_HASH нижче (https://my.telegram.org → App configuration)
2. Вкажи USERNAME каналу постачальника
3. Запусти: python telegram_parser.py
"""

import asyncio
import re
from deduplication import filter_new, mark_as_published, show_stats

try:
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto
except ImportError:
    log("❌ Встанови telethon: pip install telethon")
    exit(1)

API_ID   = 0
API_HASH = ""
CHANNEL  = "@назва_каналу_постачальника"
LIMIT    = 50


def parse_post(message) -> dict | None:
    text = message.text or ""
    if not text:
        return None

    lines = text.split("\n")
    product = {
        "sku": "", "name": "", "brand": "", "price": "",
        "size": "", "color": "", "material": "", "gender": "",
        "condition": "Нове", "photos": "", "description": text,
    }

    for line in lines:
        lower = line.lower()
        val   = line.split(":", 1)[-1].strip() if ":" in line else ""

        if lower.startswith(("бренд", "brand")):         product["brand"]    = val
        elif lower.startswith(("розмір", "size")):       product["size"]     = val
        elif lower.startswith(("колір", "color")):       product["color"]    = val
        elif lower.startswith(("матеріал", "material")): product["material"] = val
        elif lower.startswith(("ціна", "price")) or "грн" in lower:
            m = re.search(r"\d+", line)
            if m:
                product["price"] = m.group()

    for line in lines:
        if line.strip() and ":" not in line:
            product["name"] = line.strip()
            break

    if message.media and isinstance(message.media, MessageMediaPhoto):
        product["photos"] = f"tg_photo_{message.id}"

    return product if product["name"] else None


async def fetch_products():
    client = TelegramClient("session_parser", API_ID, API_HASH)
    await client.start()

    products = []
    log(f"🔄 Читаємо канал {CHANNEL}...")

    async for message in client.iter_messages(CHANNEL, limit=LIMIT):
        if message.action is not None:
            continue
        product = parse_post(message)
        if product:
            products.append(product)

    await client.disconnect()
    log(f"✅ Знайдено {len(products)} товарів")
    return products


async def main():
    products = await fetch_products()

    # Дедублікація по хешу — бо SKU у Telegram немає
    new_products, skipped = filter_new(products, source="telegram")

    if new_products:
        log(f"\n📋 Нові товари для публікації:")
        for p in new_products:
            log(f"  - {p['name']} | {p['price']} грн")
    else:
        log("✓ Нових товарів немає")

    show_stats()
    return new_products


if __name__ == "__main__":
    asyncio.run(main())
