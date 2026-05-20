"""
Telegram — парсинг товарів з каналів постачальників.

Паттерн кожного каналу задається в .env:
  TELEGRAM_CHANNELS=@channel1:A,@channel2:B,@channel3:C,@channel4:AUTO

  A    — спочатку медіа, потім окремий текст
  B    — спочатку текст, потім окремо медіа
  C    — текст вбудований у caption медіа
  AUTO — визначати автоматично

Прогрес зберігається у scripts/last_seen.json:
  { "@channel1": 12345, "@channel2": 67890 }
  Кожен наступний запуск читає тільки нові повідомлення після last_seen_id.
"""

import asyncio
import json
import os
import re
from pathlib import Path
from dotenv import load_dotenv
from deduplication import filter_new, show_stats

try:
    from telethon import TelegramClient
    from telethon.tl.types import MessageMediaPhoto, MessageService
except ImportError:
    print("❌ Встанови telethon: pip install telethon")
    exit(1)

load_dotenv()

API_ID              = int(os.getenv("TELEGRAM_API_ID") or "0")
API_HASH            = os.getenv("TELEGRAM_API_HASH", "")
TEXT_WINDOW_SECONDS = int(os.getenv("TEXT_WINDOW_SECONDS", "1200"))

# Файл де зберігається останній оброблений id для кожного каналу
LAST_SEEN_FILE = Path(__file__).parent / "last_seen.json"


# ---------------------------------------------------------------------------
# Збереження прогресу (last_seen_id)
# ---------------------------------------------------------------------------

