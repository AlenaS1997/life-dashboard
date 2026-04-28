# Life Dashboard — контекст проекта

## Цель
Оцифровать жизнь Алёны: сон, питание, активность, восстановление.
Результат — iPhone-дашборд + утренний Telegram-дайджест с инсайтами от Claude.

Данные → Google Sheets ID: `1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE`

## Источники данных

| Источник | Метрики | Статус |
|----------|---------|--------|
| Garmin | Сон, HRV, шаги, стресс, Body Battery | Скрипт готов, живёт в Sheets, кэш сессии через garth |
| Google Calendar | События дня | Переезжаем с Make.com (упёрся в лимит 1000 операций) на n8n. Workflow готов: `n8n/gcal-sync-workflow.json`. Нужен импорт + Google OAuth credential. |
| FatSecret | Питание (калории, БЖУ) | Ожидаем доступ (пароль) |
| Whoop | Восстановление | Не подключён (опционально) |

## Инфраструктура

- **Make.com**: старый сценарий «Integration Google Calendar» (Calendar → Sheets every 15 min). Упёрся в лимит 1000 ops/мес, исчерпан 15 апреля. Также был баг: `singleEvents: false` — повторяющиеся события не разворачивались в экземпляры на день. Заменяется на n8n. После запуска n8n — отключить.
- **n8n**: `https://n8n-production-e175.up.railway.app` — три workflow готовы (gcal-sync, morning-digest, weekly-digest). Без лимитов операций.
- **GitHub Actions**: два workflow в `.github/workflows/`:
  - `garmin-sync.yml` — cron 08:05 МСК, актуальный.
  - `pages.yml` — деплой `dashboard/` на Pages при пуше (вручную через workflow_dispatch тоже).
- **Google Cloud**: проект `life-dashboard-494212` (номер `1095452022430`).
  - Service account: `life-dashboard-writer@life-dashboard-494212.iam.gserviceaccount.com`
  - JSON-ключ: `.secrets/service-account.json` (в `.gitignore`)

## Дашборд

- AppSheet отклонён (не красиво).
- Решение: **кастомный HTML-дашборд**, открывается в Safari на iPhone, добавляется на домашний экран как PWA.
- Чтение данных — через публичный CSV-экспорт Google Sheets (без auth для read-only).
- Деплой: GitHub Pages (публичный репо без чувствительных данных) или Cloudflare Pages (если приватный).

## Текущее состояние (по состоянию на 2026-04-28, утро после второй ночной сессии)

**Сделано:**
- Структура папки: `scripts/`, `tests/`, `dashboard/`, `n8n/`, `data/`, `reports/`, `.secrets/`, `.github/workflows/`.
- `.env`, `.gitignore`, `.env.example`, `requirements.txt` — готовы.
- `scripts/garmin_sync.py` — Garmin → Sheets с бэкофом 429, кэшем garth-токенов, идемпотентной записью.
- `scripts/clear_gcal_events.py` — одноразовая чистка вкладки `gcal_events` от мусора Make.com.
- `tests/test_garmin_sync.py` — 22 unit-теста на парсеры HRV / Body Battery / fetch_garmin_data (через моки). Все зелёные.
- Service account создан, Sheets/Drive API включены, JSON в `.secrets/service-account.json`.
- **GitHub репо** `AlenaS1997/life-dashboard` (public), 5 секретов в Actions.
- **GitHub Actions cron** `garmin-sync.yml` — каждый день 08:05 МСК, `actions/cache` на garth-токены.
- **GitHub Pages** через `pages.yml`. URL: `https://alenas1997.github.io/life-dashboard/`.
- **Дашборд `dashboard/index.html`** (iPhone-first, тёмная тема):
  - блок погоды (Open-Meteo, без ключа);
  - **цветовая индикация good/warn/bad** на карточках сегодня (рамка + точка);
  - **сравнение с прошлой неделей** в трендах (бейдж ▲/▼ % с цветом по знаку);
  - **heatmap сна за 30 дней** — мозаика 7 колонок;
  - **pull-to-refresh** на iPhone;
  - skeleton-лоадер, detect закрытой Sheets, localStorage-кэш.
- **Service Worker `dashboard/sw.js` (v3)** — offline-кэш статики и API.
- **n8n workflow’ы** (3 файла):
  - `gcal-sync-workflow.json` (cron 08:00 МСК) — Calendar → Sheets, идемпотентно (Clear+Append), `singleEvents: true`. Замена для Make.com. Импортирован, ждёт OAuth credential.
  - `morning-digest-workflow.json` (cron 08:30 МСК) — Garmin + события + **погода** + Claude (промпт v2: тёплый, без коучинговых слов) + ссылка на дашборд. retry на всех HTTP, fallback с сырыми числами + ссылкой на дашборд. Ждёт credentials.
  - `weekly-digest-workflow.json` (cron вс 19:00 МСК) — недельный итог.

**История правок Make.com (была причиной отсутствия событий на дашборде):**
- Schedule: every 15 min → **every day 08:00** (96 ops/day → 1 ops/day, лимит 1000 ops/мес остаётся в запасе).
- Search Events: `addDays(now;-1)` для обоих полей → `addDays(now;0)` ... `addDays(now;1)` (искало вчера → ищет сегодня).
- `Single Events: No → Yes` (повторяющиеся события теперь разворачиваются в индивидуальные).
- `Limit: 10 → 50`.

**Следующий шаг для Алёны (`MORNING.md`):**
1. `git push` с Mac — все ночные коммиты улетят, Pages передеплоится автоматически.
2. Запустить `python3.11 scripts/clear_gcal_events.py` — почистить старые строки 14 апреля.
3. Активация Telegram-бота: BotFather → токен, @userinfobot → chat_id, Anthropic API key, импорт `morning-digest-workflow.json`, подставить credentials, тест → Active.
4. (Опц.) Завершить переезд `gcal-sync` на n8n: Google OAuth credential, тест, отключить Make.com.

**Осталось по плану:**
- День 4 (28.04): активация Telegram-бота — 30–45 минут.
- День 5 (29.04): добивка Telegram + (опц.) n8n переезд — 20–30 минут.
- День 6 (30.04): полировка под живые данные за неделю.
- День 7 (1.05): FatSecret или закрытие проекта.

## Правила работы

- Ничего не удалять без подтверждения.
- Отчёты сохранять в `reports/` с датой.
- Язык общения и комментариев в коде: русский.
- Секреты (`.env`, `.secrets/`, JSON-ключи) — никогда не коммитить.
