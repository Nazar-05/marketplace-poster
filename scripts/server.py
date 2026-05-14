"""
Локальний сервер для автозаповнення форми товару.

Запуск (один раз, залиш відкритим):
    python server.py

Сервер: http://localhost:5001
"""

import re, json, os, uuid, requests
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Завантажуємо .env
ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)

app        = Flask(__name__)
CORS(app)
PHOTOS_DIR = Path(__file__).parent / "photos"
PHOTOS_DIR.mkdir(exist_ok=True)

# ── .env helpers ──────────────────────────────────────────
def get_env(key, default=""):
    return os.getenv(key, default) or default

def set_env(key, value):
    """Оновлює значення в .env файлі."""
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.environ[key] = value  # оновлюємо в пам'яті

# ── Завантаження фото локально ────────────────────────────
def download_photo(url: str) -> str | None:
    """
    Скачує фото за URL, зберігає в папку photos/.
    Повертає локальний URL: http://localhost:5001/photos/filename.jpg
    """
    if not url or not url.startswith("http"):
        return None
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=15, stream=True)
        resp.raise_for_status()

        # Визначаємо розширення
        ct = resp.headers.get("Content-Type", "")
        ext = ".jpg"
        if "png" in ct:  ext = ".png"
        elif "webp" in ct: ext = ".webp"
        elif "gif" in ct:  ext = ".gif"

        filename = f"{uuid.uuid4().hex}{ext}"
        filepath = PHOTOS_DIR / filename
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)

        return f"http://localhost:5001/photos/{filename}"
    except Exception as e:
        print(f"⚠️ Не вдалось скачати фото {url}: {e}")
        return None

# ── Парсинг тексту товару ─────────────────────────────────
def parse_text(text: str) -> dict:
    lines = text.split("\n")
    product = { "name":"","brand":"","price":"","size":"","color":"","material":"","gender":"","condition":"Нове","category":"","supplier":"","description":text,"photos":"" }
    for line in lines:
        line = line.strip()
        if not line: continue
        lower = line.lower()
        val = line.split(":",1)[-1].strip() if ":" in line else ""
        if   any(lower.startswith(k) for k in ["бренд","brand"]):           product["brand"]    = val
        elif any(lower.startswith(k) for k in ["розмір","size"]):           product["size"]     = val
        elif any(lower.startswith(k) for k in ["колір","color"]):           product["color"]    = val
        elif any(lower.startswith(k) for k in ["матеріал","material"]):     product["material"] = val
        elif any(lower.startswith(k) for k in ["категорія","category"]):    product["category"] = val
        elif any(lower.startswith(k) for k in ["стать","gender"]):          product["gender"]   = val
        elif any(lower.startswith(k) for k in ["постачальник","supplier"]): product["supplier"] = val
        elif "ціна" in lower or ("грн" in lower and re.search(r"\d+", line)):
            m = re.search(r"\d+", line.replace(" ",""))
            if m: product["price"] = m.group()
    for line in lines:
        line = line.strip()
        if line and ":" not in line and len(line) < 100:
            product["name"] = line; break
    return product

