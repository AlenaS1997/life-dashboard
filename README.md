# Life Dashboard

Персональная оцифровка жизни: сон, активность, питание, восстановление → Google Sheets → HTML-дашборд на iPhone + утренний Telegram-дайджест с AI-инсайтами.

## Архитектура

```
  Garmin Connect ─┐
  FatSecret      ─┼──► Google Sheets ──► HTML dashboard (GitHub Pages)
  Google Calendar─┘          │
                             └──► n8n + Claude API ──► Telegram утренний дайджест
```

## Структура папки

```
LifeDashboard/
├── CLAUDE.md                    # Контекст проекта для Claude-сессий
├── README.md                    # Этот файл
├── MORNING.md                   # Текущий чек-лист на сегодня
├── .env                         # Секреты (в .gitignore!)
├── .env.example                 # Шаблон секретов
├── .gitignore
├── requirements.txt             # Python зависимости
├── scripts/
│   ├── garmin_sync.py           # Garmin → Google Sheets (cron 08:05 МСК)
│   ├── clear_gcal_events.py     # Одноразовая чистка вкладки gcal_events
│   ├── fatsecret_auth.py        # OAuth 1.0a setup для FatSecret Premier (одноразово)
│   ├── fatsecret_sync.py        # FatSecret Premier API → Sheets (если есть Premier)
│   └── fatsecret_scraper.py     # FatSecret WEB scraper (бесплатная альтернатива)
├── tests/
│   └── test_garmin_sync.py      # Unit-тесты для парсеров (HRV, Body Battery, fetch)
├── dashboard/                   # iPhone-дашборд (HTML, деплоится на GitHub Pages)
│   ├── index.html               # HTML+CSS+JS: погода, тренды + дельта vs прошлая неделя, heatmap сна, статусы good/warn/bad, pull-to-refresh
│   ├── sw.js                    # Service Worker для offline-кэша
│   ├── manifest.webmanifest
│   ├── icon.svg
│   └── README.md
├── n8n/                         # workflow-файлы для n8n
│   ├── gcal-sync-workflow.json              # Google Calendar → Sheets, ежедневно 08:00 МСК
│   ├── morning-digest-workflow.json         # утренний дайджест 08:30 МСК
│   ├── weekly-digest-workflow.json          # недельный итог вс 19:00 МСК
│   ├── health-reminders-workflow.json       # напоминания по здоровью 09:00 МСК (sheets-driven)
│   ├── claude-prompt.md
│   ├── health-reminders-README.md
│   └── README.md
├── .secrets/
│   ├── service-account.json     # Ключ Google сервис-аккаунта (в .gitignore!)
│   └── garth/                   # OAuth-токены Garmin (в .gitignore!)
├── data/                        # Кэш сессий, промежуточные данные
├── reports/                     # Отчёты + логи запусков (garmin_YYYY-MM-DD.log)
└── .github/
    └── workflows/
        ├── garmin-sync.yml      # cron 08:05 МСК — Garmin → Sheets
        └── pages.yml            # деплой dashboard/ на GitHub Pages
```

## Локальный запуск (на Mac)

Требуется Python 3.11+. Если только что поставили через Homebrew — используйте `python3.11` (не `python3`).

```bash
# Установить зависимости
python3.11 -m pip install -r requirements.txt

# Пробный запуск без записи в Sheets
python3.11 scripts/garmin_sync.py --dry-run

# Боевой запуск (вчерашний день)
python3.11 scripts/garmin_sync.py

# Конкретная дата
python3.11 scripts/garmin_sync.py --date 2026-04-20

# Запустить тесты для парсеров (без сети, через моки)
python3.11 -m unittest tests.test_garmin_sync -v

# Одноразовая чистка вкладки gcal_events (если в ней мусор от Make.com)
python3.11 scripts/clear_gcal_events.py --dry-run   # сначала посмотреть
python3.11 scripts/clear_gcal_events.py             # реально почистить
```

## Переменные окружения (`.env`)

| Переменная | Описание |
|------------|----------|
| `GARMIN_EMAIL` | Логин Garmin Connect |
| `GARMIN_PASSWORD` | Пароль Garmin Connect |
| `GOOGLE_SHEET_ID` | ID таблицы (из URL между `/d/` и `/edit`) |
| `GOOGLE_SERVICE_ACCOUNT_PATH` | Путь к JSON-ключу (по умолчанию `.secrets/service-account.json`) |
| `GARMIN_WORKSHEET_NAME` | Имя вкладки в таблице (по умолчанию `Garmin`) |

