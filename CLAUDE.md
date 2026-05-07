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

## Текущее состояние (по 2026-05-06, ночная сессия с FS + дашбордом)

**Работает в продакшене:**
- `garmin_sync.py` через GitHub Actions, cron 08:05 МСК. Расширен новыми полями:
  `deep_sleep_min`, `light_sleep_min`, `rem_sleep_min`, `awake_sleep_min`,
  `bedtime`, `wakeup` (+авто-расширение шапки в `garmin_daily`).
- `fatsecret_scraper.py` через GitHub Actions, cron 22:00 МСК. Логин через
  cookies из секрета `FATSECRET_COOKIES_JSON`. Бэкфилл за 30 дней лежит
  во вкладке `fatsecret_daily`.
- n8n `gcal-sync` workflow — события Fluffy → `gcal_events` (cron 08:00 МСК,
  завязан на ту же таймзону инстанса).
- Telegram-бот `@ms_life_dashboard_bot` через n8n: утренний дайджест,
  воскресный итог, парсер напоминаний из свободного текста.
- Дашборд https://alenas1997.github.io/life-dashboard/ с фичами:
  - Карточки «Сегодня» с good/warn/bad по Garmin.
  - Тренды vs прошлая неделя (▲/▼ % бейджи).
  - **Питание · вчера** — ккал + Б/Ж/У с цветом по % от цели.
  - **Серии в норме · КБЖУ** — 4 счётчика подряд дней в ±15% от цели.
  - Heatmap сна за 30 дней.
  - **Фазы сна за 14 дней** — стэкбары deep/light/REM/awake.
  - **Отбой и подъём за 30 дней** — две линии в SVG.
  - Композитный score дня (sleep 35% + HRV 25% + stress 20% + BB 20%).
  - Серии Garmin (streaks ≥3 дней).
  - Pull-to-refresh на iPhone.
- Service Worker v6.

**Инфра-настройки n8n на Railway (важно!):**
- `GENERIC_TIMEZONE=Europe/Moscow`, `TZ=Europe/Moscow` — иначе Schedule-триггеры
  считают время в UTC и шлют дайджесты со смещением.
- Persistent volume на mount path **`/data`** (не `/home/node/.n8n` — Railway
  монтирует volume под root, а n8n работает под `node`, поэтому нужен
  `N8N_USER_FOLDER=/data` и volume на `/data`). Иначе при рестарте — EACCES
  permission denied на config.

**Готово в репо, ждёт ручной активации Алёной:**
- `n8n_workflows/morning-digest_v2.json` — обновлённый утренний дайджест
  с FS-блоком и целями КБЖУ. Импорт через n8n UI.
- `n8n_workflows/Weekly-digest_v2.json` — воскресный итог с FS.
- `n8n_workflows/bot-reminder-writer_v2_INSTRUCTIONS.md` — пошаговая
  UI-инструкция как добавить ветку `/goal` в существующий
  bot-reminder-writer (без переимпорта, чтобы не убить Telegram webhook).
- `scripts/init_nutrition_goals_sheet.py` — одной командой создаёт
  вкладку `nutrition_goals` (date_set, kcal, protein_g, fat_g, carbs_g, source).

**Грабли в эту сессию:**
- FatSecret URL `Diary.aspx?pa=fjrd` — это My Fatsecret feed, а не дневник.
  Настоящий дневник по `Diary.aspx?pa=fj`.
- FS Diary HTML парсится через title-атрибуты `<td title="Total Breakfast Fat: 15.69g">` —
  это надёжнее, чем угадывать порядок колонок.
- Selenium на GH Actions ставит Chrome через `browser-actions/setup-chrome@v1`,
  для логина нужны cookies в Secret (CAPTCHA на CI пройти нельзя).
- Persistent Chrome profile иногда залочен SingletonLock — фикс через
  автоудаление этих файлов в `make_driver`.
- Railway: при правке env vars сервис делает redeploy, и если volume
  привязан неправильно — n8n стартует с пустой базой и просит создать owner.
- Railway volumes можно создавать только на новый mount path, существующий
  редактировать нельзя. Mount path должен быть `/data` для n8n (не
  `/home/node/.n8n`), иначе EACCES.

**Осталось по плану:**
- ⏳ Восстановить n8n после рестарта Railway (создать owner, импортировать
  4 workflow, восстановить 3 credentials).
- ⏳ Активировать `/goal` в bot-reminder-writer по `INSTRUCTIONS.md`.
- ⏳ Доделка дублей в gcal-sync (appendOrUpdate вместо append).
- ⏳ Финальный отчёт + закрытие проекта.

## Правила работы

- Ничего не удалять без подтверждения.
- Отчёты сохранять в `reports/` с датой.
- Язык общения и комментариев в коде: русский.
- Секреты (`.env`, `.secrets/`, JSON-ключи) — никогда не коммитить.
