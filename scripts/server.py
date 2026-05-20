"""
Локальний сервер для автозаповнення форми товару.

Запуск (один раз, залиш відкритим):
    python server.py

Сервер: http://localhost:5001
"""

import re, json, os, uuid, hashlib, requests
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from urllib.parse import unquote, urlparse

# Завантажуємо .env
ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)

import logging

def log(msg):
    from datetime import datetime
    print(f"\r[{datetime.now().strftime('%H:%M:%S')}] {msg}          ")

_spinner_active = [False]

def start_spinner(msg="📥 Завантаження фото"):
    import threading, itertools, time, sys
    _spinner_active[0] = True
    def spin():
        for ch in itertools.cycle(["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]):
            if not _spinner_active[0]:
                break
            elapsed = int(time.time() - _spinner_start[0])
            mins, secs = divmod(elapsed, 60)
            t = f"{mins}хв {secs}с" if mins else f"{secs}с"
            print(f"\r  {ch} {msg}... {t}   ", end="", flush=True)
            time.sleep(0.1)
    _spinner_start[0] = __import__("time").time()
    threading.Thread(target=spin, daemon=True).start()

_spinner_start = [0]
_photos_downloaded = [0]
import threading as _threading
_sync_lock = _threading.Lock()

def stop_spinner():
    _spinner_active[0] = False
    __import__("time").sleep(0.15)
    print("\r" + " " * 80 + "\r", end="", flush=True)

logging.getLogger("werkzeug").setLevel(logging.ERROR)

app        = Flask(__name__)
CORS(app)

logging.getLogger("werkzeug").addFilter(
    type("_", (logging.Filter,), {"filter": lambda self, r: "/health" not in r.getMessage()})()
)
PHOTOS_DIR = Path(__file__).parent / "photos"
PHOTOS_DIR.mkdir(exist_ok=True)

PUBLIC_DIR = Path(__file__).parent.parent / "public"
SYNCED_PRODUCTS_FILE = PUBLIC_DIR / "synced_products.json"
SYNC_PROGRESS_FILE = Path(__file__).parent / "sync_progress.json"

def normalize_channel_key(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r":(A|B|C|AUTO)$", "", value, flags=re.IGNORECASE)
    value = value.replace("https://t.me/", "").replace("http://t.me/", "")
    value = value.lstrip("@").strip("/")
    if "/" in value:
        value = value.split("/", 1)[0]
    return value.lower()

def product_matches_channel(product: dict, channel: str) -> bool:
    target = normalize_channel_key(channel)
    if not target:
        return False
    for field in ("supplier", "source_channel", "channel"):
        if normalize_channel_key(product.get(field, "")) == target:
            return True
    for field in ("source_url", "post_url", "media_post_url", "text_post_url"):
        raw = str(product.get(field, "") or "")
        urls = [u.strip() for u in raw.split(",") if u.strip()]
        if any(normalize_channel_key(u) == target for u in urls):
            return True
    return False

def photo_filename_from_url(url: str) -> str | None:
    path = unquote(urlparse(str(url or "").strip()).path)
    filename = Path(path).name
    if not filename or filename in (".", ".."):
        return None
    return filename

def product_photo_filenames(product: dict) -> set[str]:
    photos = product.get("photos", "")
    if isinstance(photos, list):
        items = photos
    else:
        items = str(photos or "").split(",")
    return {
        name for name in (photo_filename_from_url(item) for item in items)
        if name
    }

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
def download_photo(url: str, _counter: list = None) -> str | None:
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

        filename = f"{hashlib.md5(url.encode()).hexdigest()}{ext}"
        filepath = PHOTOS_DIR / filename
        if filepath.exists():
            if _counter is not None:
                _counter[0] += 1
            return f"http://localhost:5001/photos/{filename}"
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        _photos_downloaded[0] += 1

        if _counter is not None:
            _counter[0] += 1
        return f"http://localhost:5001/photos/{filename}"
    except Exception as e:
        log(f"⚠️ Не вдалось скачати фото {url}: {e}")
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
    embed_url = url.rstrip("/") + "?embed=1"
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

    # Фото URLs з HTML (тільки фото товару, без аватарок)
    raw_photos = []
    # Фото товару — тільки з photo_wrap блоків
    raw_photos += re.findall(r'tgme_widget_message_photo_wrap[^>]*style="[^"]*background-image:url\(\'(https://[^\']+)\'\)', html)
    raw_photos = list(dict.fromkeys(raw_photos))

    # Скачуємо фото локально
    local_photos = [p for p in (download_photo(u) for u in raw_photos[:10]) if p]

    product = parse_text(raw_text)
    product["photos"] = ", ".join(local_photos)
    product["source"] = "telegram"
    # Витягуємо дату публікації
    date_match = re.search(r'datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})', html)
    if date_match:
        dt = datetime.strptime(date_match.group(1), "%Y-%m-%dT%H:%M:%S")
        product["post_date"] = dt.strftime("%d.%m.%Y")
        product["post_datetime"] = dt.isoformat()
    else:
        product["post_date"] = ""
        product["post_datetime"] = ""
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

@app.route("/last-sync")
def last_sync():
    sync_file = Path(__file__).parent.parent / "public" / "last_sync.json"
    if not sync_file.exists():
        return jsonify({"synced_at": None})
    try: return jsonify(json.loads(sync_file.read_text(encoding="utf-8")))
    except: return jsonify({"synced_at": None})

@app.route("/synced-products")
def get_synced_products():
    products_file = SYNCED_PRODUCTS_FILE
    if not products_file.exists():
        return jsonify([])
    try:
        return jsonify(json.loads(products_file.read_text(encoding="utf-8")))
    except:
        return jsonify([])

# ── Синхронізація джерел ──────────────────────────────────
@app.route("/channels/reset", methods=["POST"])
def reset_channel_data():
    data = request.get_json() or {}
    channel = str(data.get("channel", "") or "").strip()
    target = normalize_channel_key(channel)
    if not target:
        return jsonify({"error": "channel is required"}), 400

    with _sync_lock:
        products = []
        if SYNCED_PRODUCTS_FILE.exists():
            try:
                products = json.loads(SYNCED_PRODUCTS_FILE.read_text(encoding="utf-8"))
            except:
                products = []

        removed = [p for p in products if product_matches_channel(p, channel)]
        kept = [p for p in products if not product_matches_channel(p, channel)]

        removed_photo_names = set()
        for product in removed:
            removed_photo_names.update(product_photo_filenames(product))

        kept_photo_names = set()
        for product in kept:
            kept_photo_names.update(product_photo_filenames(product))

        deleted_photos = 0
        for filename in sorted(removed_photo_names - kept_photo_names):
            photo_path = (PHOTOS_DIR / filename).resolve()
            try:
                if PHOTOS_DIR.resolve() in photo_path.parents and photo_path.exists():
                    photo_path.unlink()
                    deleted_photos += 1
            except:
                pass

        SYNCED_PRODUCTS_FILE.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        progress_removed = False
        if SYNC_PROGRESS_FILE.exists():
            try:
                progress = json.loads(SYNC_PROGRESS_FILE.read_text(encoding="utf-8"))
            except:
                progress = {}
            if isinstance(progress, dict):
                next_progress = {
                    key: val for key, val in progress.items()
                    if normalize_channel_key(key) != target
                }
                progress_removed = len(next_progress) != len(progress)
                SYNC_PROGRESS_FILE.write_text(
                    json.dumps(next_progress, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )

    return jsonify({
        "ok": True,
        "channel": channel,
        "removed_products": len(removed),
        "deleted_photos": deleted_photos,
        "progress_removed": progress_removed,
    })

import sys, os
sys.path.insert(0, str(Path(__file__).parent))

def merge_pattern_products(products: list) -> list:
    groups = {}
    used = set()
    replacements = {}

    def post_num(p):
        m = re.match(r"^tg_(\d+)_", p.get("id", ""))
        return int(m.group(1)) if m else None

    def has_photos(p):
        return bool((p.get("photos") or "").strip())

    def has_text(p):
        return bool((p.get("description") or "").strip())

    def pattern_of(p):
        supplier = str(p.get("supplier", "")).strip()
        m = re.search(r":(A|B|C|AUTO)$", supplier, flags=re.IGNORECASE)
        return m.group(1).upper() if m else "AUTO"

    def supplier_key(p):
        return re.sub(r":(A|B|C|AUTO)$", "", str(p.get("supplier", "")).strip(), flags=re.IGNORECASE)

    def merge_text_with_media(text, media_items):
        merged = dict(text)
        nums = [post_num(text)] + [post_num(m) for m in media_items]
        nums = [n for n in nums if n is not None]
        if nums:
            merged["id"] = f"tg_{min(nums)}_{max(nums)}_{text.get('supplier')}"
        photos = [p.strip() for p in (text.get("photos") or "").split(",") if p.strip()]
        media_urls = []
        for media in sorted(media_items, key=lambda p: post_num(p) or 0, reverse=True):
            photos.extend([p.strip() for p in (media.get("photos") or "").split(",") if p.strip()])
            media_url = media.get("post_url") or media.get("source_url", "")
            if media_url:
                media_urls.append(media_url)
        merged["photos"] = ", ".join(dict.fromkeys(photos))
        merged["media_post_url"] = ", ".join(media_urls)
        merged["text_post_url"] = text.get("post_url") or text.get("source_url", "")
        merged["source_url"] = text.get("source_url") or text.get("post_url", "")
        merged["post_url"] = text.get("post_url") or text.get("source_url", "")
        return merged

    for idx, p in enumerate(products):
        n = post_num(p)
        if n is not None:
            groups.setdefault((supplier_key(p), pattern_of(p)), []).append((idx, n, p))

    def collect_media(ordered, start_pos, step):
        media_items = []
        media_indices = []
        pos = start_pos + step
        while 0 <= pos < len(ordered):
            item_idx, _item_n, item = ordered[pos]
            if item_idx in used or has_text(item):
                break
            if has_photos(item):
                media_items.append(item)
                media_indices.append(item_idx)
            pos += step
        return media_items, media_indices

    def nearest_gap(text_num, media_items):
        nums = [post_num(item) for item in media_items]
        nums = [num for num in nums if num is not None]
        return min((abs(text_num - num) for num in nums), default=10**9)

    for (_supplier, pattern), items in groups.items():
        if pattern == "C":
            continue
        ordered = sorted(items, key=lambda item: item[1], reverse=True)
        for pos, (idx, _n, p) in enumerate(ordered):
            if idx in used or not has_text(p):
                continue
            media_items, media_indices = [], []

            if pattern == "A":
                media_items, media_indices = collect_media(ordered, pos, 1)
            elif pattern == "B":
                media_items, media_indices = collect_media(ordered, pos, -1)
            elif pattern == "AUTO":
                a_items, a_indices = collect_media(ordered, pos, 1)
                b_items, b_indices = collect_media(ordered, pos, -1)
                if a_items and b_items:
                    if nearest_gap(_n, b_items) < nearest_gap(_n, a_items):
                        media_items, media_indices = b_items, b_indices
                    else:
                        media_items, media_indices = a_items, a_indices
                elif a_items:
                    media_items, media_indices = a_items, a_indices
                elif b_items:
                    media_items, media_indices = b_items, b_indices

            if media_items:
                replacements[idx] = merge_text_with_media(p, media_items)
                used.update(media_indices)

    result = []
    for idx, p in enumerate(products):
        if idx in replacements:
            result.append(replacements[idx])
        elif idx not in used:
            result.append(p)
    return result

def merge_pattern_a_products(products: list) -> list:
    return merge_pattern_products(products)

def sync_source(source: str, disabled_channels: list = None) -> dict:
    # Завжди читаємо актуальний список вимкнених каналів з файлу
    disabled_file = Path(__file__).parent.parent / "public" / "disabled_channels.json"
    if disabled_file.exists():
        try: disabled_channels = json.loads(disabled_file.read_text(encoding="utf-8"))
        except: disabled_channels = []
    else:
        disabled_channels = []
    """Отримує товари з джерела та зберігає у products.json"""
    _sync_start = datetime.now()
    _photo_count = [0]
    _photos_downloaded[0] = 0
    # ВИПРАВЛЕНО: два окремі рядки замість злитого оголошення
    _private_skipped = []
    _disabled_skipped = []
    log(f"📥 Починаю синхронізацію...")
    public_dir = Path(__file__).parent.parent / "public"
    products_file = public_dir / "synced_products.json"

    existing = []
    if products_file.exists():
        try: existing = json.loads(products_file.read_text(encoding="utf-8"))
        except: existing = []

    # Завантажуємо прогрес синку
    progress_file = Path(__file__).parent / "sync_progress.json"
    sync_progress = {}
    if progress_file.exists():
        try: sync_progress = json.loads(progress_file.read_text(encoding="utf-8"))
        except: sync_progress = {}

    # Завантажуємо published.json для дедублікації
    pub_file = Path(__file__).parent / "published.json"
    published = {}
    if pub_file.exists():
        try: published = json.loads(pub_file.read_text(encoding="utf-8"))
        except: pass

    new_products = []

    channel_results = {}
    if source == "telegram":
        channels = [c.strip() for c in get_env("TELEGRAM_CHANNELS","").split(",") if c.strip()]
        for ch in channels:
            ch_url = f"https://t.me/{ch.lstrip('@')}" if not ch.startswith("http") else ch
            # ВИПРАВЛЕНО: прибрано дублюючий if, правильний відступ блоку
            def _strip(c): return re.sub(r':([ABCabc]|AUTO)$', '', c.strip(), flags=re.IGNORECASE)
            def _norm(c):
                c = re.sub(r':([ABCabc]|AUTO)$', '', c.strip(), flags=re.IGNORECASE)
                c = c.replace("https://t.me/", "").replace("http://t.me/", "")
                return c.lstrip("@").lower().strip("/")
            is_private_link = "joinchat" in ch or "/+" in ch
            is_plain_text = not ch.startswith("http") and not ch.startswith("@") and not re.match(r'^[a-zA-Z0-9_]{5,}$', ch)
            if is_private_link or is_plain_text:
                pending_file = Path(__file__).parent / "pending_private_channels.json"
                pending = []
                if pending_file.exists():
                    try: pending = json.loads(pending_file.read_text(encoding="utf-8"))
                    except: pending = []
                if ch not in pending:
                    pending.append(ch)
                    pending_file.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
                _private_skipped.append(ch)
                continue
            if _norm(ch) in [_norm(d) for d in disabled_channels] or _norm(ch_url) in [_norm(d) for d in disabled_channels]:
                _disabled_skipped.append(ch)
                continue
            url = f"https://t.me/{ch.lstrip('@')}" if not ch.startswith("http") else ch
            # Беремо останні 20 постів каналу
            try:
                if False:
                    pass
                if False:
                    # Зберігаємо в pending_private_channels.json
                    pending_file = Path(__file__).parent / "pending_private_channels.json"
                    pending = []
                    if pending_file.exists():
                        try: pending = json.loads(pending_file.read_text(encoding="utf-8"))
                        except: pending = []
                    if ch not in pending:
                        pending.append(ch)
                        pending_file.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8")
                    _private_skipped.append(ch)
                    continue
                # Витягуємо username з повного URL якщо потрібно
                def _strip_pat(c): return re.sub(r':([ABCabc]|AUTO)$', '', c.strip(), flags=re.IGNORECASE)
                def _pattern(c):
                    m = re.search(r':([ABCabc]|AUTO)$', c.strip(), flags=re.IGNORECASE)
                    return m.group(1).upper() if m else "AUTO"
                if ch.startswith("https://t.me/"):
                    ch_name = _strip_pat(ch.replace("https://t.me/", "").strip("/"))
                else:
                    ch_name = _strip_pat(ch.lstrip("@"))
                ch_pattern = _pattern(ch)
                all_post_urls = []
                ch_title = ch_name
                try:
                
                    _title_resp = requests.get(f"https://t.me/s/{ch_name}", headers={"User-Agent":"Mozilla/5.0 (compatible; Googlebot/2.1)"}, timeout=10)
                    _title_match = re.search(r'<div class="tgme_channel_info_header_title"[^>]*>(.*?)</div>', _title_resp.text)
                    if _title_match:
                        ch_title = re.sub(r"<[^>]+>", "", _title_match.group(1)).strip()
                except:
                    pass
                page_url = f"https://t.me/s/{ch_name}"
                _link_count = [0]
                _collecting = [True]
                def _spin_links():
                    import itertools, time
                    for sp in itertools.cycle(["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]):
                        if not _collecting[0]: break
                        _elapsed = int((datetime.now() - _sync_start).total_seconds())
                        _mins, _secs = divmod(_elapsed, 60)
                        _t = f"{_mins}хв {_secs}с" if _mins else f"{_secs}с"
                        print(f"\r  {sp} 🔗 Канал @{ch_name}: збираю посилання: {_link_count[0]} | ⏱ {_t}          ", end="", flush=True)
                        time.sleep(0.1)
                existing_post_ids = {p.get("id") for p in existing}
                last_synced_id = sync_progress.get(_norm(ch), {}).get("last_id") or sync_progress.get(ch, {}).get("last_id")
                import threading
                threading.Thread(target=_spin_links, daemon=True).start()
                while page_url:
                    import time; time.sleep(1)
                    resp = requests.get(page_url, headers={"User-Agent":"Mozilla/5.0 (compatible; Googlebot/2.1)"}, timeout=10)
                    found = re.findall(r'href="(https://t\.me/[^"]+/\d+)"', resp.text)
                    all_post_urls.extend(found)
                    _link_count[0] = len(all_post_urls)
                    # Зупиняємось якщо на сторінці є пост який вже є в базі
                    page_has_known = any(
                        f"tg_{u.split('/')[-1]}_{ch}" in existing_post_ids
                        for u in found
                    )
                    page_has_last = last_synced_id and any(
                        u.split('/')[-1] == last_synced_id
                        for u in found
                    )
                    if page_has_known and not last_synced_id:
                        break
                    if page_has_last:
                        break
                    # Зупиняємось якщо сторінка містить пости старші за DATE_FROM
                    from datetime import timedelta
                    date_limit = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                    dates_on_page = re.findall(r'datetime="(\d{4}-\d{2}-\d{2})', resp.text)
                    should_stop = dates_on_page and min(dates_on_page) < date_limit
                    prev_match = re.search(r'href="/s/' + ch_name + r'\?before=(\d+)"', resp.text)
                    if should_stop or not prev_match:
                        break
                    page_url = f"https://t.me/s/{ch_name}?before={prev_match.group(1)}"
                _collecting[0] = False
                import time; time.sleep(0.15)
                print("\r" + " " * 80 + "\r", end="", flush=True)
                # Зупиняємось на першому пості який вже є в базі
                post_urls = []
                for u in dict.fromkeys(all_post_urls):
                    pid = u.split('/')[-1]
                    if pid == last_synced_id:
                        break
                    if f"tg_{pid}_{ch}" in existing_post_ids and not last_synced_id:
                        break
                    post_urls.append(u)
                ch_count = 0
                from datetime import timedelta
                DATE_FROM = (datetime.now(timezone.utc) - timedelta(days=30))
                # Групуємо пости по альбому (grouped_id)
                seen_ids = set()
                stop_parsing = False
                total_posts = len(post_urls)
                _post_idx_ref = [0]
                _processing = [True]
                def _spin_posts():
                    import itertools, time
                    for sp in itertools.cycle(["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]):
                        if not _processing[0]: break
                        _elapsed = int((datetime.now() - _sync_start).total_seconds())
                        _mins, _secs = divmod(_elapsed, 60)
                        _t = f"{_mins}хв {_secs}с" if _mins else f"{_secs}с"
                        print(f"\r  {sp} 📄 Канал @{ch_name}: пост {_post_idx_ref[0]}/{total_posts} | 📥 фото: {_photos_downloaded[0]} | ⏱ {_t}          ", end="", flush=True)
                        time.sleep(0.1)
                threading.Thread(target=_spin_posts, daemon=True).start()
                if ch_pattern == "A":
                    post_urls = sorted(dict.fromkeys(post_urls), key=lambda u: int(u.split("/")[-1]))

                fetched_posts = {}
                def _get_post(purl):
                    if purl not in fetched_posts:
                        fetched_posts[purl] = fetch_telegram(purl)
                    return fetched_posts[purl]

                def _has_photos(p):
                    return bool((p.get("photos") or "").strip())

                def _has_text(p):
                    return bool((p.get("description") or "").strip())

                def _merge_media_text(media, media_url, text, text_url):
                    merged = dict(text)
                    merged["photos"] = media.get("photos", "")
                    merged["media_post_url"] = media_url
                    merged["text_post_url"] = text_url
                    return merged

                post_idx = 0
                while post_idx < len(post_urls):
                    purl = post_urls[post_idx]
                    _post_idx_ref[0] = post_idx + 1
                    if stop_parsing:
                        break
                    post_id = purl.split('/')[-1]
                    if post_id in seen_ids:
                        post_idx += 1
                        continue
                    p = _get_post(purl)
                    product_id = post_id
                    progress_id = post_id
                    product_url = purl

                    if False and ch_pattern == "A" and post_idx + 1 < len(post_urls):
                        next_url = post_urls[post_idx + 1]
                        next_id = next_url.split('/')[-1]
                        next_p = _get_post(next_url)
                        current_is_media = _has_photos(p) and not _has_text(p)
                        next_is_text = _has_text(next_p)
                        current_is_text = _has_text(p)
                        next_is_media = _has_photos(next_p) and not _has_text(next_p)
                        are_neighbors = int(next_id) == int(post_id) + 1
                        if current_is_media and next_is_text and are_neighbors:
                            p = _merge_media_text(p, purl, next_p, next_url)
                            product_id = f"{post_id}_{next_id}"
                            progress_id = next_id
                            product_url = next_url
                            seen_ids.add(next_id)
                            post_idx += 1
                        elif current_is_text and next_is_media and are_neighbors:
                            p = _merge_media_text(next_p, next_url, p, purl)
                            product_id = f"{post_id}_{next_id}"
                            progress_id = next_id
                            product_url = purl
                            seen_ids.add(next_id)
                            post_idx += 1

                    if p.get('error'):
                        print(f"\r{' ' * 80}\r", end="", flush=True)
                        log(f"  ⚠️ {purl}: {p.get('error','')[:80]}")
                    # Зупиняємось якщо пост старший за DATE_FROM
                    if p.get("post_date"):
                        try:
                            post_dt = datetime.strptime(p["post_date"], "%d.%m.%Y").replace(tzinfo=timezone.utc)
                            if post_dt < DATE_FROM:
                                post_idx += 1
                                continue
                        except:
                            pass
                    if not p.get("error"):
                        if not p.get("name") and p.get("description"):
                            first_line = p["description"].split("\n")[0].strip()
                            p["name"] = first_line[:80] if first_line else "Без назви"
                        if not p.get("name"):
                            p["name"] = "Без назви"
                        p["id"] = f"tg_{product_id}_{ch}"
                        p["supplier"] = ch
                        p["supplier_title"] = ch_title
                        p["source_url"] = product_url
                        p["post_url"] = product_url
                        p["addedAt"] = datetime.now(timezone.utc).isoformat()
                        new_products.append(p)
                        ch_count += 1
                        seen_ids.add(post_id)
                        # Зберігаємо прогрес
                        sync_progress[_norm(ch)] = {"last_id": progress_id}
                        progress_file.write_text(json.dumps(sync_progress, ensure_ascii=False), encoding="utf-8")
                    post_idx += 1
                _processing[0] = False
                import time; time.sleep(0.15)
                print("\r" + " " * 80 + "\r", end="", flush=True)
                channel_results[_strip_pat(ch)] = {"status": "ok", "count": ch_count, "links": len(all_post_urls)}
            except Exception as e:
                err_map = {
                    "cannot access local variable": "внутрішня помилка змінної",
                    "Connection": "помилка з'єднання",
                    "Timeout": "перевищено час очікування",
                    "404": "канал не знайдено",
                    "403": "доступ заборонено",
                }
                err_str = str(e)
                ua_msg = next((v for k, v in err_map.items() if k in err_str), err_str)
                log(f"⚠️ {ch}: {ua_msg}")
                channel_results[ch] = {"status": "error", "message": ua_msg}
                channel_results[_strip_pat(ch)] = {"status": "error", "message": ua_msg}

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

    if source == "telegram":
        existing = merge_pattern_a_products(existing)
        new_products = merge_pattern_a_products(new_products)

    # Фільтруємо нові (яких ще немає в existing та не опубліковані)
    existing_ids = {p.get("id") for p in existing}
    truly_new = [p for p in new_products if p.get("id") not in existing_ids]
    merged = existing + truly_new
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    def get_post_dt(p):
        pd = p.get("post_date","")
        if pd:
            try: return datetime.strptime(pd, "%d.%m.%Y").replace(tzinfo=timezone.utc)
            except: pass
        ad = p.get("addedAt","")
        if ad:
            try: return datetime.fromisoformat(ad)
            except: pass
        return datetime.now(timezone.utc)
    merged = [p for p in merged if get_post_dt(p) >= cutoff]
    products_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    sync_file = public_dir / "last_sync.json"
    sync_file.write_text(json.dumps({"synced_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False), encoding="utf-8")

    stop_spinner()
    elapsed = (datetime.now() - _sync_start).seconds
    mins, secs = divmod(elapsed, 60)
    time_str = f"{mins} хв {secs} сек" if mins else f"{secs} сек"

    # ВИПРАВЛЕНО: правильний відступ для цих рядків (на рівні функції)
    disabled_info = f" | ⏩ вимкнених: {len(_disabled_skipped)}" if _disabled_skipped else ""
    private_info  = f" | ⚠️ приватних: {len(_private_skipped)}" if _private_skipped else ""

    return {"total": len(new_products), "new_count": len(truly_new), "skipped": len(new_products)-len(truly_new), "channel_results": channel_results if source == "telegram" else {}, "disabled_info": disabled_info, "private_info": private_info, "disabled_count": len(_disabled_skipped), "active_count": len(channel_results), "private_count": len(_private_skipped)}

@app.route("/disabled-channels", methods=["POST"])
def save_disabled_channels():
    data = request.get_json() or {}
    disabled = data.get("disabled_channels", [])
    disabled_file = Path(__file__).parent.parent / "public" / "disabled_channels.json"
    disabled_file.write_text(json.dumps(disabled, ensure_ascii=False), encoding="utf-8")
    return jsonify({"ok": True})

@app.route("/pending-private-channels", methods=["GET"])
def get_pending_private():
    pending_file = Path(__file__).parent / "pending_private_channels.json"
    if not pending_file.exists():
        return jsonify([])
    try: return jsonify(json.loads(pending_file.read_text(encoding="utf-8")))
    except: return jsonify([])

@app.route("/pending-private-channels/clear", methods=["POST"])
def clear_pending_private():
    pending_file = Path(__file__).parent / "pending_private_channels.json"
    pending_file.write_text("[]", encoding="utf-8")
    return jsonify({"ok": True})

@app.route("/sync/<source>", methods=["POST"])
def sync_route(source):
    if source not in ("telegram","mydrop","keycrm"):
        return jsonify({"error":"Невідоме джерело"}), 400
    data = request.get_json() or {}
    disabled_channels = data.get("disabled_channels", [])
    # Зберігаємо вимкнені канали щоб автосинк теж їх пропускав
    disabled_file = Path(__file__).parent.parent / "public" / "disabled_channels.json"
    disabled_file.write_text(json.dumps(disabled_channels, ensure_ascii=False), encoding="utf-8")
    with _sync_lock:
        result = sync_source(source, disabled_channels=disabled_channels)
    if "error" in result: return jsonify(result), 400
    extra = (result.get('disabled_info','') + result.get('private_info','')).strip(' |')
    suffix = f" | {extra}" if extra else ""
    total_links = sum(v.get('links',0) for v in result.get('channel_results',{}).values())
    print(f"\r{' ' * 80}\r", end="", flush=True)
    log(f"✅ Синк: нових {result.get('new_count',0)} | дублів {result.get('skipped',0)} | вимкнених: {result.get('disabled_count',0)} | 📥 фото: {_photos_downloaded[0]} | 🔗 посилань: {total_links} | ✅ активних: {result.get('active_count',0)} | ❌ вимкнених: {result.get('disabled_count',0)} | ⏳ Очікує API: {result.get('private_count',0)}")
    return jsonify(result)

logging.getLogger("werkzeug").setLevel(logging.ERROR)

if __name__ == "__main__":
    print("")  # порожній рядок перед логами Flask
    log("🚀 Сервер запущено на http://localhost:5001")
    log(f"📁 Фото зберігаються в: {PHOTOS_DIR}")
    log("💡 Залиш це вікно відкритим поки працюєш з додатком.")
    log("✅ Сервер активний. Для зупинки натисни CTRL+C")
    import threading

    def auto_sync_loop():
        import time
        INTERVAL = 30 * 60  # 30 хвилин
        log("🤖 Автосинк запущено — кожні 30 хвилин\n")
        time.sleep(20)
        first_run = True
        while True:
            if not first_run:
                # Перевіряємо час останнього синку
                sync_file = Path(__file__).parent.parent / "public" / "last_sync.json"
                if sync_file.exists():
                    try:
                        last = json.loads(sync_file.read_text(encoding="utf-8")).get("synced_at","")
                        if last:
                            diff = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
                            if diff < INTERVAL:
                                time.sleep(INTERVAL - diff)
                                continue
                    except: pass
            first_run = False
            log("🔄 Автосинк: синхронізую Telegram...")
            try:
                disabled = []
                disabled_file = Path(__file__).parent.parent / "public" / "disabled_channels.json"
                if disabled_file.exists():
                    try: disabled = json.loads(disabled_file.read_text(encoding="utf-8"))
                    except: disabled = []
                with _sync_lock:
                    result = sync_source("telegram", disabled_channels=disabled)
                extra = (result.get('disabled_info','') + result.get('private_info','')).strip(' |')
                suffix = f" | {extra}" if extra else ""
                total_links = sum(v.get('links',0) for v in result.get('channel_results',{}).values())
                log(f"✅ Автосинк: нових {result.get('new_count',0)} | дублів {result.get('skipped',0)} | вимкнених: {result.get('disabled_count',0)} | 📥 фото: {_photos_downloaded[0]} | 🔗 посилань: {total_links} | ✅ активних: {result.get('active_count',0)} | ❌ вимкнених: {result.get('disabled_count',0)} | ⏳ Очікує API: {result.get('private_count',0)}")
            except Exception as e:
                log(f"❌ Автосинк помилка: {e}")
            time.sleep(INTERVAL)

    threading.Thread(target=auto_sync_loop, daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False)
