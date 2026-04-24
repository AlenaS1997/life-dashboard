# n8n: утренний Telegram-дайджест

Workflow для n8n, который каждое утро в 08:30 МСК:

1. Читает Google Sheets (вкладки `garmin_daily` и `gcal_events`) через публичный gviz CSV.
2. Формирует контекст: последняя запись + средние за 7 дней + события на сегодня.
3. Просит Claude Sonnet 4.6 написать короткий тёплый дайджест на русском.
4. Отправляет в Telegram.

Никаких лишних зависимостей — всё через встроенные ноды n8n.

## Когда импортировать

На Дни 5–6 по плану. До этого момента можно просто держать файл в репо.

## Импорт в n8n

1. Открой `https://n8n-production-e175.up.railway.app`.
2. Workflows → `+` → `Import from file` → выбери `morning-digest-workflow.json`.

## Настройка (три вещи)

### 1. Telegram-бот

1. В Telegram открой `@BotFather`, команда `/newbot`, назови, например, `Life Dashboard Bot`.
2. BotFather выдаст токен вида `123456:ABC-DEF...`.
3. В Telegram открой `@userinfobot`, он покажет твой `chat_id` (число).
4. В n8n: Credentials → `+` → `Telegram API` → вставь токен. Назови `Life Dashboard Bot`.
5. В workflow: открой ноду `Конфиг`, поставь свой `chat_id` в поле `telegram_chat_id`.
6. Открой ноду `Отправить в Telegram` → выбери только что созданный credential.

Первый раз напиши боту `/start` в Telegram — иначе он не сможет писать тебе в личку.

### 2. Anthropic API-ключ

1. На `https://console.anthropic.com/` → API Keys → Create Key.
2. В n8n: Credentials → `+` → `Header Auth`:
   - Name: `Anthropic x-api-key`
   - Header name: `x-api-key`
   - Header value: твой `sk-ant-...`
3. В ноде `Claude: сочиняет дайджест` → Credentials → выбери `Anthropic x-api-key`.

### 3. Google Sheets — публичный доступ на чтение

Шаг уже должен быть сделан для дашборда (`dashboard/README.md`):
`Share` → `Anyone with the link: Viewer`.

Если таблица приватная — gviz CSV вернёт HTML логина, и парсер ничего не найдёт.

## Тест

1. В workflow нажми `Execute workflow` (правый верхний угол).
2. Через 5–10 секунд бот пришлёт сообщение в Telegram.
3. Если не пришло — открой последнее выполнение в `Executions`, посмотри, на каком шаге ошибка.
   - `Тянем Garmin CSV` пустой → таблица не публичная.
   - `Claude` — 401 → неправильный API-ключ.
   - `Telegram` — 400 `chat not found` → ты ещё не писал боту `/start`.

## Активация

После успешного теста: `Active` (тумблер справа вверху) → ON. Теперь дайджест будет приходить каждое утро в 08:30 МСК.

## Изменение промпта

Промпт (`system` в ноде Claude) вынесен в `claude-prompt.md` — отредактируй там и скопируй сюда,
чтобы не терять историю правок в git.

## Что дальше

- Добавить погоду: HTTP Request к OpenWeather после «Собираем контекст», вложить результат в prompt.
- Связать с дашбордом: в конец дайджеста подкладывать ссылку `https://<username>.github.io/life-dashboard-web/`.
- Недельный срез по воскресеньям: второй workflow, другой prompt, агрегаты за 7 дней.
