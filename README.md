# 🛍 Marketplace Poster — Постинг товарів на українські маркетплейси

## 📌 Що це таке
Інструмент для дропшипера — автоматизує публікацію одягу та взуття з Telegram каналів та CRM систем (MyDrop, KeyCRM) на українські маркетплейси.

## 🏪 Підтримувані маркетплейси
| Маркетплейс | Метод | Формат файлу |
|---|---|---|
| Rozetka | REST API | JSON |
| Prom.ua / Bigl.ua | XML/YML | XML |
| Shafa.ua | через Prom.ua | XML |
| Kasta | Excel | CSV |
| OLX | OAuth API | JSON |
| Mono базар | ❌ Закритий | — |

## 📥 Джерела даних
| Джерело | Статус | Примітка |
|---|---|---|
| Telegram публічні канали | ✅ | Без API ключів |
| Telegram приватні канали | ✅ | Потребує API ID + Hash |
| MyDrop (дропшипер) | ✅ | Потребує API токен |
| KeyCRM | ✅ | Потребує API ключ |
| Вручну / текст посту | ✅ | Завжди доступно |

## 🗂 Структура проекту
```
marketplace-poster/
├── public/
│   ├── index.html
│   ├── products.json          ← базові товари (порожній)
│   └── synced_products.json   ← товари після синхронізації (gitignore)
├── src/
│   ├── App.js                 ← головний React компонент
│   ├── App.css                ← стилі
│   ├── PhotoManager.js        ← менеджер фото (порядок, додавання, видалення)
│   ├── PhotoManager.css
│   ├── SourcesView.js         ← вкладка "Джерела" (Telegram канали, CRM)
│   └── index.js
├── scripts/
│   ├── server.py              ← локальний Flask сервер (порт 5001)
│   ├── deduplication.py       ← перевірка дублікатів по SKU та хешу
│   ├── mydrop_sync.py         ← синхронізація MyDrop
│   ├── keycrm_sync.py         ← синхронізація KeyCRM
│   ├── telegram_parser.py     ← парсинг Telegram каналів
│   ├── requirements.txt       ← Python залежності
│   ├── .env.example           ← приклад налаштувань (скопіюй в .env)
│   └── photos/                ← локальні фото товарів (gitignore)
├── .gitignore
└── package.json
```

## 🚀 Запуск

### 1. Встановити Node.js (18+) та Python (3.10+)

### 2. React додаток
```bash
npm install
npm start
# Відкриється на http://localhost:3000 або :3001
```

### 3. Python сервер (в окремому терміналі)
```bash
cd scripts
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python server.py
# Запускається на http://localhost:5001
```

### 4. Налаштування API ключів
Скопіюй `scripts/.env.example` → `scripts/.env` і заповни:
```
TELEGRAM_MODE=public
TELEGRAM_CHANNELS=@channel1,@channel2
MYDROP_TOKEN=твій_токен
KEYCRM_KEY=твій_ключ
```
Або через вкладку **🔌 Джерела** в додатку.

## 🔑 Де взяти API ключі
- **MyDrop**: mydrop.com.ua → Інтеграції → API
- **KeyCRM**: ваш_домен.keycrm.app → Налаштування → API
- **Telegram API** (для приватних каналів): my.telegram.org → App configuration

## 🧩 Вкладки додатку
| Вкладка | Функція |
|---|---|
| 📋 Стрічка | Список товарів з фільтрами, вибір для публікації |
| 🔌 Джерела | Додавання Telegram каналів та CRM, синхронізація |
| 🛒 Маркетплейси | Увімкнення/вимкнення маркетплейсів |
| 📦 Результат | Завантаження згенерованих файлів |
| ⚙️ Налаштування | Загальні налаштування |

## 🔄 Логіка дедублікації
- Товар з CRM (є SKU) → перевірка по SKU
- Товар з Telegram (немає SKU) → перевірка по хешу (назва + ціна + фото)
- База опублікованих: `localStorage` в браузері + `scripts/published.json`

## ⚠️ Важливо
- `scripts/.env` — не пушити на GitHub (вже в .gitignore)
- `scripts/photos/` — локальні фото, не пушити
- Для роботи автозаповнення по посиланню потрібен запущений `server.py`
