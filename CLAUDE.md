# Life Dashboard — контекст проекта

## Цель
Оцифровать жизнь Алёны: сон, питание, активность, восстановление.
Результат — iPhone-дашборд + утренний Telegram-дайджест с инсайтами от Claude.

Данные → Google Sheets ID: `1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE`

## Источники данных

| Источник | Метрики | Статус |
|----------|---------|--------|
| Garmin | Сон, HRV, шаги, стресс, Body Battery, фазы сна, отбой/подъём, вес | ✅ GitHub Actions cron **10:30 МСК** (Михаил может спать до 10, sync захватывает свежий сон). `garmin_sync.py`: сон и HRV берутся за `target_date+1` (ночь target → след. день — то, что человек ассоциирует с «сон за вчера»). Флаги `--days N` / `--overwrite`. |
| Google Calendar (Fluffy) | События дня | ✅ n8n workflow `gcal-sync`, cron 08:00 МСК. Тянет из календаря `Fluffyismylifemoscow@gmail.com` (расшарен с основным аккаунтом). Make.com отключён. |
| FatSecret | Питание (калории, БЖУ) | ✅ Web-scraper `scripts/fatsecret_scraper.py` парсит Diary.aspx?pa=fj через Selenium. GitHub Actions cron **07:00 МСК** (`.github/workflows/fatsecret-sync.yml`) — парсит вчерашний день, к утреннему дайджесту данные готовы. CI логинится через cookies из секрета `FATSECRET_COOKIES_JSON`. |
| Whoop | Восстановление | Не подключён (опционально) |

## Инфраструктура

- **Make.com**: отключён (старый сценарий Google Calendar, упёрся в лимит ops).
- **n8n**: `https://n8n-production-e175.up.railway.app` на Railway.
  - **База — PostgreSQL** (отдельный сервис в Railway-проекте). SQLite на volume отказались: при каждом передеплое n8n volume отваливался и база терялась. С Postgres база не зависит от передеплоев. Подключение через env vars `DB_TYPE=postgresdb` + `DB_POSTGRESDB_*=${{Postgres.PG*}}`.
  - **Сборка из кастомного Dockerfile** (в корне репо). Railway Source = GitHub repo `alenas1997/life-dashboard`. Dockerfile запускает n8n под root — обходит EACCES на Railway-volume. ВНИМАНИЕ: каждый push в репо передеплоивает n8n (но база в Postgres, не теряется).
  - Env vars: `GENERIC_TIMEZONE=Europe/Moscow`, `TZ=Europe/Moscow` (n8n считает всё время в МСК), `N8N_HOST`, `N8N_PROTOCOL=https`, `WEBHOOK_URL`, `N8N_EDITOR_BASE_URL`.
  - **4 workflow, все Published:**
    - `gcal-sync` — cron 08:00 МСК.
    - `morning-digest v2` — cron `0 11 * * *` (11:00 МСК — после пробуждения Михаила).
    - `Weekly-digest v2` — cron `0 19 * * 0` (вс 19:00 МСК).
    - `bot-reminder-writer v2` — Telegram Trigger: напоминания + `/goal` + whitelist по chat_id.
- **Railway**: оплачен Hobby ($5/мес).
- **GitHub Actions**: три workflow в `.github/workflows/`:
  - `garmin-sync.yml` — cron 10:30 МСК (`30 7 * * *` UTC).
  - `fatsecret-sync.yml` — cron 07:00 МСК (`0 4 * * *` UTC).
  - `pages.yml` — деплой `dashboard/` на Pages при пуше.
- **Google Cloud**: проект `life-dashboard-494212`.
  - Service account `life-dashboard-writer@...` — JSON-ключ `.secrets/service-account.json` (в `.gitignore`). Используется в Garmin sync и как credential Google Sheets в n8n.
  - OAuth client «n8n life dashboard» — для Google Calendar credential в n8n.

