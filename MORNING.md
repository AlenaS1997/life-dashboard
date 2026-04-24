# Возвращаемся к дашборду — чек-лист

Пока ты отсутствовала, я сделал:

- `dashboard/` — MVP веб-дашборда (одна HTML-страница + manifest + иконка, всё под iPhone).
- `n8n/` — готовый workflow для утреннего Telegram-дайджеста (импортишь позже).
- В `scripts/garmin_sync.py` — добавил кэш сессии garth, чтобы не логиниться в Garmin каждый раз и не ловить 429.
- В `.github/workflows/garmin-sync.yml` — добавил `actions/cache` для этих же токенов.

Ничего секретного не коммитил — проверь, если хочешь: `git status` покажет только код, без `.env` и `.secrets/`.

## Что делаем сегодня (по шагам)

### Шаг 1 — докрутить Garmin → Sheets (5–10 минут)

Попробуй ещё раз на Mac:

```bash
cd ~/Desktop/LifeDashboard
python3.11 scripts/garmin_sync.py
```

Теперь скрипт сначала пытается восстановить сессию из `.secrets/garth/`. В первый запуск токенов там нет — сделает полный логин и сохранит. Со второго запуска логин будет пропущен (Garmin перестанет злиться).

Если всё ок — в таблице `garmin_daily` появилась новая строка. Напиши мне «Garmin пишет» и переходим к шагу 2.

Если по-прежнему 429 — значит у IP твоего Mac кулдаун, подожди 1–2 часа. Либо сразу едем в GitHub Actions (шаг 2), оттуда IP другой.

### Шаг 2 — GitHub Actions (автозапуск)

1. Создай публичный репозиторий `life-dashboard` (или любое имя) на GitHub.
2. Напиши мне username, и я дам точные команды `git init / git remote add / git push`.
3. В репо: `Settings → Secrets and variables → Actions → New secret`. Добавь пять секретов:

   | Имя | Откуда взять |
   |-----|--------------|
   | `GARMIN_EMAIL` | из `.env` |
   | `GARMIN_PASSWORD` | из `.env` |
   | `GOOGLE_SHEET_ID` | `1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE` |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | всё содержимое `.secrets/service-account.json` (копировать как текст) |
   | `GARMIN_WORKSHEET_NAME` | `garmin_daily` |

4. `Actions → Garmin → Google Sheets sync → Run workflow`. Через минуту должна появиться новая строка в таблице.

### Шаг 3 — опубликовать дашборд (5 минут)

1. В таблице `Life Dashboard`: `Share → Anyone with the link: Viewer → Done`. Это нужно, чтобы дашборд мог читать CSV. Никаких секретов там нет — просто сухие цифры.
2. Локально проверь, что дашборд работает: `cd dashboard && python3 -m http.server 8000`, открой `http://localhost:8000` в Safari. Увидишь реальные цифры вместо demo.
3. Когда понравится — скажи мне «деплоим», и я дам команды на пуш dashboard-папки на GitHub Pages.

### Шаг 4 — iPhone

Когда дашборд задеплоен:

1. Открой URL в Safari на iPhone.
2. «Поделиться» → «На экран «Домой»» → имя «Life».
3. Запусти с домашнего — выглядит как нативное приложение.

## Что не твоё

Настройка n8n/Telegram-бота (Дни 5–6) — я дам пошаговую инструкцию ближе к пятнице. Файлы уже лежат в `n8n/`, импортировать будешь одной кнопкой.

## Если что-то не так

Скидывай последние 20–30 строк вывода терминала (или скрин ошибки). Логи в `reports/garmin_YYYY-MM-DD.log`.
