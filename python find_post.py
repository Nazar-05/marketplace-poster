import requests, re

page = "https://t.me/s/men_channel_ua"
ch = "men_channel_ua"
count = 0

while page:
    r = requests.get(page, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    urls = re.findall(r"https://t\.me/men_channel_ua/\d+", r.text)
    count += 1
    dates = re.findall(r'datetime="(\d{4}-\d{2}-\d{2})"', r.text)
    min_date = min(dates) if dates else "немає"

    if any("132920" in u for u in urls):
        print(f"Знайдено на сторінці {count}! Мін дата: {min_date}")
        break

    print(f"Сторінка {count}, мін дата: {min_date}, йдемо далі...")

    if dates and min(dates) < "2026-01-01":
        print(f"СТОП — скрипт зупинився б тут через стару дату!")
        break

    m = re.search(r'href="/s/men_channel_ua\?before=(\d+)"', r.text)
    if not m:
        print(f"Немає наступної сторінки на сторінці {count}")
        break

    page = f"https://t.me/s/{ch}?before={m.group(1)}"
import time; time.sleep(2)