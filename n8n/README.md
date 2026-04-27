# n8n: workflow-файлы

В папке три workflow-файла:

| Файл | Когда | Что делает |
|------|-------|-----------|
| `gcal-sync-workflow.json` | Каждый день 08:00 МСК | Синхронизирует события Google Calendar на сегодня в `gcal_events`. Заменяет старый Make.com сценарий — без лимитов, без дублей, идемпотентно (Clear → Append). |
| `morning-digest-workflow.json` | Каждое утро 08:30 МСК | Короткий тёплый дайджест: вчерашний сон/HRV/шаги/стресс + события дня + один инсайт. |
| `weekly-digest-workflow.json` | Каждое воскресенье 19:00 МСК | Итог недели: что улучшилось, что просело, лучший день, фокус на следующую неделю. |

Все workflow — на встроенных нодах n8n. Никаких сторонних community-нод.

## gcal-sync — отдельная инструкция

Этот workflow заменяет Make.com-сценарий «Integration Google Calendar», который упирался в лимит 1000 операций/мес на бесплатном плане. n8n у тебя на Railway — без лимитов.

### Импорт и настройка (один раз)

1. **Импортируй файл.** В n8n: Workflows → `+` → `Import from file` → `gcal-sync-workflow.json`.
2. **Создай Google credential.** Credentials → `+` → `Google Calendar OAuth2 API` → Sign in with Google → разреши доступ к Calendar и Sheets (n8n спросит оба scope). Назови, например, `Google (Алёна)`. Этот же credential подойдёт и для Google Sheets-нод — n8n сам подхватит.
3. **Подставь credential в три ноды:**
   - `Получить события дня` (Google Calendar)
   - `Очистить gcal_events (кроме заголовка)` (Google Sheets)
   - `Append в gcal_events` (Google Sheets)
4. **Проверь конфиг.** Открой ноду `Конфиг`:
   - `sheet_id` — уже подставлен (`1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE`).
   - `events_tab` — `gcal_events`.
   - `calendar_id` — `savchenko.alena.27071997@gmail.com`. Если хочешь брать события всех календарей — поменяй на `primary`.
5. **Тест.** Жми «Execute workflow» (правый верхний). Все ноды должны стать зелёными. В Sheets вкладка `gcal_events` обновится: только заголовок + сегодняшние события.
6. **Active.** Тумблер ON в верхнем правом углу.
7. **Отключи Make.** В Make.com открой сценарий «Integration Google Calendar» → тумблер Active → OFF. Чтобы зря не тратил оставшиеся операции.

### Логика workflow

```
Schedule 08:00 МСК
  ↓
Конфиг (sheet_id, calendar_id, events_tab)
  ↓
Получить события дня
  (Google Calendar, singleEvents=true, диапазон [00:00; 23:59] сегодня)
  ↓
Маппим в строки таблицы
  (Code: date, event_title, start_time, end_time, calendar)
  ↓
Очистить gcal_events кроме заголовка
  (Google Sheets clear, строки 2..5001)
  ↓
Есть ли события?
  (IF: если 0 событий — append пропускаем)
  ↓ (если да)
Append в gcal_events
  (Google Sheets append)
```

### Почему дублей теперь не будет

- **`singleEvents: true`** — повторяющиеся события (Подъём, Зал, Дорога) раскрываются в индивидуальные экземпляры на сегодня. Make при `singleEvents: false` этого не делал, поэтому таблица была пустой.
- **Сначала Clear, потом Append** — таблица всегда содержит **ровно сегодняшние события**. Сколько бы раз ни запустил вручную — дублей быть не может в принципе.
- **Guard на пустой массив** — если на сегодня событий нет, append пропускаем, таблица остаётся с одним заголовком, дашборд корректно покажет «На сегодня событий нет».
- **Retry на сеть** — все три HTTP-ноды с `retryOnFail: true, maxTries: 3`. Кратковременные сбои Google API не убивают синк.

---

## Telegram-дайджесты — настройка

## Когда импортировать

