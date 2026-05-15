"""
Telegram — парсинг товарів з каналу постачальника
Дедублікація по хешу контенту (назва + ціна + фото).
"""

import asyncio
import re
from collections import defaultdict
from deduplication import filter_new, mark_as_published, show_stats

try:
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto, MessageService
except ImportError:
    print("❌ Встанови telethon: pip install telethon")
    exit(1)

API_ID   = 0
API_HASH = ""
CHANNEL  = "@назва_каналу_постачальника"
LIMIT    = 50


def parse_post(messages: list) -> dict | None:
    """
    Приймає список повідомлень одного альбому (або одне повідомлення).
    Збирає текст і ВСІ фото групи.
    """
    # Шукаємо текст у будь-якому повідомленні групи
    text = ""
    for msg in messages:
        if msg.text:
            text = msg.text
            break

    if not text:
        return None

    lines = text.split("\n")
    post_message = messages[0]
    post_url = f"https://t.me/{CHANNEL.lstrip('@')}/{post_message.id}"
    post_date = post_message.date.strftime("%d.%m.%Y") if post_message.date else ""

    product = {
        "sku": "", "name": "", "brand": "", "price": "",
        "size": "", "color": "", "material": "", "gender": "",
        "condition": "Нове", "photos": [], "description": text,
        "post_url": post_url, "post_date": post_date,
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

    # Збираємо ВСІ фото з усіх повідомлень групи
    for msg in messages:
        if msg.media and isinstance(msg.media, MessageMediaPhoto):
            product["photos"].append(f"tg_photo_{msg.id}")

    # Для сумісності з рештою коду — рядок через кому
    product["photos"] = ",".join(product["photos"])

    return product if product["name"] else None


async def fetch_products():
    client = TelegramClient("session_parser", API_ID, API_HASH)
    await client.start()

    # Збираємо повідомлення, групуємо альбоми
    solo_messages = []           # одиночні повідомлення
    albums = defaultdict(list)   # grouped_id -> [messages]

    print(f"🔄 Читаємо канал {CHANNEL}...")

    async for message in client.iter_messages(CHANNEL, limit=LIMIT):
        # Пропускаємо сервісні повідомлення (зміна аватарки, назви каналу і т.д.)
        if isinstance(message, MessageService):
            continue
        if message.action is not None:
            continue

        if message.grouped_id:
            # Повідомлення є частиною альбому
            albums[message.grouped_id].append(message)
        else:
            solo_messages.append(message)

    await client.disconnect()

    # Обробляємо альбоми (список повідомлень → один товар)
    products = []
    for group_id, msgs in albums.items():
        product = parse_post(msgs)
        if product:
            products.append(product)

    # Обробляємо одиночні повідомлення
    for msg in solo_messages:
        product = parse_post([msg])
        if product:
            products.append(product)

    print(f"✅ Знайдено {len(products)} товарів")
    return products


async def main():
    products = await fetch_products()

    new_products, skipped = filter_new(products, source="telegram")

    if new_products:
        print(f"\n📋 Нові товари для публікації:")
        for p in new_products:
            print(f"  - {p['name']} | {p['price']} грн | фото: {len(p['photos'].split(','))}")
    else:
        print("✓ Нових товарів немає")

    show_stats()
    return new_products


if __name__ == "__main__":
    asyncio.run(main())