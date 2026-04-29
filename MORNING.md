# Чек-лист — где мы и что осталось

После долгой совместной сессии 28–29 апреля ситуация поменялась
кардинально. Этот файл — актуальный статус и что делать дальше.

## Что работает прямо сейчас ✅

- **Garmin → Sheets** — GitHub Actions cron каждый день 08:05 МСК.
- **Дашборд** на `https://alenas1997.github.io/life-dashboard/` — все
  карточки, тренды vs прошлая неделя, heatmap сна, цветовая индикация,
  pull-to-refresh. **Без погоды** (убрали по запросу).
- **n8n на Railway** — поднят с persistent volume + правильным OAuth
  callback URL. Базовая инфра больше не слетит при рестартах.
- **Google Calendar → Sheets через n8n** — workflow `gcal-sync`
  опубликован, тянет события из календаря Fluffy в `gcal_events`,
  каждый день 08:00 МСК. Make.com можно отключить.

## Изменения которые я сделал в эту ночную сессию (не запушены!)

1. **Дашборд:** убрал блок «События дня» (дублировал Google Calendar
   на iPhone), на их место добавил:
   - **Композитный score** — общая оценка дня 0–100 с разбивкой по
     метрикам (вес: sleep_score 0.35, hrv 0.25, stress 0.20, BB min 0.20).
     Цветовая разбивка по каждой метрике.
   - **Серии (streaks)** — список streak'ов ≥3 дней: «🟢 сон ≥7 ч 4 дн.»,
     «🔴 HRV <30 5 дн.» и т.п. Если серий нет — «копим».
2. Service Worker bumpнут до **v5** — старый кэш чистится при первой
   загрузке.
3. Подготовлен каркас `scripts/fatsecret_sync.py` (см. ниже).

## Шаг 1 — запуш правок (1 мин)

```bash
cd ~/Desktop/LifeDashboard
git add -A
git commit -m "Дашборд: убрать события + добавить score и streaks; каркас FS"
git push
```

Pages передеплоится за ~30 сек, новый дашборд появится.

## Шаг 2 — отключить Make.com (30 сек)

Открой [Make](https://eu1.make.com) → сценарий «Integration Google
Calendar» → тумблер **Active → OFF**. Больше не нужен — события идут
через n8n без лимитов.

## Шаг 3 — Telegram-бот (30–40 мин активной работы)

Финальный большой кусок. Делаешь когда есть силы.

### 3.1 BotFather (3 мин)
1. В Telegram открой `@BotFather`.
2. `/newbot` → имя `Life Dashboard` → username вида `@alena_life_bot`.
3. **Сохрани токен** вида `1234:ABC...`.
4. **Жми Start у своего бота в Telegram** (без этого он не может писать
   тебе в личку).

### 3.2 chat_id (1 мин)
1. В Telegram открой `@userinfobot` → Start.
2. Сохрани число `Id: 123456789`.

### 3.3 Anthropic API key (5 мин)
1. https://console.anthropic.com/ → залогинься.
2. **Plans & Billing** → добавь карту → закинь $5 кредитов.
3. **API Keys** → Create Key → имя `Life Dashboard n8n` → сохрани
   `sk-ant-...`.

### 3.4 n8n credentials (5 мин)
В n8n → **Credentials** → **+ Create Credential** дважды:

**Telegram API:**
- `Access Token`: токен от BotFather.
- Имя: `Life Dashboard Bot`.

**Header Auth:**
- `Name` (имя credential): `Anthropic x-api-key`.
- `Header Name`: `x-api-key`.
- `Header Value`: `sk-ant-...`.

### 3.5 Импорт workflow (5 мин)
1. **Workflows → + → Import from File** →
   `Desktop/LifeDashboard/n8n/morning-digest-workflow.json`.
2. **На двух нодах с ⚠️** (Claude / Telegram) подвяжи credentials:
   - `Claude: разбор` → выбери `Anthropic x-api-key`.
   - `Отправить в Telegram` → выбери `Life Dashboard Bot`.
3. Открой ноду **Конфиг** → поле `telegram_chat_id` → подставь свой
   chat_id из 3.2.
4. Открой ноду **Календарь за 7 дней + сегодня** → подвяжи credential
   `Google Calendar (Fluffy)` (тот что уже создан для gcal-sync).
5. Сохрани (Cmd+S).

### 3.6 Тест (2 мин)
1. **Execute workflow** — все 8 нод должны позеленеть.
2. В Telegram должен прийти дайджест от твоего бота.
3. Если не пришёл — открой **Executions** → последний run → найди
   красную ноду → пришли скрин.

### 3.7 Активация (1 мин)
**Publish** в правом верхнем углу. Каждое утро 08:30 МСК будет приходить
дайджест.

### 3.8 Аналогично — weekly-digest (опц., 5 мин)
То же самое для `weekly-digest-workflow.json` — будет приходить каждое
воскресенье 19:00 МСК с недельным разбором.

## Шаг 4 — FatSecret (отдельная задача, 1.5–3 часа)

Сейчас у тебя есть только аккаунт в **мобильном приложении** FS.
Для API нужен **отдельный developer account** на
[platform.fatsecret.com](https://platform.fatsecret.com) — это другая
система, твой пароль от приложения там не подойдёт.

Что делать (когда созреешь):

1. Зарегистрироваться на platform.fatsecret.com (бесплатно, можно тот же
   email).
2. **Проверить:** дают ли food diary endpoints на free tier, или нужен
   Premier API ($10–20/мес). Если нужен Premier — решить, готова
   платить или нет.
3. Создать API application → получить **Consumer Key + Consumer Secret**.
4. Заполнить в `.env`:
   ```
   FATSECRET_CONSUMER_KEY=...
   FATSECRET_CONSUMER_SECRET=...
   ```
5. Запустить `python3.11 scripts/fatsecret_auth.py` — он проведёт через
   OAuth 1.0a flow, сохранит твой user-токен в `.secrets/fatsecret_token.json`.
6. Запустить `python3.11 scripts/fatsecret_sync.py` — потянет diary за
   вчера в Sheets вкладку `fatsecret_daily`.
7. Добавить в GitHub Actions workflow `.github/workflows/fatsecret-sync.yml`
   (cron 08:10 МСК).
8. Обновить дашборд — добавить блок калории/БЖУ.
9. Обновить morning-digest payload — Claude начнёт включать питание
   в анализ.

Скрипт-заглушка лежит готовая в `scripts/fatsecret_sync.py` — со всеми
TODO-блоками и комментариями. Когда будут API keys — заполню логику
до конца.

## Если что-то сломалось

| Симптом | Что делать |
|---------|-----------|
| Дашборд показывает старую версию (есть погода) | Cmd+Shift+R на десктопе; на iPhone закрой Safari полностью |
| n8n: «Application failed to respond» | Railway сервис падает. Открой Deployments → логи → пришли скрин |
| n8n: Telegram credential «chat not found» | Не нажала Start у своего бота в Telegram |
| n8n: Anthropic 401 | Неправильный API key в Header Auth credential |
| n8n: Anthropic 529/429 | Перегрузка Anthropic, retry уже встроен (3 попытки) |
| Дашборд показывает «Sheets закрыт» | Открой таблицу → Share → Anyone with link: Viewer |

## Контекст и история

- Полный статус — `CLAUDE.md`.
- Прошлый отчёт — `reports/2026-04-27-day3.md`.
- Сегодняшний (29 апреля) — `reports/2026-04-29-day4.md` (создам после
  завершения работы Telegram).