### ВАЖНО про время (история граблей)
n8n-инстанс работает в `Europe/Moscow` (через `GENERIC_TIMEZONE`). Поэтому **все cron-выражения в Schedule-нодах пишутся прямо в МСК-времени**, без пересчёта в UTC. `30 8 * * *` = 08:30 МСК. GitHub Actions, наоборот, всегда UTC — там cron в UTC (07:00 МСК = `0 4 * * *`).

## Дашборд

- AppSheet отклонён (не красиво).
- Решение: **кастомный HTML-дашборд**, открывается в Safari на iPhone, добавляется на домашний экран как PWA.
- Чтение данных — через публичный CSV-экспорт Google Sheets (без auth для read-only).
- Деплой: GitHub Pages (публичный репо без чувствительных данных) или Cloudflare Pages (если приватный).

## Текущее состояние — проект завершён (2026-05-21)

**Всё работает в продакшене:**
- `garmin_sync.py` (GH Actions, 10:30 МСК): сон, HRV, шаги, стресс, BB, фазы сна,
  отбой/подъём, вес. Сон и HRV берутся за `target_date+1` (ночь, относящаяся к
  «вчерашнему дню» в человеческом понимании: лёг вчера, проснулся сегодня).
  Авто-расширение шапки `garmin_daily`. Флаги `--days N` / `--overwrite`.
- `fatsecret_scraper.py` (GH Actions, 07:00 МСК): питание → `fatsecret_daily`.
- n8n `gcal-sync` (08:00 МСК): события Fluffy → `gcal_events`. Google Sheets
  через Service Account, Calendar через OAuth.
- n8n `morning-digest v2` (11:00 МСК) и `Weekly-digest v2` (вс 19:00 МСК):
  дайджесты в Telegram с разбором от Claude, блок питания, цели КБЖУ.
- n8n `bot-reminder-writer v2`: бот `@ms_life_dashboard_bot` принимает
  напоминания свободным текстом, команду `/goal`, фильтрует по whitelist chat_id.
- Дашборд https://alenas1997.github.io/life-dashboard/ — PWA, password-gate
  (пароль хранится как SHA-256). Блоки: Сегодня, Тренды 7 дней (tap по точкам),
  Питание вчера, Неделя превышений нормы, Вес (спарклайн + детали),
  Сон heatmap 14/30 дней (календарь), Фазы сна 7 дней, Композитный score, Серии.
- Service Worker v19, авто-обновление (`updateViaCache:none` + controllerchange).

**Ключевые файлы:**
- `Dockerfile` — кастомный образ n8n для Railway (запуск под root).
- `n8n_workflows/*.json` — актуальные версии всех 4 workflow.
- `scripts/init_nutrition_goals_sheet.py` — создание вкладки `nutrition_goals`.

**Грабли проекта (на будущее):**
- FatSecret: настоящий дневник по `Diary.aspx?pa=fj` (не `pa=fjrd` — это feed).
  Парсится через title-атрибуты `<td title="Total Breakfast Fat: 15.69g">`.
- Railway + n8n + volume = ненадёжно: volume отваливался при передеплоях,
  база терялась 3 раза. Решение — Postgres (отдельный сервис).
- Railway монтирует volume под root → n8n под `node` падает с EACCES.
  Обход — кастомный Dockerfile с запуском под root.
- n8n в `Europe/Moscow`: cron пишется в МСК, не в UTC. GitHub Actions — в UTC.
- Header Auth credential: поле Name = имя HTTP-заголовка (`x-api-key`),
  не название credential. Пробел/неверное имя → `ERR_INVALID_HTTP_TOKEN`.
- Google Sheets OAuth в n8n не видит список файлов (нет Drive scope) —
  используем Service Account.

**Возможные доработки (не критично, на будущее):**
- Дубли в gcal-sync (appendOrUpdate вместо append).
- Whoop-интеграция (восстановление).
- Cloudflare Access для дашборда вместо password-gate (если нужна строгая защита).

## Правила работы

- Ничего не удалять без подтверждения.
- Отчёты сохранять в `reports/` с датой.
- Язык общения и комментариев в коде: русский.
- Секреты (`.env`, `.secrets/`, JSON-ключи) — никогда не коммитить.