## Настройка Google Sheets (разово)

1. В [Google Cloud Console](https://console.cloud.google.com/) создать проект.
2. Включить два API: **Google Sheets API** и **Google Drive API**.
3. IAM & Admin → Service Accounts → создать `life-dashboard-writer`.
4. У аккаунта: Keys → Add Key → JSON → скачать, положить в `.secrets/service-account.json`.
5. Открыть Google Sheets таблицу → Share → добавить email сервис-аккаунта (`client_email` из JSON) с ролью **Editor**.
6. Создать в таблице вкладку с именем, указанным в `GARMIN_WORKSHEET_NAME` (по умолчанию `Garmin`).

## GitHub Actions (автозапуск)

Workflow `.github/workflows/garmin-sync.yml` запускается ежедневно в 08:05 МСК и вручную из вкладки Actions.

### Секреты репозитория

В GitHub: Settings → Secrets and variables → Actions → New repository secret. Добавить:

| Секрет | Значение |
|--------|----------|
| `GARMIN_EMAIL` | Логин Garmin |
| `GARMIN_PASSWORD` | Пароль Garmin |
| `GOOGLE_SHEET_ID` | ID таблицы |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | **Всё содержимое** файла `service-account.json` (копировать JSON-текст целиком) |
| `GARMIN_WORKSHEET_NAME` | Имя вкладки (`Garmin`) |

После добавления секретов — зайти в Actions, выбрать «Garmin → Google Sheets sync», нажать «Run workflow» для ручной проверки.

## Колонки вкладки Garmin

| Колонка | Описание |
|---------|----------|
| `date` | Дата YYYY-MM-DD |
| `sleep_hours` | Часы сна |
| `sleep_score` | Sleep Score (0–100) |
| `hrv` | HRV last-night average |
| `steps` | Шаги за день |
| `stress` | Средний стресс (0–100) |
| `bb_max` | Body Battery максимум |
| `bb_min` | Body Battery минимум |

Скрипт идемпотентный — не дублирует строку, если дата уже записана.

## Известные ограничения

- **Garmin 429**: при частых запросах API временно блокирует. Скрипт:
  1. Сначала пробует поднять сессию из кэша `.secrets/garth/` (oauth-токены) — без логина.
  2. Если кэша нет или токены протухли — делает полный логин с экспоненциальным бэкофом (30s → 60s → 120s → 240s) и сохраняет свежие токены.
  В GitHub Actions эти же токены кэшируются через `actions/cache`, так что ежедневный прогон тоже обычно проходит без логина.
- **HRV/Body Battery = 0**: если часы не носились ночью или не поддерживают метрику, соответствующий эндпоинт возвращает пусто. Скрипт это переживает, просто пишет 0.

## Дашборд и Telegram-дайджест

- **Дашборд**: см. `dashboard/README.md`. Одностраничное HTML-приложение, открывается по `https://alenas1997.github.io/life-dashboard/`, добавляется на домашний экран iPhone через Safari. Читает данные из публичного CSV-экспорта Google Sheets, без backend. Service Worker (`sw.js`) кэширует статику и последние данные для offline.
- **Telegram-дайджест**: см. `n8n/README.md`. Два готовых workflow для n8n:
  - утренний (cron 08:30 МСК) — короткий тёплый дайджест с инсайтом дня;
  - воскресный недельный (cron вс 19:00 МСК) — итог недели с агрегатами и фокусом на следующую.
  Оба с retry на сеть и fallback-сообщением при провале Claude.

## Roadmap

- [x] Garmin → Google Sheets (manual + GitHub Actions cron)
- [x] Кэш garth-токенов для обхода 429
- [x] HTML-дашборд MVP
- [x] Деплой дашборда на GitHub Pages (через `.github/workflows/pages.yml`)
- [x] Погода (Open-Meteo) + Service Worker offline-кэш + skeleton-лоадер
- [x] Detect закрытой Sheets с понятной инструкцией
- [x] n8n утренний + воскресный workflow’ы готовы
- [ ] Активация Telegram-бота (Дни 5–6: BotFather + Anthropic API key)
- [ ] FatSecret → Sheets (когда будет доступ)
- [ ] Whoop (опционально)

## Правила работы

- Ничего не удалять без подтверждения.
- Отчёты сохранять в `reports/` с датой.
- Язык общения и комментариев — русский.
