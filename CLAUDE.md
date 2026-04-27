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

## Текущее состояние (по состоянию на 2026-04-28 утро)

**Сделано:**
- Структура папки: `scripts/`, `dashboard/`, `n8n/`, `data/`, `reports/`, `.secrets/`, `.github/workflows/`.
- `.env`, `.gitignore`, `.env.example`, `requirements.txt` — готовы.
- `scripts/garmin_sync.py`:
  - бэкофф на 429, логирование, правильные эндпоинты для HRV и Body Battery;
  - идемпотентная запись в Sheets (row 1 как source-of-truth для порядка колонок);
  - кэш сессии garth в `.secrets/garth/` через модульный `garth.resume()/save()` (с fallback’ами под разные версии библиотеки).
- Service account создан, Sheets/Drive API включены, JSON в `.secrets/service-account.json`.
- Python 3.11 через Homebrew. Live-run’ы стабильно проходят.
- **GitHub репо** `AlenaS1997/life-dashboard` (public) поднят, 5 секретов в Actions, токен PAT у Алёны в Mac keychain.
- **GitHub Actions cron** `garmin-sync.yml` — каждый день 08:05 МСК, `actions/cache` на garth-токены, успешные runs.
- **GitHub Pages** через отдельный workflow `pages.yml` — собирает `dashboard/` через `actions/upload-pages-artifact` + `actions/deploy-pages`. URL: `https://alenas1997.github.io/life-dashboard/`.
- **Дашборд `dashboard/index.html`** — iPhone-first, тёмная тема, гviz CSV, погода (Open-Meteo, без ключа), skeleton-лоадер, detect закрытой Sheets с понятным баннером, локаль-устойчивый парсер чисел, localStorage кэш.
- **Service Worker `dashboard/sw.js`** — offline-кэш статики и API (network-first для CSV/погоды, cache-first для статики).
- **n8n workflow’ы** — два файла:
  - `morning-digest-workflow.json` (cron 08:30 МСК) — retry на всех HTTP-нодах, fallback на сырые числа при провале Claude.
  - `weekly-digest-workflow.json` (cron вс 19:00 МСК) — недельный итог с агрегатами и сравнением с прошлой неделей.

**Следующий шаг для Алёны (`MORNING.md`):**
1. `git pull && git push` с Mac — мои ночные коммиты (`8abad9d`, `f943a08`) улетают на GitHub, Pages передеплоит автоматически.
2. Открыть дашборд https://alenas1997.github.io/life-dashboard/ — проверить погоду, баннер «Sheets закрыт» (если ещё не открыт).
3. Если Sheets закрыт — Share → Anyone with the link: Viewer.
4. Safari → Поделиться → На экран «Домой» — иконка на iPhone.
5. В Дни 5–6 — импорт `n8n/morning-digest-workflow.json` + `weekly-digest-workflow.json`, подключить Telegram Bot + Anthropic API key (по `n8n/README.md`).

**Осталось по плану на неделю:**
- ~~Дни 2–3: деплой дашборда + iPhone~~ — сделано (iPhone-добавление осталось одним кликом для Алёны).
- ~~День 4: полировка (погода, offline)~~ — сделано ночью с 27 на 28.
- Дни 5–6: активация Telegram-бота + Claude (файлы готовы, нужны только credentials).
- День 7: FatSecret или дополнительная полировка.

## Правила работы

- Ничего не удалять без подтверждения.
- Отчёты сохранять в `reports/` с датой.
- Язык общения и комментариев в коде: русский.
- Секреты (`.env`, `.secrets/`, JSON-ключи) — никогда не коммитить.
