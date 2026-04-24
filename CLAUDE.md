# Life Dashboard — контекст проекта

## Цель
Оцифровать жизнь Алёны: сон, питание, активность, восстановление.
Результат — iPhone-дашборд + утренний Telegram-дайджест с инсайтами от Claude.

Данные → Google Sheets ID: `1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE`

## Источники данных

| Источник | Метрики | Статус |
|----------|---------|--------|
| Garmin | Сон, HRV, шаги, стресс, Body Battery | Скрипт готов, живёт в Sheets, кэш сессии через garth |
| Google Calendar | События дня | ✅ Работает через Make.com daily 08:00 |
| FatSecret | Питание (калории, БЖУ) | Ожидаем доступ (пароль) |
| Whoop | Восстановление | Не подключён (опционально) |

## Инфраструктура

- **Make.com**: Google Calendar → Sheets (daily 08:00). Работает.
- **n8n**: `https://n8n-production-e175.up.railway.app` — готов для Telegram-бота и Claude-интеграции.
- **GitHub Actions**: workflow `.github/workflows/garmin-sync.yml` готов, cron 08:05 МСК. Нужен пуш в репо + секреты.
- **Google Cloud**: проект `life-dashboard-494212` (номер `1095452022430`).
  - Service account: `life-dashboard-writer@life-dashboard-494212.iam.gserviceaccount.com`
  - JSON-ключ: `.secrets/service-account.json` (в `.gitignore`)

## Дашборд

- AppSheet отклонён (не красиво).
- Решение: **кастомный HTML-дашборд**, открывается в Safari на iPhone, добавляется на домашний экран как PWA.
- Чтение данных — через публичный CSV-экспорт Google Sheets (без auth для read-only).
- Деплой: GitHub Pages (публичный репо без чувствительных данных) или Cloudflare Pages (если приватный).

## Текущее состояние (по состоянию на 2026-04-24 день)

**Сделано:**
- Структура папки: `scripts/`, `dashboard/`, `n8n/`, `data/`, `reports/`, `.secrets/`, `.github/workflows/`.
- `.env`, `.gitignore`, `.env.example`, `requirements.txt` — готовы.
- `scripts/garmin_sync.py`:
  - бэкофф на 429, логирование, правильные эндпоинты для HRV и Body Battery;
  - идемпотентная запись в Sheets (row 1 как source-of-truth для порядка колонок);
  - кэш сессии garth в `.secrets/garth/` — пропускает логин, если oauth-токены валидны.
- Service account создан, Sheets/Drive API включены, JSON в `.secrets/service-account.json`.
- Python 3.11 через Homebrew. Dry-run + первый live-run прошли (HRV/BB живые).
- `.github/workflows/garmin-sync.yml` — cron 08:05 МСК + `actions/cache` на garth-токены.
- `dashboard/` — HTML MVP под iPhone (тёмная тема, gviz CSV, mock-fallback, PWA-манифест, SVG-иконка).
- `n8n/morning-digest-workflow.json` + `claude-prompt.md` + `README.md` — каркас Telegram-бота к импорту.

**Следующий шаг для Алёны (`MORNING.md`):**
1. Прогнать `python3.11 scripts/garmin_sync.py` на Mac — проверить кэш сессии (вторая попытка должна идти без логина).
2. Создать публичный GitHub-репо, дать username → запушить код, добавить 5 секретов, прогнать workflow.
3. `Share → Anyone with link: Viewer` на Sheets → проверить дашборд локально → деплой на GitHub Pages → iPhone home screen.
4. В Дни 5–6 — импорт `n8n/morning-digest-workflow.json`, подключить Telegram Bot + Anthropic API key.

**Осталось по плану на неделю:**
- Дни 2–3 (сегодня–завтра): деплой дашборда на GitHub Pages + iPhone.
- День 4: полировка (погода, ссылка на дашборд в дайджесте).
- Дни 5–6: активация Telegram-бота + подкрутка промпта.
- День 7: FatSecret или полировка.

## Правила работы

- Ничего не удалять без подтверждения.
- Отчёты сохранять в `reports/` с датой.
- Язык общения и комментариев в коде: русский.
- Секреты (`.env`, `.secrets/`, JSON-ключи) — никогда не коммитить.
