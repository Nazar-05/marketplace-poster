"""
Локальний сервер для автозаповнення форми товару.

Запуск (один раз, залиш відкритим):
    python server.py

Сервер: http://localhost:5001
"""

import asyncio, re, json, os, uuid, hashlib, subprocess, requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from urllib.parse import unquote, urlparse

# Імпорт модуля групування варіацій товарів
try:
    from product_grouper import process_products
except ImportError:
    # Якщо модуль не знайдено, створюємо заглушку
    def process_products(products):
        return products

# Завантажуємо .env
ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(ENV_PATH)

import logging

_console_lock = __import__("threading").RLock()

def log(msg):
    from datetime import datetime
    with _console_lock:
        print(f"\r[{datetime.now().strftime('%H:%M:%S')}] {msg}          ", flush=True)

def progress_print(msg):
    with _console_lock:
        print(f"\r{msg}", end="", flush=True)

def clear_progress_line(width=120):
    with _console_lock:
        print("\r" + " " * width + "\r", end="", flush=True)


def curl_get_text(url: str, timeout_seconds: int = 20) -> str:
    result = subprocess.run(
        [
            "curl.exe",
            "--fail",
            "--location",
            "--silent",
            "--show-error",
            "--connect-timeout", "8",
            "--max-time", str(timeout_seconds),
            "--retry", "0",
            "--user-agent", "Mozilla/5.0 (compatible; Googlebot/2.1)",
            url,
        ],
        check=True,
        timeout=timeout_seconds + 5,
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace")


def telegram_message_html_to_text(message_html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", message_html, flags=re.IGNORECASE)
    text = re.sub(r"</(?:div|p)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_telegram_text_html(html: str) -> str:
    start = html.find('class="tgme_widget_message_text')
    if start < 0:
        return ""
    start = html.find(">", start)
    if start < 0:
        return ""
    start += 1
    # Telegram embed HTML can be oddly large; keep parsing bounded to avoid regex stalls.
    chunk = html[start:start + 50000]
    end_candidates = [
        pos for pos in (
            chunk.find('<div class="tgme_widget_message_footer'),
            chunk.find('<time'),
            chunk.find('</div>'),
        )
        if pos >= 0
    ]
    end = min(end_candidates) if end_candidates else len(chunk)
    return chunk[:end]


def extract_telegram_photo_urls(html: str) -> list[str]:
    urls = []
    marker = "tgme_widget_message_photo_wrap"
    for part in html.split(marker)[1:20]:
        needle = "background-image:url('"
        start = part.find(needle)
        if start < 0:
            continue
        start += len(needle)
        end = part.find("'", start)
        if end < 0:
            continue
        photo_url = part[start:end]
        if photo_url.startswith("https://") and photo_url not in urls:
            urls.append(photo_url)
    return urls


def strip_line_marker(line: str) -> str:
    return re.sub(r"^[\s\-–—➖✔️✅☑️•·]+", "", line).strip()


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
            progress_print(f"  {ch} {msg}... {t}   ")
            time.sleep(0.1)
    _spinner_start[0] = __import__("time").time()
    threading.Thread(target=spin, daemon=True).start()

_spinner_start = [0]
_photos_downloaded = [0]
import threading as _threading
_sync_lock = _threading.Lock()
_last_sync_finished_at = [datetime.now(timezone.utc) - timedelta(minutes=30)]

def _read_last_sync_time():
    sync_file = Path(__file__).parent.parent / "public" / "last_sync.json"
    if not sync_file.exists():
        return None
    try:
        value = json.loads(sync_file.read_text(encoding="utf-8")).get("synced_at", "")
        if not value:
            return None
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def _mark_sync_finished():
    _last_sync_finished_at[0] = datetime.now(timezone.utc)

def _autosync_anchor_time(include_saved=True):
    saved = _read_last_sync_time() if include_saved else None
    current = _last_sync_finished_at[0]
    if saved and saved > current:
        return saved
    return current

def stop_spinner():
    _spinner_active[0] = False
    __import__("time").sleep(0.15)
    clear_progress_line()

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

def product_post_numbers(product: dict) -> list[int]:
    numbers = []
    for field in ("source_url", "post_url", "media_post_url", "text_post_url"):
        raw = str(product.get(field, "") or "")
        numbers.extend(int(n) for n in re.findall(r"/(\d+)(?:\D|$)", raw))
    product_id = str(product.get("id", "") or "")
    m = re.match(r"^tg_([0-9_]+)_", product_id)
    if m:
        numbers.extend(int(n) for n in m.group(1).split("_") if n.isdigit())
    return numbers

def product_max_post_id(product: dict) -> int | None:
    numbers = product_post_numbers(product)
    return max(numbers) if numbers else None

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
def photo_dedupe_key(url: str) -> str:
    filename = photo_filename_from_url(url)
    if filename:
        photo_path = PHOTOS_DIR / filename
        try:
            if photo_path.exists() and photo_path.is_file():
                return hashlib.md5(photo_path.read_bytes()).hexdigest()
        except OSError:
            pass
    return str(url or "").strip()

def dedupe_photo_urls(photos: list[str]) -> list[str]:
    result = []
    seen = set()
    for photo in photos:
        photo = str(photo or "").strip()
        if not photo:
            continue
        key = photo_dedupe_key(photo)
        if key in seen:
            continue
        seen.add(key)
        result.append(photo)
    return result

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
    filepath = None
    tmp_path = None
    headers_path = None
    try:
        stem = hashlib.md5(url.encode()).hexdigest()
        for ext in (".jpg", ".png", ".webp", ".gif"):
            existing_path = PHOTOS_DIR / f"{stem}{ext}"
            if existing_path.exists():
                if existing_path.stat().st_size <= 0:
                    existing_path.unlink()
                else:
                    if _counter is not None:
                        _counter[0] += 1
                    return f"http://localhost:5001/photos/{existing_path.name}"

        tmp_path = PHOTOS_DIR / f"{stem}.download"
        headers_path = PHOTOS_DIR / f"{stem}.headers"
        tmp_path.unlink(missing_ok=True)
        headers_path.unlink(missing_ok=True)

        subprocess.run(
            [
                "curl.exe",
                "--fail",
                "--location",
                "--silent",
                "--show-error",
                "--connect-timeout", "8",
                "--max-time", "25",
                "--retry", "0",
                "--user-agent", "Mozilla/5.0",
                "--dump-header", str(headers_path),
                "--output", str(tmp_path),
                url,
            ],
            check=True,
            timeout=30,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        ct = headers_path.read_text(encoding="utf-8", errors="ignore").lower() if headers_path.exists() else ""
        ext = ".jpg"
        if "image/png" in ct:
            ext = ".png"
        elif "image/webp" in ct:
            ext = ".webp"
        elif "image/gif" in ct:
            ext = ".gif"

        filename = f"{stem}{ext}"
        filepath = PHOTOS_DIR / filename

        if tmp_path.stat().st_size <= 0:
            tmp_path.unlink(missing_ok=True)
            return None

        tmp_path.replace(filepath)

        if filepath.stat().st_size <= 0:
            filepath.unlink(missing_ok=True)
            return None

        _photos_downloaded[0] += 1

        if _counter is not None:
            _counter[0] += 1
        return f"http://localhost:5001/photos/{filename}"
    except (requests.exceptions.Timeout, subprocess.TimeoutExpired):
        log(f"⚠️ Timeout фото, пропущено: {url[:80]}")
        if filepath is not None:
            try:
                filepath.unlink(missing_ok=True)
            except OSError:
                pass
        return None
    except Exception as e:
        if filepath is not None:
            try:
                filepath.unlink(missing_ok=True)
            except OSError:
                pass
        return None
    finally:
        for cleanup_path in (tmp_path, headers_path):
            if cleanup_path is not None:
                try:
                    cleanup_path.unlink(missing_ok=True)
                except OSError:
                    pass

# ── Парсинг тексту товару ─────────────────────────────────
def parse_text(text: str) -> dict:
    lines = text.split("\n")
    product = { "name":"","brand":"","price":"","size":"","color":"","material":"","gender":"","condition":"Нове","category":"","supplier":"","description":text,"photos":"" }
    for line in lines:
        line = strip_line_marker(line.strip())
        if not line: continue
        lower = line.lower()
        val = line.split(":",1)[-1].strip() if ":" in line else ""
        if   any(lower.startswith(k) for k in ["бренд","brand"]):           product["brand"]    = val
        elif any(lower.startswith(k) for k in ["розмір","size"]):           product["size"]     = val
        elif any(lower.startswith(k) for k in ["колір","color"]):           product["color"]    = val
        elif any(lower.startswith(k) for k in ["матеріал","material","тканина","fabric"]): product["material"] = val
        elif any(lower.startswith(k) for k in ["категорія","category"]):    product["category"] = val
        elif any(lower.startswith(k) for k in ["стать","gender"]):          product["gender"]   = val
        elif any(lower.startswith(k) for k in ["постачальник","supplier"]): product["supplier"] = val
        elif "ціна" in lower or ("грн" in lower and re.search(r"\d+", line)):
            m = re.search(r"\d+", line.replace(" ",""))
            if m: product["price"] = m.group()
    for line in lines:
        line = strip_line_marker(line.strip())
        if line and ":" not in line and len(line) < 100:
            product["name"] = line; break
    return product

# ── Автовизначення категорії ──────────────────────────────
def detect_category(name: str, description: str = "") -> str:
    text = f"{name} {description}".lower()
    rules = [
        ("Костюм",      ["костюм", "комплект", "двійка", "трійка"]),
        ("Футболка",    ["футболка", "футбол", "t-shirt", "тішка"]),
        ("Шорти",       ["шорти", "shorts"]),
        ("Штани",       ["штани", "джогери", "джоггери", "брюки", "карго", "трекінг"]),
        ("Куртка",      ["куртка", "вітровка", "бомбер", "парка", "анорак"]),
        ("Худі",        ["худі", "hoodie", "толстовка"]),
        ("Світшот",     ["світшот", "sweatshirt"]),
        ("Сорочка",     ["сорочка", "рубашка", "shirt"]),
        ("Кофта",       ["кофта", "кардиган", "джемпер", "светр"]),
        ("Спідниця",    ["спідниця"]),
        ("Плаття",      ["плаття", "сукня", "dress"]),
        ("Кросівки",    ["кросівки", "кросовки", "sneakers", "найк", "адідас", "nike", "adidas"]),
        ("Черевики",    ["черевики", "boots"]),
        ("Кепка",       ["кепка", "шапка", "cap", "hat"]),
        ("Сумка",       ["сумка", "рюкзак", "bag"]),
    ]
    for category, keywords in rules:
        if any(kw in text for kw in keywords):
            return category
    return ""

# ── Telegram публічний пост ───────────────────────────────
def fetch_telegram(url: str, channel_name: str = "", post_index: int = 0, total_posts: int = 0) -> dict:
    embed_url = url.rstrip("/") + "?embed=1"
    try:
        html = curl_get_text(embed_url, timeout_seconds=20)
    except Exception as e:
        return {"error": f"Не вдалось завантажити пост: {e}"}

    # Текст
    raw_text_html = extract_telegram_text_html(html)
    raw_text = telegram_message_html_to_text(raw_text_html) if raw_text_html else ""

    # Фото URLs з HTML (тільки фото товару, без аватарок)
    raw_photos = extract_telegram_photo_urls(html)

    # Скачуємо фото послідовно: так простіше бачити, на якому саме файлі зависає Telegram/CDN.
    local_photos = []
    try:
        photo_urls = raw_photos[:10]
        for photo_idx, photo_url in enumerate(photo_urls, start=1):
            photo = download_photo(photo_url)
            if photo:
                local_photos.append(photo)
    except Exception as e:
        log(f"⚠️ Помилка при завантаженні фото: {str(e)[:60]}")

    product = parse_text(raw_text)
    product["photos"] = ", ".join(local_photos)
    product["source"] = "telegram"
    if not product.get("category"):
        product["category"] = detect_category(product.get("name",""), raw_text)
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
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(download_photo, raw_photos[:10]))
        local_photos = [lp for lp in results if lp]

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

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(download_photo, raw_photos[:10]))
        local_photos = [lp for lp in results if lp]

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
@app.route("/synced-products/delete", methods=["POST"])
def delete_synced_product():
    data = request.get_json() or {}
    product_id = str(data.get("id", "") or "").strip()
    if not product_id:
        return jsonify({"error": "id is required"}), 400

    with _sync_lock:
        products = []
        if SYNCED_PRODUCTS_FILE.exists():
            try:
                products = json.loads(SYNCED_PRODUCTS_FILE.read_text(encoding="utf-8"))
            except:
                products = []

        removed = [p for p in products if str(p.get("id", "")) == product_id]
        if not removed:
            return jsonify({"removed_products": 0, "deleted_photos": 0}), 404

        kept = [p for p in products if str(p.get("id", "")) != product_id]

        kept_photo_names = set()
        for product in kept:
            kept_photo_names.update(product_photo_filenames(product))

        removed_photo_names = set()
        for product in removed:
            removed_photo_names.update(product_photo_filenames(product))

        deleted_photos = 0
        photos_dir = PHOTOS_DIR.resolve()
        for filename in sorted(removed_photo_names - kept_photo_names):
            try:
                photo_path = (PHOTOS_DIR / filename).resolve()
                if photo_path.is_file() and photos_dir in photo_path.parents:
                    photo_path.unlink()
                    deleted_photos += 1
            except:
                pass

        SYNCED_PRODUCTS_FILE.write_text(
            json.dumps(kept, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    return jsonify({
        "removed_products": len(removed),
        "deleted_photos": deleted_photos,
    })

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

        kept_photo_names = set()
        for product in kept:
            kept_photo_names.update(product_photo_filenames(product))

        deleted_photos = 0
        photos_dir = PHOTOS_DIR.resolve()
        for photo_path in sorted(PHOTOS_DIR.glob("*")):
            try:
                photo_path = photo_path.resolve()
                if (
                    photo_path.is_file()
                    and photos_dir in photo_path.parents
                    and photo_path.name not in kept_photo_names
                ):
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
        for key in ("text_post_url", "post_url", "source_url", "media_post_url"):
            value = str(p.get(key, "") or "")
            nums = [int(n) for n in re.findall(r"/(\d+)(?:\D|$)", value)]
            if nums:
                return max(nums)
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
        existing_media_urls = [u.strip() for u in (text.get("media_post_url") or "").split(",") if u.strip()]
        for media in sorted(media_items, key=lambda p: post_num(p) or 0, reverse=True):
            photos.extend([p.strip() for p in (media.get("photos") or "").split(",") if p.strip()])
            media_url = media.get("post_url") or media.get("source_url", "")
            if media_url:
                media_urls.append(media_url)
        merged["photos"] = ", ".join(dedupe_photo_urls(photos))
        merged["media_post_url"] = ", ".join(dict.fromkeys(media_urls + existing_media_urls))
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

    referenced_media_urls = set()
    for item in list(replacements.values()) + products:
        if not has_text(item):
            continue
        for media_url in str(item.get("media_post_url", "") or "").split(","):
            media_url = media_url.strip()
            if media_url:
                referenced_media_urls.add(media_url)

    result = []
    for idx, p in enumerate(products):
        if idx in replacements:
            item = replacements[idx]
        elif idx not in used:
            item = p
        else:
            continue
        item_url = item.get("post_url") or item.get("source_url", "")
        if not has_text(item) and item_url in referenced_media_urls:
            continue
        item = dict(item)
        item["photos"] = ", ".join(dedupe_photo_urls(str(item.get("photos", "") or "").split(",")))
        result.append(item)
    return result

def merge_pattern_a_products(products: list) -> list:
    return merge_pattern_products(products)


def telegram_channel_pattern(channel: str) -> str:
    m = re.search(r':([ABCabc]|AUTO)$', str(channel or "").strip(), flags=re.IGNORECASE)
    return m.group(1).upper() if m else "AUTO"


def telegram_channel_name(channel: str) -> str:
    value = re.sub(r':([ABCabc]|AUTO)$', '', str(channel or "").strip(), flags=re.IGNORECASE)
    value = value.replace("https://t.me/", "").replace("http://t.me/", "")
    return value.strip("/").lstrip("@")


def telegram_message_text(msg) -> str:
    return getattr(msg, "message", None) if getattr(msg, "message", None) is not None else (getattr(msg, "text", "") or "")


def telegram_msg_ts(msg) -> int:
    return int(msg.date.timestamp()) if getattr(msg, "date", None) else 0


def telegram_api_build_blocks(messages: list, is_photo) -> list[dict]:
    blocks = []
    seen_grouped = {}
    for msg in sorted(messages, key=telegram_msg_ts):
        text = telegram_message_text(msg)
        if getattr(msg, "grouped_id", None):
            group_id = msg.grouped_id
            if group_id in seen_grouped:
                idx = seen_grouped[group_id]
                blocks[idx]["msgs"].append(msg)
                blocks[idx]["ts_end"] = max(blocks[idx]["ts_end"], telegram_msg_ts(msg))
                if text and text.strip() and not blocks[idx]["caption"]:
                    blocks[idx]["caption"] = text
                    blocks[idx]["text_msg"] = msg
            else:
                idx = len(blocks)
                seen_grouped[group_id] = idx
                blocks.append({
                    "type": "media", "msgs": [msg],
                    "ts": telegram_msg_ts(msg), "ts_end": telegram_msg_ts(msg),
                    "caption": text if text and text.strip() else "",
                    "text_msg": msg if text and text.strip() else None,
                })
        elif is_photo(msg):
            blocks.append({
                "type": "media", "msgs": [msg],
                "ts": telegram_msg_ts(msg), "ts_end": telegram_msg_ts(msg),
                "caption": text if text and text.strip() else "",
                "text_msg": msg if text and text.strip() else None,
            })
        elif text and text.strip():
            blocks.append({"type": "text", "msgs": [msg], "ts": telegram_msg_ts(msg), "text": text, "text_msg": msg})
    return blocks


async def telegram_api_download_photo(client, msg, channel_name: str) -> str | None:
    try:
        filename = f"tg_{normalize_channel_key(channel_name) or 'channel'}_{msg.id}.jpg"
        filepath = PHOTOS_DIR / filename
        if not filepath.exists():
            await client.download_media(msg, file=str(filepath))
        if filepath.exists() and filepath.stat().st_size > 0:
            _photos_downloaded[0] += 1
            return f"http://localhost:5001/photos/{filename}"
    except Exception as e:
        log(f"⚠️ Не вдалось скачати Telegram фото {getattr(msg, 'id', '')}: {str(e)[:60]}")
    return None


async def telegram_api_make_product(client, media_msgs: list, text: str, channel_name: str, text_msg, anchor_msg) -> dict | None:
    if not text or not text.strip() or not media_msgs:
        return None
    fields = parse_text(text)
    ids = [m.id for m in media_msgs if getattr(m, "id", None)]
    if text_msg and getattr(text_msg, "id", None):
        ids.append(text_msg.id)
    ids = sorted(set(ids))
    product_id = f"{ids[0]}_{ids[-1]}" if len(ids) > 1 else str(ids[0] if ids else getattr(anchor_msg, "id", ""))
    post_msg = text_msg or anchor_msg
    photos = []
    for msg in media_msgs[:10]:
        photo = await telegram_api_download_photo(client, msg, channel_name)
        if photo:
            photos.append(photo)
    post_url = f"https://t.me/{channel_name}/{getattr(post_msg, 'id', getattr(anchor_msg, 'id', ''))}"
    return {
        **fields,
        "id": f"tg_{product_id}_{channel_name}",
        "photos": ", ".join(dedupe_photo_urls(photos)),
        "post_url": post_url,
        "source_url": post_url,
        "post_date": post_msg.date.strftime("%d.%m.%Y") if getattr(post_msg, "date", None) else "",
        "source": "telegram",
        "supplier": f"@{channel_name}",
        "supplier_title": channel_name,
        "addedAt": datetime.now(timezone.utc).isoformat(),
    }


async def telegram_api_products_from_blocks(client, blocks: list, channel_name: str, pattern: str) -> list[dict]:
    async def build(media_msgs, text, text_msg, anchor_msg):
        return await telegram_api_make_product(client, media_msgs, text, channel_name, text_msg, anchor_msg)

    products = []
    if pattern == "C":
        for b in blocks:
            if b["type"] == "media" and b.get("caption"):
                p = await build(b["msgs"], b["caption"], b.get("text_msg"), b["msgs"][0])
                if p: products.append(p)
        return products

    if pattern == "A":
        n, used, i = len(blocks), [False] * len(blocks), 0
        while i < n:
            if used[i] or blocks[i]["type"] != "media":
                i += 1; continue
            media_msgs, anchor, last_ts = list(blocks[i]["msgs"]), blocks[i]["msgs"][0], blocks[i]["ts_end"]
            text, text_msg = blocks[i].get("caption", ""), blocks[i].get("text_msg")
            used[i] = True
            j = i + 1
            while j < n and not used[j] and blocks[j]["type"] == "media" and not blocks[j].get("caption"):
                if blocks[j]["ts"] - last_ts > 1200: break
                media_msgs.extend(blocks[j]["msgs"])
                last_ts = blocks[j]["ts_end"]
                used[j] = True; j += 1
            if not text and j < n and not used[j] and blocks[j]["type"] == "text" and blocks[j]["ts"] - last_ts <= 1200:
                text, text_msg = blocks[j]["text"], blocks[j].get("text_msg")
                used[j] = True; j += 1
            p = await build(media_msgs, text, text_msg, anchor)
            if p: products.append(p)
            i = j
        return products

    if pattern == "B":
        n, used, i = len(blocks), [False] * len(blocks), 0
        while i < n:
            if used[i] or blocks[i]["type"] != "text":
                i += 1; continue
            text, text_msg, last_ts = blocks[i]["text"], blocks[i].get("text_msg"), blocks[i]["ts"]
            media_msgs, anchor, j = [], None, i + 1
            while j < n and not used[j] and blocks[j]["type"] == "media" and not blocks[j].get("caption"):
                if blocks[j]["ts"] - last_ts > 1200: break
                anchor = anchor or blocks[j]["msgs"][0]
                media_msgs.extend(blocks[j]["msgs"])
                last_ts = blocks[j]["ts_end"]
                used[j] = True; j += 1
            if media_msgs:
                p = await build(media_msgs, text, text_msg, anchor)
                if p: products.append(p)
                used[i] = True
            i = j if media_msgs else i + 1
        return products

    products_c = await telegram_api_products_from_blocks(client, blocks, channel_name, "C")
    non_caption = [b for b in blocks if not (b["type"] == "media" and b.get("caption"))]
    products_a = await telegram_api_products_from_blocks(client, non_caption, channel_name, "A")
    products_b = await telegram_api_products_from_blocks(client, non_caption, channel_name, "B")
    return products_c + (products_a if len(products_a) >= len(products_b) else products_b)


async def sync_telegram_via_api(channels: list[str], disabled_channels: list[str], sync_progress: dict) -> dict:
    try:
        from telethon import TelegramClient
        from telethon.tl.types import MessageMediaPhoto, MessageService
    except ImportError:
        return {"error": "Telethon не встановлено. Виконай: pip install telethon"}

    api_id = int(get_env("TELEGRAM_API_ID") or "0")
    api_hash = get_env("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        return {"error": "TELEGRAM_API_ID або TELEGRAM_API_HASH не вказано"}

    from datetime import timedelta

    def is_photo(msg):
        return bool(getattr(msg, "media", None) and isinstance(msg.media, MessageMediaPhoto))

    client = TelegramClient(str(Path(__file__).parent / "session_parser"), api_id, api_hash)
    await client.start()
    products, channel_results, active_channels = [], {}, set()
    disabled_norm = {normalize_channel_key(c) for c in disabled_channels}
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    total_links = 0

    for raw_channel in channels:
        channel_name = telegram_channel_name(raw_channel)
        pattern = telegram_channel_pattern(raw_channel)
        norm = normalize_channel_key(channel_name)
        if norm in disabled_norm:
            channel_results[channel_name] = {"status": "disabled", "count": 0, "links": 0}
            continue
        last_id = int(sync_progress.get(norm, {}).get("last_id") or sync_progress.get(raw_channel, {}).get("last_id") or 0)
        try:
            raw_messages = []
            async for msg in client.iter_messages(channel_name, min_id=last_id):
                if isinstance(msg, MessageService) or getattr(msg, "action", None) is not None:
                    continue
                if msg.date and msg.date.replace(tzinfo=timezone.utc) < cutoff:
                    break
                raw_messages.append(msg)
            if not raw_messages:
                channel_results[channel_name] = {"status": "ok", "count": 0, "links": 0, "mode": "api"}
                active_channels.add(norm)
                continue
            max_id = max(msg.id for msg in raw_messages)
            blocks = telegram_api_build_blocks(raw_messages, is_photo)
            channel_products = await telegram_api_products_from_blocks(client, blocks, channel_name, pattern)
            keywords = get_archive_keywords()
            for p in channel_products:
                if not p.get("name") and p.get("description"):
                    first_line = p["description"].split("\n")[0].strip()
                    p["name"] = first_line[:80] if first_line else "Без назви"
                if not p.get("category"):
                    p["category"] = detect_category(p.get("name", ""), p.get("description", ""))
                # Автоархівація за ключовими словами
                p["archived"] = should_auto_archive(p, keywords)
            products.extend(channel_products)
            sync_progress[norm] = {"last_id": str(max_id)}
            active_channels.add(norm)
            total_links += len(raw_messages)
            channel_results[channel_name] = {"status": "ok", "count": len(channel_products), "links": len(raw_messages), "mode": "api"}
            channel_results[norm] = channel_results[channel_name]
        except Exception as e:
            channel_results[channel_name] = {"status": "error", "message": str(e)}
            log(f"⚠️ API {channel_name}: {str(e)[:120]}")

    await client.disconnect()
    return {"products": products, "channel_results": channel_results, "active_channels": active_channels, "total_links": total_links}


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
    active_channels = set()
    total_channel_links = 0
    skipped_problem_posts = []
    if source == "telegram":
        channels = [c.strip() for c in get_env("TELEGRAM_CHANNELS","").split(",") if c.strip()]
        use_api_sync = get_env("TELEGRAM_MODE", "public") != "public" and bool(get_env("TELEGRAM_API_ID")) and bool(get_env("TELEGRAM_API_HASH"))
        if use_api_sync:
            api_result = asyncio.run(sync_telegram_via_api(channels, disabled_channels, sync_progress))
            if api_result.get("error"):
                return {"error": api_result["error"]}
            new_products.extend(api_result.get("products", []))
            channel_results.update(api_result.get("channel_results", {}))
            active_channels.update(api_result.get("active_channels", set()))
            total_channel_links += api_result.get("total_links", 0)
            progress_file.write_text(json.dumps(sync_progress, ensure_ascii=False), encoding="utf-8")
            channels = []
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
                        progress_print(f"  {sp} 🔗 Канал @{ch_name}: збираю посилання: {_link_count[0]} | ⏱ {_t}          ")
                        time.sleep(0.1)
                existing_post_ids = {p.get("id") for p in existing}
                existing_post_numbers_for_channel = {
                    number
                    for item in existing
                    if product_matches_channel(item, ch)
                    for number in product_post_numbers(item)
                }
                last_synced_id = sync_progress.get(_norm(ch), {}).get("last_id") or sync_progress.get(ch, {}).get("last_id")
                try:
                    last_synced_id = int(last_synced_id) if last_synced_id else 0
                except ValueError:
                    last_synced_id = 0
                import threading
                threading.Thread(target=_spin_links, daemon=True).start()
                while page_url:
                    import time; time.sleep(1)
                    resp = requests.get(page_url, headers={"User-Agent":"Mozilla/5.0 (compatible; Googlebot/2.1)"}, timeout=10)
                    found = [
                        u for u in re.findall(r'href="(https://t\.me/[^"]+/\d+)"', resp.text)
                        if normalize_channel_key(u) == _norm(ch)
                    ]
                    all_post_urls.extend(found)
                    _link_count[0] = len(all_post_urls)
                    # Скануємо всі сторінки за 30 днів, навіть якщо між ними є вже збережені пости.
                    # Зупиняємось якщо сторінка містить пости старші за DATE_FROM
                    from datetime import timedelta
                    date_limit = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
                    dates_on_page = re.findall(r'datetime="(\d{4}-\d{2}-\d{2})', resp.text)
                    should_stop = dates_on_page and min(dates_on_page) < date_limit
                    found_ids = []
                    for found_url in found:
                        try:
                            found_ids.append(int(found_url.split("/")[-1]))
                        except ValueError:
                            pass
                    reached_synced_posts = last_synced_id and found_ids and min(found_ids) <= last_synced_id
                    prev_match = re.search(r'href="/s/' + ch_name + r'\?before=(\d+)"', resp.text)
                    if reached_synced_posts or should_stop or not prev_match:
                        break
                    page_url = f"https://t.me/s/{ch_name}?before={prev_match.group(1)}"
                _collecting[0] = False
                import time; time.sleep(0.15)
                clear_progress_line()
                # Парсимо тільки ті пости, яких ще немає в локальній базі каналу.
                post_urls = []
                for u in dict.fromkeys(all_post_urls):
                    pid = u.split('/')[-1]
                    try:
                        post_number = int(pid)
                        if last_synced_id and post_number <= last_synced_id:
                            continue
                        if post_number in existing_post_numbers_for_channel:
                            continue
                    except ValueError:
                        pass
                    if f"tg_{pid}_{ch}" in existing_post_ids:
                        continue
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
                _current_post_url = [""]
                def _spin_posts():
                    import itertools, time
                    for sp in itertools.cycle(["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]):
                        if not _processing[0]: break
                        _elapsed = int((datetime.now() - _sync_start).total_seconds())
                        _mins, _secs = divmod(_elapsed, 60)
                        _t = f"{_mins}хв {_secs}с" if _mins else f"{_secs}с"
                        progress_print(f"  {sp} 📄 Канал @{ch_name}: пост {_post_idx_ref[0]}/{total_posts} | 📥 фото: {_photos_downloaded[0]} | ⏱ {_t}          ")
                        time.sleep(0.1)
                threading.Thread(target=_spin_posts, daemon=True).start()
                if ch_pattern == "A":
                    post_urls = sorted(dict.fromkeys(post_urls), key=lambda u: int(u.split("/")[-1]))

                fetched_posts = {}
                def _get_post(purl, idx=0):
                    if purl not in fetched_posts:
                        fetched_posts[purl] = fetch_telegram(purl, ch_name, idx, total_posts)
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
                    _current_post_url[0] = purl

                    skip_post_ids = {
                        post_id.strip()
                        for post_id in get_env("TELEGRAM_SKIP_POST_IDS", "27887,27894").split(",")
                        if post_id.strip()
                    }
                    current_post_id = purl.rstrip("/").split("/")[-1]
                    if current_post_id in skip_post_ids:
                        clear_progress_line()
                        skipped_problem_posts.append(f"@{ch_name}/{current_post_id}")
                        _current_post_url[0] = ""
                        try:
                            sync_progress[_norm(ch)] = {"last_id": current_post_id}
                            progress_file.write_text(json.dumps(sync_progress, ensure_ascii=False), encoding="utf-8")
                        except Exception as e:
                            log(f"⚠️ Не вдалось зберегти прогрес @{ch_name}/{current_post_id}: {e}")
                        break

                    if stop_parsing:
                        break
                    post_id = purl.split('/')[-1]
                    if post_id in seen_ids:
                        post_idx += 1
                        continue
                    p = _get_post(purl, _post_idx_ref[0])
                    _current_post_url[0] = ""
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
                        clear_progress_line()
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
                        if not p.get("category"):
                            p["category"] = detect_category(p.get("name",""), p.get("description",""))
                        p["id"] = f"tg_{product_id}_{ch}"
                        p["supplier"] = ch
                        p["supplier_title"] = ch_title
                        p["source_url"] = product_url
                        p["post_url"] = product_url
                        p["addedAt"] = datetime.now(timezone.utc).isoformat()
                        # Автоархівація за ключовими словами
                        p["archived"] = should_auto_archive(p, get_archive_keywords())
                        new_products.append(p)
                        ch_count += 1
                        seen_ids.add(post_id)
                        # Зберігаємо прогрес
                        sync_progress[_norm(ch)] = {"last_id": progress_id}
                        progress_file.write_text(json.dumps(sync_progress, ensure_ascii=False), encoding="utf-8")
                    post_idx += 1
                _processing[0] = False
                import time; time.sleep(0.15)
                # Видалено проблемний print який зависає
                # print("\r" + " " * 80 + "\r", end="", flush=True)
                active_channels.add(_norm(ch))
                total_channel_links += len(all_post_urls)
                channel_results[_strip_pat(ch)] = {"status": "ok", "count": ch_count, "links": len(all_post_urls)}
                channel_results[_norm(ch)] = {"status": "ok", "count": ch_count, "links": len(all_post_urls)}
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
            keywords = get_archive_keywords()
            for p in resp.json():
                sizes = p.get("sizes",[])
                raw_photos = p.get("images",[])
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=5) as ex:
                    results = list(ex.map(download_photo, raw_photos[:5]))
                local_photos = [lp for lp in results if lp]
                product = {
                    "id": f"mydrop_{p.get('sku','')}",
                    "sku": p.get("sku",""), "name": p.get("title",""), "brand": p.get("brand",""),
                    "price": str(p.get("price","")), "size": ", ".join(s["title"] for s in sizes if s.get("amount",0)>0),
                    "color": p.get("color",""), "material": p.get("material",""), "gender": p.get("gender",""),
                    "condition": "Нове", "photos": ", ".join(local_photos), "description": p.get("description",""),
                    "source": "mydrop", "supplier": "MyDrop", "addedAt": "",
                    "archived": should_auto_archive({"name": p.get("title",""), "description": p.get("description","")}, keywords)
                }
                new_products.append(product)
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
            keywords = get_archive_keywords()
            for p in all_p:
                offers = p.get("offers",[])
                sizes  = [o.get("properties",{}).get("size","") for o in offers if o.get("quantity",0)>0]
                raw_photos = [a["url"] for a in p.get("attachments",[]) if a.get("url")]
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=5) as ex:
                    results = list(ex.map(download_photo, raw_photos[:5]))
                local_photos = [lp for lp in results if lp]
                product = {
                    "id": f"keycrm_{p.get('sku','')}",
                    "sku": p.get("sku",""), "name": p.get("name",""), "brand": p.get("brand",""),
                    "price": str(p.get("price","")), "size": ", ".join(filter(None,sizes)),
                    "color": p.get("properties",{}).get("color",""), "material": "", "gender": "",
                    "condition": "Нове", "photos": ", ".join(local_photos), "description": p.get("description",""),
                    "source": "keycrm", "supplier": "KeyCRM", "addedAt": "",
                    "archived": should_auto_archive({"name": p.get("name",""), "description": p.get("description","")}, keywords)
                }
                new_products.append(product)
        except Exception as e:
            return {"error": str(e)}

    if source == "telegram":
        existing = merge_pattern_a_products(existing)
        new_products = merge_pattern_a_products(new_products)
        # Групуємо варіації товарів (різні кольори одного товару)
        try:
            grouped_count_before = len(new_products)
            new_products = process_products(new_products)
            grouped_count_after = len(new_products)
            if grouped_count_before != grouped_count_after:
                log(f"🔗 Групування: {grouped_count_before} товарів → {grouped_count_after} після об'єднання варіацій")
        except Exception as e:
            log(f"⚠️ Помилка групування варіацій: {e}")
            pass

    # Фільтруємо нові (яких ще немає в existing та не опубліковані)
    existing_ids = {p.get("id") for p in existing}
    existing_post_numbers = {
        number
        for item in existing
        for number in product_post_numbers(item)
    }
    truly_new = [
        p for p in new_products
        if p.get("id") not in existing_ids
        and not (set(product_post_numbers(p)) & existing_post_numbers)
    ]
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

    if source == "telegram":
        for channel in active_channels:
            max_saved_id = max((
                product_max_post_id(p) or 0
                for p in merged
                if product_matches_channel(p, channel)
            ), default=0)
            current_id = int(sync_progress.get(channel, {}).get("last_id") or 0)
            if max_saved_id > current_id:
                sync_progress[channel] = {"last_id": str(max_saved_id)}
        progress_file.write_text(json.dumps(sync_progress, ensure_ascii=False), encoding="utf-8")

    products_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    sync_file = public_dir / "last_sync.json"
    sync_file.write_text(json.dumps({"synced_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False), encoding="utf-8")

    elapsed = (datetime.now() - _sync_start).seconds
    mins, secs = divmod(elapsed, 60)
    time_str = f"{mins} хв {secs} сек" if mins else f"{secs} сек"

    disabled_info = f" | ⏩ вимкнених: {len(_disabled_skipped)}" if _disabled_skipped else ""
    private_info  = f" | ⚠️ приватних: {len(_private_skipped)}" if _private_skipped else ""
    problem_posts_info = " | ⏭️ проблемних постів: 0"
    if skipped_problem_posts:
        problem_posts_info = f" | ⏭️ проблемних постів: {len(skipped_problem_posts)} ({', '.join(skipped_problem_posts[:5])})"

    result = {
        "total": len(new_products),
        "new_count": len(truly_new),
        "skipped": len(new_products)-len(truly_new),
        "channel_results": channel_results if source == "telegram" else {},
        "disabled_info": disabled_info,
        "private_info": private_info,
        "disabled_count": len(_disabled_skipped),
        "active_count": len(active_channels),
        "private_count": len(_private_skipped),
        "total_links": total_channel_links,
        "skipped_problem_posts": skipped_problem_posts,
        "problem_posts_info": problem_posts_info,
    }

    return result

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

# ── Архів ────────────────────────────────────────────────
ARCHIVE_KEYWORDS_FILE = Path(__file__).parent.parent / "public" / "archive_keywords.json"

def get_archive_keywords():
    """Повертає словник {channel: [keywords]} або {} якщо файл не існує"""
    if not ARCHIVE_KEYWORDS_FILE.exists():
        return {}
    try:
        data = json.loads(ARCHIVE_KEYWORDS_FILE.read_text(encoding="utf-8"))
        # Підтримка старого формату (масив) для зворотної сумісності
        if isinstance(data, list):
            return {}
        return data if isinstance(data, dict) else {}
    except:
        return {}

def save_archive_keywords(keywords_dict):
    """Зберігає словник {channel: [keywords]}"""
    ARCHIVE_KEYWORDS_FILE.write_text(json.dumps(keywords_dict, ensure_ascii=False, indent=2), encoding="utf-8")

def should_auto_archive(product, keywords_dict):
    """Перевіряє чи пост містить ключові слова для автоархівації по каналу.
    Якщо фільтр багаторядковий — всі рядки мають бути присутні у тексті (логіка AND).
    Якщо фільтр однорядковий — перевіряється просте входження.
    """
    if not keywords_dict or not isinstance(keywords_dict, dict):
        return False

    # Отримуємо канал продукту (supplier для Telegram)
    channel = product.get("supplier", "")
    if not channel:
        return False

    # Перевіряємо чи є ключові слова для цього каналу
    keywords = keywords_dict.get(channel, [])
    if not keywords:
        return False

    # Перевіряємо текст на наявність ключових слів
    text = f"{product.get('name', '')} {product.get('description', '')}".lower()

    for kw in keywords:
        if not kw.strip():
            continue
        lines = [line.strip() for line in kw.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            # Однорядковий фільтр — просте входження
            if lines[0].lower() in text:
                return True
        else:
            # Багаторядковий фільтр — всі рядки мають бути присутні (AND)
            if all(line.lower() in text for line in lines):
                return True

    return False

@app.route("/archive-keywords", methods=["GET"])
def get_archive_keywords_route():
    return jsonify(get_archive_keywords())

@app.route("/archive-keywords", methods=["POST"])
def save_archive_keywords_route():
    data = request.get_json() or {}
    keywords_dict = data.get("keywords", {})
    if not isinstance(keywords_dict, dict):
        return jsonify({"error": "keywords must be a dict"}), 400
    save_archive_keywords(keywords_dict)
    return jsonify({"ok": True})

@app.route("/apply-archive-rules", methods=["POST"])
def apply_archive_rules():
    """Застосовує правила архівування до всіх існуючих постів"""
    keywords_dict = get_archive_keywords()
    if not keywords_dict:
        return jsonify({"ok": True, "archived_count": 0})

    with _sync_lock:
        products = []
        if SYNCED_PRODUCTS_FILE.exists():
            try:
                products = json.loads(SYNCED_PRODUCTS_FILE.read_text(encoding="utf-8"))
            except:
                products = []

        archived_count = 0
        for p in products:
            # Пропускаємо вже архівовані
            if p.get("archived"):
                continue

            # Перевіряємо чи потрібно архівувати
            if should_auto_archive(p, keywords_dict):
                p["archived"] = True
                archived_count += 1

        SYNCED_PRODUCTS_FILE.write_text(
            json.dumps(products, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    return jsonify({"ok": True, "archived_count": archived_count})

@app.route("/archive-product", methods=["POST"])
def archive_product():
    data = request.get_json() or {}
    product_id = str(data.get("id", "") or "").strip()
    archived = bool(data.get("archived", False))

    if not product_id:
        return jsonify({"error": "id is required"}), 400

    with _sync_lock:
        products = []
        if SYNCED_PRODUCTS_FILE.exists():
            try:
                products = json.loads(SYNCED_PRODUCTS_FILE.read_text(encoding="utf-8"))
            except:
                products = []

        found = False
        for p in products:
            if str(p.get("id", "")) == product_id:
                p["archived"] = archived
                found = True
                break

        if not found:
            return jsonify({"error": "Product not found"}), 404

        SYNCED_PRODUCTS_FILE.write_text(
            json.dumps(products, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    return jsonify({"ok": True, "archived": archived})

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
        try:
            result = sync_source(source, disabled_channels=disabled_channels)
        finally:
            _mark_sync_finished()
    if "error" in result: return jsonify(result), 400
    extra = (result.get('disabled_info','') + result.get('private_info','') + result.get('problem_posts_info','')).strip(' |')
    suffix = f" | {extra}" if extra else ""
    total_links = result.get('total_links', sum(v.get('links',0) for v in result.get('channel_results',{}).values()))
    clear_progress_line()
    log(f"✅ Синк: нових {result.get('new_count',0)} | пропущено існуючих {result.get('skipped',0)} | 📥 фото: {_photos_downloaded[0]} | 🔗 посилань: {total_links} | ✅ активних: {result.get('active_count',0)} | ❌ вимкнених: {result.get('disabled_count',0)} | ⏳ Очікує API: {result.get('private_count',0)}{suffix}")
    return jsonify(result)

logging.getLogger("werkzeug").setLevel(logging.ERROR)

if __name__ == "__main__":
    import sys
    # Встановлюємо UTF-8 для stdout щоб емодзі працювали в Windows
    if sys.platform == "win32":
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

    import threading

    def auto_sync_loop_after_finish():
        import time
        interval = 30 * 60
        startup_sync = True
        time.sleep(20)

        while True:
            anchor = _autosync_anchor_time(include_saved=not startup_sync)
            wait_seconds = interval - (datetime.now(timezone.utc) - anchor).total_seconds()
            if wait_seconds > 0:
                time.sleep(min(wait_seconds, 60))
                continue

            if not _sync_lock.acquire(timeout=5):
                continue

            try:
                anchor = _autosync_anchor_time(include_saved=not startup_sync)
                wait_seconds = interval - (datetime.now(timezone.utc) - anchor).total_seconds()
                if wait_seconds > 0:
                    startup_sync = False
                    continue

                startup_sync = False
                print("")
                log("🔄 Автосинк: синхронізую Telegram...")
                try:
                    disabled = []
                    disabled_file = Path(__file__).parent.parent / "public" / "disabled_channels.json"
                    if disabled_file.exists():
                        try:
                            disabled = json.loads(disabled_file.read_text(encoding="utf-8"))
                        except Exception:
                            disabled = []

                    result = sync_source("telegram", disabled_channels=disabled)
                    total_links = result.get("total_links", sum(v.get("links", 0) for v in result.get("channel_results", {}).values()))
                    extra = (result.get("disabled_info", "") + result.get("private_info", "") + result.get("problem_posts_info", "")).strip(" |")
                    suffix = f" | {extra}" if extra else ""
                    log(f"✅ Автосинк: нових {result.get('new_count',0)} | пропущено існуючих {result.get('skipped',0)} | 📥 фото: {_photos_downloaded[0]} | 🔗 посилань: {total_links} | ✅ активних: {result.get('active_count',0)} | ❌ вимкнених: {result.get('disabled_count',0)} | ⏳ Очікує API: {result.get('private_count',0)}{suffix}")
                except Exception as e:
                    log(f"❌ Автосинк помилка: {e}")
                finally:
                    _mark_sync_finished()
            finally:
                _sync_lock.release()

    threading.Thread(target=auto_sync_loop_after_finish, daemon=True).start()
    app.run(host="127.0.0.1", port=5001, debug=False)
