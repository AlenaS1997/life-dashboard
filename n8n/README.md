# n8n: Telegram-дайджесты

В папке два workflow-файла:

| Файл | Когда | Что делает |
|------|-------|-----------|
| `morning-digest-workflow.json` | Каждое утро 08:30 МСК | Короткий тёплый дайджест: вчерашний сон/HRV/шаги/стресс + события дня + один инсайт. |
| `weekly-digest-workflow.json` | Каждое воскресенье 19:00 МСК | Итог недели: что улучшилось, что просело, лучший день, фокус на следующую неделю. |

Оба workflow — на встроенных нодах n8n (Schedule Trigger → Set → HTTP Request → Code → HTTP Request → Telegram). Никаких сторонних community-нод.

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