def load_last_seen() -> dict:
    if LAST_SEEN_FILE.exists():
        with open(LAST_SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_last_seen(data: dict):
    with open(LAST_SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Читання каналів з .env
# ---------------------------------------------------------------------------

def parse_channels_config() -> list[dict]:
    """
    Читає TELEGRAM_CHANNELS з .env.
    Формат: @channel1:A,@channel2:B,@channel3:AUTO
    """
    raw = os.getenv("TELEGRAM_CHANNELS", "")
    channels = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue

        pattern = "AUTO"

        if entry.startswith("http"):
            # https://t.me/channel:A  або  https://t.me/channel (без паттерну)
            # Паттерн — одна-чотири літери в кінці після останнього ":"
            # але НЕ плутаємо з "https:"
            m = re.match(r"(https?://t\.me/[^:]+):([A-Za-z]{1,4})$", entry)
            if m:
                url     = m.group(1)
                pattern = m.group(2).upper()
            else:
                url = entry
            channel = re.sub(r"https?://t\.me/", "", url).strip()
        else:
            # @channel:A  або  channel:A  або  @channel
            if ":" in entry:
                channel, pattern = entry.rsplit(":", 1)
                pattern = pattern.strip().upper()
            else:
                channel = entry

        if pattern not in ("A", "B", "C", "AUTO"):
            pattern = "AUTO"

        channel = channel.strip().lstrip("@")
        channel = "@" + channel

        channels.append({"channel": channel, "pattern": pattern})
    return channels


# ---------------------------------------------------------------------------
# Утиліти
# ---------------------------------------------------------------------------

def get_timestamp(msg) -> float:
    return msg.date.timestamp() if msg.date else 0


def is_photo(msg) -> bool:
    return bool(msg.media and isinstance(msg.media, MessageMediaPhoto))


def is_text_only(msg) -> bool:
    return bool(msg.text and msg.text.strip() and not msg.media)


def is_product_text(text: str) -> bool:
    lower = text.lower()
    markers = [
        r"\d+\s*грн", r"ціна", r"price",
        r"розмір|size", r"колір|color",
        r"бренд|brand", r"матеріал|material",
        r"артикул|sku",
    ]
    return any(re.search(p, lower) for p in markers)


def parse_text(text: str) -> dict:
    lines = text.split("\n")
    fields = {
        "sku": "", "name": "", "brand": "", "price": "",
        "size": "", "color": "", "material": "", "gender": "",
        "condition": "Нове", "description": text,
    }
    for line in lines:
        lower = line.lower()
        val   = line.split(":", 1)[-1].strip() if ":" in line else ""

        if lower.startswith(("бренд", "brand")):         fields["brand"]    = val
        elif lower.startswith(("розмір", "size")):       fields["size"]     = val
        elif lower.startswith(("колір", "color")):       fields["color"]    = val
        elif lower.startswith(("матеріал", "material")): fields["material"] = val
        elif lower.startswith(("стан", "condition")):    fields["condition"]= val
        elif lower.startswith(("артикул", "sku")):       fields["sku"]      = val
        elif lower.startswith(("ціна", "price")) or "грн" in lower:
            m = re.search(r"\d+", line)
            if m:
                fields["price"] = m.group()

    for line in lines:
        s = line.strip()
        if s and ":" not in s and not re.fullmatch(r"[\d\s.,\-]+", s):
            fields["name"] = s
            break

    return fields


def build_product(media_msgs: list, text: str, channel: str, anchor_msg) -> dict | None:
    if not text or not media_msgs:
        return None
    fields = parse_text(text)
    if not fields["name"]:
        return None

    post_url  = f"https://t.me/{channel.lstrip('@')}/{anchor_msg.id}"
    post_date = anchor_msg.date.strftime("%d.%m.%Y") if anchor_msg.date else ""
    photos    = [f"tg_photo_{m.id}" for m in media_msgs if is_photo(m)]

    return {**fields, "photos": ",".join(photos), "post_url": post_url, "post_date": post_date}


# ---------------------------------------------------------------------------
# Побудова блоків
# ---------------------------------------------------------------------------

def build_blocks(messages: list) -> list[dict]:
    blocks = []
    seen_grouped = {}

    for msg in sorted(messages, key=get_timestamp):
        if msg.grouped_id:
            if msg.grouped_id in seen_grouped:
                idx = seen_grouped[msg.grouped_id]
                blocks[idx]["msgs"].append(msg)
                blocks[idx]["ts_end"] = max(blocks[idx]["ts_end"], get_timestamp(msg))
                if msg.text and msg.text.strip() and not blocks[idx]["caption"]:
                    blocks[idx]["caption"] = msg.text.strip()
            else:
                idx = len(blocks)
                seen_grouped[msg.grouped_id] = idx
                blocks.append({
                    "type": "media", "msgs": [msg],
                    "ts": get_timestamp(msg), "ts_end": get_timestamp(msg),
                    "caption": msg.text.strip() if msg.text else "",
                })
        elif is_photo(msg):
            blocks.append({
                "type": "media", "msgs": [msg],
                "ts": get_timestamp(msg), "ts_end": get_timestamp(msg),
                "caption": msg.text.strip() if msg.text else "",
            })
        elif is_text_only(msg):
            blocks.append({
                "type": "text", "msgs": [msg],
                "ts": get_timestamp(msg), "text": msg.text.strip(),
            })

    return blocks


# ---------------------------------------------------------------------------
# Стратегії групування
# ---------------------------------------------------------------------------

def group_pattern_c(blocks: list, channel: str) -> list[dict]:
    """C: текст вбудований у caption медіа."""
    products = []
    for b in blocks:
        if b["type"] == "media" and b["caption"]:
            p = build_product(b["msgs"], b["caption"], channel, b["msgs"][0])
            if p:
                products.append(p)
    return products


def group_pattern_a(blocks: list, channel: str) -> list[dict]:
    """A: медіа → текст."""
    n, used, products = len(blocks), [False] * len(blocks), []
    i = 0
    while i < n:
        if used[i] or blocks[i]["type"] != "media":
            i += 1; continue

        media_msgs = list(blocks[i]["msgs"])
        last_ts    = blocks[i]["ts_end"]
        anchor     = blocks[i]["msgs"][0]
        used[i]    = True
        j          = i + 1

        while j < n and not used[j] and blocks[j]["type"] == "media" and not blocks[j]["caption"]:
            if blocks[j]["ts"] - last_ts > TEXT_WINDOW_SECONDS:
                break
            media_msgs.extend(blocks[j]["msgs"])
            last_ts = blocks[j]["ts_end"]
            used[j] = True; j += 1

        text = blocks[i].get("caption", "")
        if not text and j < n and not used[j] and blocks[j]["type"] == "text":
            if blocks[j]["ts"] - last_ts <= TEXT_WINDOW_SECONDS:
                text = blocks[j]["text"]
                used[j] = True; j += 1

        p = build_product(media_msgs, text, channel, anchor)
        if p:
            products.append(p)
        i = j

    return products


def group_pattern_b(blocks: list, channel: str) -> list[dict]:
    """B: текст → медіа."""
    n, used, products = len(blocks), [False] * len(blocks), []
    i = 0
    while i < n:
        if used[i] or blocks[i]["type"] != "text":
            i += 1; continue

        text_val = blocks[i]["text"]
        last_ts  = blocks[i]["ts"]
        j        = i + 1
        media_msgs, anchor = [], None

        while j < n and not used[j] and blocks[j]["type"] == "media" and not blocks[j]["caption"]:
            if blocks[j]["ts"] - last_ts > TEXT_WINDOW_SECONDS:
                break
            if anchor is None:
                anchor = blocks[j]["msgs"][0]
            media_msgs.extend(blocks[j]["msgs"])
            last_ts = blocks[j]["ts_end"]
            used[j] = True; j += 1

        if media_msgs:
            p = build_product(media_msgs, text_val, channel, anchor)
            if p:
                products.append(p)
            used[i] = True
            i = j
        else:
            i += 1

    return products


def group_pattern_auto(blocks: list, channel: str) -> list[dict]:
    """AUTO: пробує всі три, повертає найкращий результат."""
    results_c   = group_pattern_c(blocks, channel)
    non_caption = [b for b in blocks if not (b["type"] == "media" and b["caption"])]
    results_a   = group_pattern_a(non_caption, channel)
    results_b   = group_pattern_b(non_caption, channel)
    best_ab     = results_a if len(results_a) >= len(results_b) else results_b
    return results_c + best_ab


PATTERN_HANDLERS = {
    "A": group_pattern_a,
    "B": group_pattern_b,
    "C": group_pattern_c,
    "AUTO": group_pattern_auto,
}


# ---------------------------------------------------------------------------
# Telethon: завантаження
# ---------------------------------------------------------------------------

async def fetch_channel(client: TelegramClient, channel: str, pattern: str, last_seen_id: int) -> tuple[list[dict], int]:
    """
    Повертає (products, max_id).
    max_id — найбільший id серед прочитаних повідомлень,
    зберігається як нова точка відліку для наступного запуску.
    """
    print(f"🔄 [{pattern}] {channel} (нові після id={last_seen_id})...")

    raw = []
    # min_id=last_seen_id — Telethon поверне лише повідомлення з id > last_seen_id
    async for msg in client.iter_messages(channel, min_id=last_seen_id):
        if isinstance(msg, MessageService) or msg.action is not None:
            continue
        raw.append(msg)

    if not raw:
        print(f"   ✓ Нових повідомлень немає")
        return [], last_seen_id

    max_id = max(msg.id for msg in raw)
    print(f"   📨 {len(raw)} нових повідомлень (до id={max_id})")

    blocks   = build_blocks(raw)
    handler  = PATTERN_HANDLERS[pattern]
    products = handler(blocks, channel)

    print(f"   ✅ {len(products)} товарів знайдено")
    return products, max_id


async def fetch_all_products() -> list[dict]:
    channels  = parse_channels_config()
    if not channels:
        print("❌ TELEGRAM_CHANNELS не задано в .env")
        return []

    last_seen = load_last_seen()
    client    = TelegramClient("session_parser", API_ID, API_HASH)
    await client.start()

    all_products = []
    for cfg in channels:
        channel = cfg["channel"]
        pattern = cfg["pattern"]
        last_id = last_seen.get(channel, 0)

        try:
            products, new_last_id = await fetch_channel(client, channel, pattern, last_id)
            all_products.extend(products)

            # Зберігаємо прогрес навіть якщо товарів не знайшли —
            # щоб не перечитувати ці ж повідомлення наступного разу
            if new_last_id > last_id:
                last_seen[channel] = new_last_id

        except Exception as e:
            print(f"❌ Помилка з {channel}: {e}")

    await client.disconnect()
    save_last_seen(last_seen)
    return all_products


# ---------------------------------------------------------------------------
# Точка входу
# ---------------------------------------------------------------------------

async def main():
    products = await fetch_all_products()

    new_products, skipped = filter_new(products, source="telegram")

    if new_products:
        print(f"\n📋 Нові товари для публікації ({len(new_products)}):")
        for p in new_products:
            photo_count = len(p["photos"].split(",")) if p["photos"] else 0
            print(f"  - {p['name']} | {p['price']} грн | фото: {photo_count} | {p['post_url']}")
    else:
        print("\n✓ Нових товарів немає")

    show_stats()
    return new_products


if __name__ == "__main__":
    asyncio.run(main())