# ── Telegram публічний пост ───────────────────────────────
def fetch_telegram(url: str) -> dict:
    embed_url = url.rstrip("/") + "?embed=1&single=1"
    headers   = {"User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"}
    try:
        resp = requests.get(embed_url, headers=headers, timeout=12)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        return {"error": f"Не вдалось завантажити пост: {e}"}

    # Текст
    text_match = re.search(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
    raw_text = ""
    if text_match:
        raw_text = re.sub(r"<[^>]+>", "\n", text_match.group(1)).strip()
        raw_text = re.sub(r"\n{3,}", "\n\n", raw_text)

    # Фото URLs з HTML
    raw_photos = []
    raw_photos += re.findall(r"background-image:url\('(https://[^']+)'\)", html)
    raw_photos += re.findall(r'<img[^>]+src=[\'"]?(https://cdn[^\'">\s]+)[\'"]?', html)
    raw_photos  = list(dict.fromkeys(raw_photos))  # без дублів

    # Скачуємо фото локально
    print(f"📥 Скачую {len(raw_photos)} фото з Telegram...")
    local_photos = [p for p in (download_photo(u) for u in raw_photos[:10]) if p]

    product = parse_text(raw_text)
    product["photos"] = ", ".join(local_photos)
    product["source"] = "telegram"
    return product

# ── MyDrop ────────────────────────────────────────────────
def fetch_mydrop(url: str) -> dict:
    token = get_env("MYDROP_TOKEN")
    if not token:
        return {"error": "Не вказано MYDROP_TOKEN у файлі scripts/.env"}
    headers = {"X-API-KEY": token}
    try:
        resp = requests.get("https://backend.mydrop.com.ua/api/products", headers=headers, timeout=10)
        resp.raise_for_status()
        products = resp.json()
        sku_m = re.search(r"sku[=/]([^&/]+)", url)
        if sku_m:
            products = [p for p in products if p.get("sku") == sku_m.group(1)]
        if not products:
            return {"error": "Товар не знайдено в MyDrop"}
        p = products[0]
        sizes = p.get("sizes", [])

        # Скачуємо фото
        raw_photos = p.get("images", [])
        print(f"📥 Скачую {len(raw_photos)} фото з MyDrop...")
        local_photos = [lp for lp in (download_photo(u) for u in raw_photos[:10]) if lp]

        return {
            "sku":p.get("sku",""), "name":p.get("title",""), "brand":p.get("brand",""),
            "price":str(p.get("price","")), "size":", ".join(s["title"] for s in sizes if s.get("amount",0)>0),
            "color":p.get("color",""), "material":p.get("material",""), "gender":p.get("gender",""),
            "condition":"Нове", "photos":", ".join(local_photos), "description":p.get("description",""), "source":"mydrop",
        }
    except Exception as e:
        return {"error": str(e)}

# ── KeyCRM ────────────────────────────────────────────────
def fetch_keycrm(url: str) -> dict:
    key = get_env("KEYCRM_KEY")
    if not key:
        return {"error": "Не вказано KEYCRM_KEY у файлі scripts/.env"}
    pid = re.search(r"/(\d+)/?$", url)
    if not pid:
        return {"error": "Не вдалось визначити ID товару з посилання"}
    headers = {"Authorization": f"Bearer {key}"}
    try:
        resp = requests.get(f"https://openapi.keycrm.app/v1/products/{pid.group(1)}", headers=headers, timeout=10)
        resp.raise_for_status()
        p = resp.json()
        offers = p.get("offers", [])
        sizes  = [o.get("properties",{}).get("size","") for o in offers if o.get("quantity",0)>0]
        raw_photos = [a["url"] for a in p.get("attachments",[]) if a.get("url")]

        print(f"📥 Скачую {len(raw_photos)} фото з KeyCRM...")
        local_photos = [lp for lp in (download_photo(u) for u in raw_photos[:10]) if lp]

        return {
            "sku":p.get("sku",""), "name":p.get("name",""), "brand":p.get("brand",""),
            "price":str(p.get("price","")), "size":", ".join(filter(None,sizes)),
            "color":p.get("properties",{}).get("color",""), "material":"", "gender":"",
            "condition":"Нове", "photos":", ".join(local_photos), "description":p.get("description",""), "source":"keycrm",
        }
    except Exception as e:
        return {"error": str(e)}

# ── Маршрути ─────────────────────────────────────────────
@app.route("/photos/<filename>")
def serve_photo(filename):
    return send_from_directory(PHOTOS_DIR, filename)

@app.route("/fetch", methods=["POST"])
def fetch_product():
    url = (request.get_json() or {}).get("url","").strip()
    if not url: return jsonify({"error":"URL не вказано"}), 400
    if "t.me"    in url: result = fetch_telegram(url)
    elif "mydrop" in url: result = fetch_mydrop(url)
    elif "keycrm" in url: result = fetch_keycrm(url)
    else: return jsonify({"error":"Джерело не розпізнано. Підтримується: t.me, mydrop, keycrm"}), 400
    return jsonify(result)

@app.route("/parse-text", methods=["POST"])
def parse_text_route():
    text = (request.get_json() or {}).get("text","")
    if not text: return jsonify({"error":"Текст не вказано"}), 400
    return jsonify(parse_text(text))

@app.route("/download-photo", methods=["POST"])
def download_photo_route():
    url = (request.get_json() or {}).get("url","").strip()
    if not url: return jsonify({"error":"URL не вказано"}), 400
    local = download_photo(url)
    if local: return jsonify({"url": local})
    return jsonify({"error":"Не вдалось скачати фото"}), 400

@app.route("/settings", methods=["GET"])
def get_settings():
    channels_raw = get_env("TELEGRAM_CHANNELS","")
    channels = [c.strip() for c in channels_raw.split(",") if c.strip()]
    return jsonify({
        "telegram_mode":    get_env("TELEGRAM_MODE","public"),
        "telegram_channels": channels,
        "has_telegram_api": bool(get_env("TELEGRAM_API_ID")),
        "has_mydrop_token": bool(get_env("MYDROP_TOKEN")),
        "has_keycrm_key":   bool(get_env("KEYCRM_KEY")),
    })

@app.route("/settings", methods=["POST"])
def update_settings():
    data = request.get_json() or {}
    mapping = {
        "telegram_mode":    "TELEGRAM_MODE",
        "telegram_api_id":  "TELEGRAM_API_ID",
        "telegram_api_hash":"TELEGRAM_API_HASH",
        "telegram_channels":"TELEGRAM_CHANNELS",
        "mydrop_token":     "MYDROP_TOKEN",
        "keycrm_key":       "KEYCRM_KEY",
    }
    for key, env_key in mapping.items():
        if key in data:
            val = data[key]
            if isinstance(val, list): val = ",".join(val)
            set_env(env_key, str(val))
    load_dotenv(ENV_PATH, override=True)
    return jsonify({"ok": True})

@app.route("/health")
def health():
    return jsonify({"status":"ok"})

if __name__ == "__main__":
    print("🚀 Сервер запущено на http://localhost:5001")
    print(f"   Фото зберігаються в: {PHOTOS_DIR}")
    print("   Залиш це вікно відкритим поки працюєш з додатком.\n")
    app.run(host="127.0.0.1", port=5001, debug=False)

# ── Синхронізація джерел ──────────────────────────────────
import sys, os
sys.path.insert(0, str(Path(__file__).parent))

def sync_source(source: str) -> dict:
    """Отримує товари з джерела та зберігає у products.json"""
    public_dir = Path(__file__).parent.parent / "public"
    products_file = public_dir / "synced_products.json"

    existing = []
    if products_file.exists():
        try: existing = json.loads(products_file.read_text(encoding="utf-8"))
        except: existing = []

    # Завантажуємо published.json для дедублікації
    pub_file = Path(__file__).parent / "published.json"
    published = {}
    if pub_file.exists():
        try: published = json.loads(pub_file.read_text(encoding="utf-8"))
        except: pass

    new_products = []

    if source == "telegram":
        channels = [c.strip() for c in get_env("TELEGRAM_CHANNELS","").split(",") if c.strip()]
        for ch in channels:
            url = f"https://t.me/{ch.lstrip('@')}" if not ch.startswith("http") else ch
            # Беремо останні 20 постів каналу
            try:
                resp = requests.get(f"https://t.me/s/{ch.lstrip('@')}", headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
                post_urls = re.findall(r'href="(https://t\.me/[^"]+/\d+)"', resp.text)
                post_urls = list(dict.fromkeys(post_urls))[:20]
                for purl in post_urls:
                    p = fetch_telegram(purl)
                    if not p.get("error") and p.get("name"):
                        p["id"] = f"tg_{purl.split('/')[-1]}_{ch}"
                        p["supplier"] = ch
                        p["addedAt"] = p.get("addedAt", "")
                        new_products.append(p)
            except Exception as e:
                print(f"⚠️ {ch}: {e}")

    elif source == "mydrop":
        token = get_env("MYDROP_TOKEN")
        if not token: return {"error": "MYDROP_TOKEN не вказано"}
        try:
            resp = requests.get("https://backend.mydrop.com.ua/api/products", headers={"X-API-KEY":token}, timeout=15)
            resp.raise_for_status()
            for p in resp.json():
                sizes = p.get("sizes",[])
                raw_photos = p.get("images",[])
                local_photos = [lp for lp in (download_photo(u) for u in raw_photos[:5]) if lp]
                new_products.append({
                    "id": f"mydrop_{p.get('sku','')}",
                    "sku": p.get("sku",""), "name": p.get("title",""), "brand": p.get("brand",""),
                    "price": str(p.get("price","")), "size": ", ".join(s["title"] for s in sizes if s.get("amount",0)>0),
                    "color": p.get("color",""), "material": p.get("material",""), "gender": p.get("gender",""),
                    "condition": "Нове", "photos": ", ".join(local_photos), "description": p.get("description",""),
                    "source": "mydrop", "supplier": "MyDrop", "addedAt": "",
                })
        except Exception as e:
            return {"error": str(e)}

    elif source == "keycrm":
        key = get_env("KEYCRM_KEY")
        if not key: return {"error": "KEYCRM_KEY не вказано"}
        try:
            page, all_p = 1, []
            while True:
                resp = requests.get("https://openapi.keycrm.app/v1/products", headers={"Authorization":f"Bearer {key}"}, params={"page":page,"limit":50}, timeout=15)
                resp.raise_for_status()
                batch = resp.json().get("data",[])
                if not batch: break
                all_p.extend(batch); page += 1
            for p in all_p:
                offers = p.get("offers",[])
                sizes  = [o.get("properties",{}).get("size","") for o in offers if o.get("quantity",0)>0]
                raw_photos = [a["url"] for a in p.get("attachments",[]) if a.get("url")]
                local_photos = [lp for lp in (download_photo(u) for u in raw_photos[:5]) if lp]
                new_products.append({
                    "id": f"keycrm_{p.get('sku','')}",
                    "sku": p.get("sku",""), "name": p.get("name",""), "brand": p.get("brand",""),
                    "price": str(p.get("price","")), "size": ", ".join(filter(None,sizes)),
                    "color": p.get("properties",{}).get("color",""), "material": "", "gender": "",
                    "condition": "Нове", "photos": ", ".join(local_photos), "description": p.get("description",""),
                    "source": "keycrm", "supplier": "KeyCRM", "addedAt": "",
                })
        except Exception as e:
            return {"error": str(e)}

    # Фільтруємо нові (яких ще немає в existing та не опубліковані)
    existing_ids = {p.get("id") for p in existing}
    truly_new = [p for p in new_products if p.get("id") not in existing_ids]
    merged = existing + truly_new
    products_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"total": len(new_products), "new_count": len(truly_new), "skipped": len(new_products)-len(truly_new)}

@app.route("/sync/<source>", methods=["POST"])
def sync_route(source):
    if source not in ("telegram","mydrop","keycrm"):
        return jsonify({"error":"Невідоме джерело"}), 400
    result = sync_source(source)
    if "error" in result: return jsonify(result), 400
    return jsonify(result)