На Дни 5–6 по плану. До этого момента можно просто держать файлы в репо.

## Импорт в n8n

1. Открой `https://n8n-production-e175.up.railway.app`.
2. Workflows → `+` → `Import from file`.
3. Импортируй сначала `morning-digest-workflow.json`, потом `weekly-digest-workflow.json`.

## Настройка (три вещи, общие для обоих workflow)

### 1. Telegram-бот

1. В Telegram открой `@BotFather`, команда `/newbot`, назови, например, `Life Dashboard Bot`.
2. BotFather выдаст токен вида `123456:ABC-DEF...`.
3. В Telegram открой `@userinfobot`, он покажет твой `chat_id` (число).
4. В n8n: Credentials → `+` → `Telegram API` → вставь токен. Назови `Life Dashboard Bot`.
5. В каждом workflow: открой ноду `Конфиг` → поставь свой `chat_id` в поле `telegram_chat_id`.
6. В ноде `Отправить в Telegram` → выбери только что созданный credential.

Первый раз напиши боту `/start` в Telegram — иначе он не сможет писать тебе в личку.

### 2. Anthropic API-ключ

1. На `https://console.anthropic.com/` → API Keys → Create Key.
2. В n8n: Credentials → `+` → `Header Auth`:
   - Name: `Anthropic x-api-key`
   - Header name: `x-api-key`
   - Header value: твой `sk-ant-...`
3. В нодах `Claude: ...` (в обоих workflow) → Credentials → выбери `Anthropic x-api-key`.

### 3. Google Sheets — публичный доступ на чтение

Шаг уже должен быть сделан для дашборда (`dashboard/README.md`):
`Share` → `Anyone with the link: Viewer`.

Если таблица приватная — gviz CSV вернёт HTML логина, и парсер ничего не найдёт.

## Надёжность (что встроено)

- **Retry на сеть.** Все HTTP-ноды (Garmin CSV, события, Claude) имеют `retryOnFail: true, maxTries: 3` с паузой 5–10 сек. Кратковременные сбои Anthropic / 429 не убивают дайджест.
- **Fallback при провале Claude.** Если все 3 попытки Anthropic-API провалились — Telegram-нода всё равно отправит сообщение, но с сырыми цифрами и пометкой `⚠️ Дайджест не сформирован`. Лучше «грубый дайджест», чем тишина в 8:30 утра.
- **continueOnFail на событиях.** Если Make.com не успел залить события дня — утренний дайджест всё равно уйдёт, просто без секции «События».

## Тест

1. В workflow нажми `Execute workflow` (правый верхний угол).
2. Через 5–10 секунд бот пришлёт сообщение в Telegram.
3. Если не пришло — открой последнее выполнение в `Executions`, посмотри, на каком шаге ошибка:
   - `Тянем Garmin CSV` пустой → таблица не публичная.
   - `Claude` — 401 → неправильный API-ключ.
   - `Claude` — 529 / 429 → сразу retry, дай n8n 30 секунд.
   - `Telegram` — 400 `chat not found` → ты ещё не писал боту `/start`.

## Активация

После успешного теста: `Active` (тумблер справа вверху) → ON.
- Утренний дайджест: каждый день 08:30 МСК.
- Недельный итог: каждое воскресенье 19:00 МСК.

## Изменение промпта

Промпты (`system` в нодах Claude) вынесены в `claude-prompt.md` (утренний) — отредактируй там и скопируй в JSON, чтобы не терять историю правок в git. Для weekly промпт пока живёт прямо в JSON; если будешь часто его править — вынеси в `claude-weekly-prompt.md` по аналогии.

## Что дальше

- Добавить погоду в утренний дайджест: HTTP Request к Open-Meteo после «Собираем контекст», вложить результат в prompt. Дашборд уже это умеет — можно скопировать URL.
- В конец дайджеста подкладывать ссылку на дашборд: `https://alenas1997.github.io/life-dashboard/`.
- Если будут дни без данных — добавить guard в Code-ноде, который пропустит запуск (вместо отправки пустого сообщения).
