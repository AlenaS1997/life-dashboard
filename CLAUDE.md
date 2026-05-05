# Life Dashboard — контекст проекта

## Цель
Оцифровать жизнь Алёны: сон, питание, активность, восстановление.
Результат — iPhone-дашборд + утренний Telegram-дайджест с инсайтами от Claude.

Данные → Google Sheets ID: `1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE`

## Источники данных

| Источник | Метрики | Статус |
|----------|---------|--------|
| Garmin | Сон, HRV, шаги, стресс, Body Battery | ✅ GitHub Actions cron 08:05 МСК. |
| Google Calendar (Fluffy) | События дня | ✅ n8n workflow `gcal-sync` опубликован, cron 08:00 МСК. Тянет из календаря `Fluffyismylifemoscow@gmail.com` (расшарен с основным аккаунтом). Make.com отключён. |
| FatSecret | Питание (калории, БЖУ) | ✅ Web-scraper `scripts/fatsecret_scraper.py` парсит Diary.aspx?pa=fj через Selenium. GitHub Actions cron 22:00 МСК (`.github/workflows/fatsecret-sync.yml`). CI логинится через cookies из секрета `FATSECRET_COOKIES_JSON` (экспорт — `scripts/fatsecret_export_cookies.py`). Бэкфилл за 30 дней есть в `fatsecret_daily`. |
| Whoop | Восстановление | Не подключён (опционально) |

## Инфраструктура

- **Make.com**: старый сценарий «Integration Google Calendar» — отключается. Был причиной отсутствия событий на дашборде (упёрся в лимит 1000 ops + `singleEvents: false`).
- **n8n**: `https://n8n-production-e175.up.railway.app` на Railway. Persistent volume `/home/node/.n8n` подключён (после серии граблей с потерей базы при рестарте). Env vars настроены: `N8N_HOST`, `N8N_PROTOCOL=https`, `WEBHOOK_URL`, `N8N_EDITOR_BASE_URL` — для корректного OAuth callback URL. Три workflow:
  - `gcal-sync` — **активен**, cron 08:00 МСК.
  - `morning-digest` — готов в репо, **ждёт активации** (нужны Telegram + Anthropic credentials).
  - `weekly-digest` — готов в репо, ждёт тех же credentials.
- **Railway**: trial кончается через ~10 дней ($5/мес Hobby после).
- **GitHub Actions**: три workflow в `.github/workflows/`:
  - `garmin-sync.yml` — cron 08:05 МСК, актуальный.
  - `fatsecret-sync.yml` — cron 22:00 МСК, активен. Ставит Chrome через `browser-actions/setup-chrome@v1`, логин через `FATSECRET_COOKIES_JSON` (Secret).
  - `pages.yml` — деплой `dashboard/` на Pages при пуше (вручную через workflow_dispatch тоже).
- **Google Cloud**: проект `life-dashboard-494212` (номер `1095452022430`).
  - Service account: `life-dashboard-writer@life-dashboard-494212.iam.gserviceaccount.com`
  - JSON-ключ: `.secrets/service-account.json` (в `.gitignore`)

## Дашборд

- AppSheet отклонён (не красиво).
- Решение: **кастомный HTML-дашборд**, открывается в Safari на iPhone, добавляется на домашний экран как PWA.
- Чтение данных — через публичный CSV-экспорт Google Sheets (без auth для read-only).
- Деплой: GitHub Pages (публичный репо без чувствительных данных) или Cloudflare Pages (если приватный).

## Текущее состояние (по 2026-04-29, после третьей ночной сессии)

**Работает в продакшене:**
- `garmin_sync.py` через GitHub Actions, cron 08:05 МСК (тесты — 22 шт).
- n8n `gcal-sync` workflow, cron 08:00 МСК — события Fluffy → `gcal_events`.
- Дашборд https://alenas1997.github.io/life-dashboard/ с фичами:
  - Карточки «Сегодня» с цветовой индикацией good/warn/bad.
  - Тренды vs прошлая неделя (▲/▼ % бейджи).
  - Heatmap сна за 30 дней.
  - **Композитный score дня** (sleep 35% + HRV 25% + stress 20% + BB 20%).
  - **Серии (streaks)** — подряд дни ≥3 в норме/проблеме.
  - Pull-to-refresh на iPhone.
  - **Без блока погоды** (убран по запросу).
  - Без блока «События дня» (дублировал нативный календарь).
- Service Worker v5.

**Готово, ждёт активации Алёной:**
- `morning-digest-workflow.json` — Telegram-дайджест 08:30 МСК.
  Промпт v3 (аналитик, тренды 7/14/30, streak'и, разбор причин,
  одна рекомендация). Нужны: BotFather токен, chat_id, Anthropic API key.
- `weekly-digest-workflow.json` — воскресный итог 19:00 МСК.
- `scripts/fatsecret_sync.py` + `scripts/fatsecret_auth.py` — каркас FS
  интеграции. Ждёт регистрацию на platform.fatsecret.com.

**Грабли которые мы прошли в эту сессию:**
- Make.com упёрся в лимит 1000 ops/мес из-за `every 15 min` schedule + `singleEvents: false`. Починили оба, но потом всё равно переехали на n8n.
- n8n на Railway без persistent volume → база слетала при каждом передеплое (3 раза прошли owner setup). Решено через volume mount `/home/node/.n8n`.
- n8n env vars `N8N_HOST` / `N8N_PROTOCOL` / `WEBHOOK_URL` / `N8N_EDITOR_BASE_URL` нужны для корректного OAuth callback URL (по умолчанию был localhost:5678).
- OAuth client в Google Cloud — отдельный wizard «Project configuration», нужен External + добавить email в Test users.
- Календарь Fluffy — другой Google аккаунт, но расшарен на основной → можем тянуть его через credential основного аккаунта, просто меняем `calendar_id` на email Fluffy.
- IF-нода в n8n не пропускала items от Маппим к Append — упростили pipeline (убрали IF и Clear, теперь Append получает 19 events напрямую). Дубли решим в следующую сессию через `appendOrUpdate`.
- Нода Google Calendar в n8n при импорте JSON не маппит `singleEvents` — нужно явно ставить **All Occurrences** в Recurring Event Handling + Timezone = Europe/Moscow в Options.

**Следующий шаг (`MORNING.md`):**
1. `git push` — улетят правки дашборда (события убраны, score+streaks добавлены).
2. Telegram-бот: BotFather → chat_id → Anthropic key → подвязать в morning-digest → Publish.
3. (Опц.) FatSecret: регистрация dev account → проверить доступ к food diary → запустить fatsecret_auth.py → fatsecret_sync.py.

**Осталось по плану:**
- ⏳ Активация Telegram-бота — 30–40 минут активной работы Алёны.
- ⏳ FatSecret интеграция (когда будет dev account + Premier API проверка) — 1.5–3 часа.
- ⏳ Доделка дублей в gcal-sync (appendOrUpdate вместо append).
- ⏳ Финальный отчёт + закрытие проекта.

## Правила работы

- Ничего не удалять без подтверждения.
- Отчёты сохранять в `reports/` с датой.
- Язык общения и комментариев в коде: русский.
- Секреты (`.env`, `.secrets/`, JSON-ключи) — никогда не коммитить.
