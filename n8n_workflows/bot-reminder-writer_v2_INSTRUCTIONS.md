# Добавление `/goal` в bot-reminder-writer

## Зачем

Чтобы из Telegram-бота можно было задать целевые КБЖУ командой:

```
/goal kcal=1800 protein=120 fat=60 carbs=180
```

Бот сохранит цель в Sheets-вкладку `nutrition_goals`, и `morning-digest` / `weekly-digest` / дашборд начнут использовать её для блока «Питание».

Также поддерживаются:
- `/goal` — без аргументов → бот покажет текущую цель.
- `/goal help` — справка.

## Почему НЕ переимпорт

Импортировать обновлённый JSON для этого workflow нельзя — он переинициализирует Telegram webhook (n8n при импорте Telegram Trigger вызывает `setWebhook` у Telegram), и на старый бот придётся регистрировать заново. Поэтому **меняем существующий workflow через UI**, добавляя 5 нод.

## Предусловия

1. Лист `nutrition_goals` создан в Google Sheets — запусти:
   ```bash
   cd ~/Desktop/LifeDashboard
   python3.11 scripts/init_nutrition_goals_sheet.py
   ```
2. n8n работает и `bot-reminder-writer` активен.

## Что добавляем (схема)

Текущий поток:
```
Telegram Trigger → Конфиг → Claude (парсер reminder) → ... → Sheets append
```

Меняем на:
```
Telegram Trigger → Конфиг → IF (это /goal?)
                              ├── true  → Goal Parser (Code) → Goal Sheets append → Telegram reply
                              └── false → Claude (старый поток reminder)
```

Детали — ниже по шагам.

## Шаги в n8n UI

### Шаг 1. Открой workflow `bot-reminder-writer`

В n8n: Workflows → bot-reminder-writer → Open.

### Шаг 2. Удали соединение «Конфиг → Claude: парсит reminder»

Кликни на стрелку между нодами «Конфиг» и «Claude: парсит reminder». Нажми Delete (или клавишу Backspace). Стрелка исчезнет — Claude теперь не получает данные. Не пугайся, восстановим через IF.

### Шаг 3. Добавь IF-ноду

1. Кликни «+» на canvas (или правый клик → Add Node).
2. В поиске набери `If` → выбери ноду **If** (Core Nodes).
3. Назови её **«Команда /goal?»**.
4. Размести её между «Конфиг» и «Claude: парсит reminder» (визуально).
5. В её настройках:
   - **Conditions** → нажми «Add condition» → выбери тип **String**.
   - Value 1: `{{ $('Конфиг').item.json.user_text }}`
   - Operation: **Starts with**
   - Value 2: `/goal`
   - Включи **Case Sensitive: false** (или «Ignore Case»).
6. Save.

### Шаг 4. Соедини ноды через IF

1. От «Конфиг» проведи стрелку в **«Команда /goal?»** (input).
2. **False output** ноды IF (нижняя ветка) → соедини с **«Claude: парсит reminder»** (старая ветка reminder продолжает работать).
3. **True output** (верхняя ветка) → пока никуда, добавим Goal Parser ниже.

### Шаг 5. Добавь Code-ноду «Goal Parser»

1. Add Node → ищи **Code** → выбери **Code** (n8n-nodes-base.code).
2. Назови её **«Goal Parser»**.
3. В поле кода вставь:

```javascript
// Парсим команду /goal:
//   /goal kcal=1800 protein=120 fat=60 carbs=180   → save
//   /goal                                          → show
//   /goal help                                     → help
//
// Цели хранятся в листе nutrition_goals (date_set, kcal, protein_g, fat_g, carbs_g, source).

const text = ($('Конфиг').item.json.user_text || '').trim();
const chatId = $('Конфиг').item.json.chat_id;
const today = $('Конфиг').item.json.today_iso;

// Уберём префикс /goal (с возможным @bot_username)
const stripped = text.replace(/^\/goal(@\w+)?\s*/i, '').trim();

// help
if (/^help$/i.test(stripped)) {
  return [{ json: {
    action: 'reply_only',
    chat_id: chatId,
    reply_text: '🎯 *Цели КБЖУ*\n\n' +
      '`/goal kcal=1800 protein=120 fat=60 carbs=180` — задать цель\n' +
      '`/goal` — показать текущую\n' +
      '`/goal help` — это сообщение\n\n' +
      'Дайджест и дашборд будут сравнивать твоё реальное питание с этой целью.',
  }}];
}

// без аргументов → показать текущую (читаем последнюю строку из Sheets)
// Ноду Sheets read добавлять не будем для простоты — просто скажем «открой дашборд / Sheets»
if (!stripped) {
  return [{ json: {
    action: 'reply_only',
    chat_id: chatId,
    reply_text: '🎯 Текущая цель — на дашборде в блоке «Питание». Чтобы изменить:\n`/goal kcal=1800 protein=120 fat=60 carbs=180`',
  }}];
}

// парсим аргументы вида key=value через пробел
const args = {};
for (const pair of stripped.split(/\s+/)) {
  const m = pair.match(/^(\w+)=([\d.]+)$/);
  if (m) args[m[1].toLowerCase()] = parseFloat(m[2]);
}

const required = ['kcal', 'protein', 'fat', 'carbs'];
const missing = required.filter((k) => !isFinite(args[k]));
if (missing.length) {
  return [{ json: {
    action: 'reply_only',
    chat_id: chatId,
    reply_text: '⚠️ Не хватает полей: ' + missing.join(', ') +
      '\n\nПример: `/goal kcal=1800 protein=120 fat=60 carbs=180`',
  }}];
}

return [{ json: {
  action: 'add_goal',
  chat_id: chatId,
  reply_text: `✅ Цель сохранена:\n*${args.kcal} ккал · Б ${args.protein} / Ж ${args.fat} / У ${args.carbs}*\n\nДайджест начнёт сравнивать с этими числами с завтра.`,
  // Поля для Sheets autoMap (на верхнем уровне):
  date_set: today,
  kcal: args.kcal,
  protein_g: args.protein,
  fat_g: args.fat,
  carbs_g: args.carbs,
  source: 'telegram',
}}];
```

4. Save.
5. Соедини **True output** ноды «Команда /goal?» → input ноды «Goal Parser».

### Шаг 6. Добавь Google Sheets-ноду «Goal Sheets append»

1. Add Node → **Google Sheets** → операция **Append**.
2. Назови её **«Добавить в nutrition_goals»**.
3. Параметры:
   - **Document**: выбери ту же таблицу, что в существующей ноде «Добавить в health_reminders» (по ID `1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE`).
   - **Sheet**: `nutrition_goals`
   - **Mapping mode**: **Auto-Map Input Data to Columns** (как в существующей ноде).
4. **Credentials**: тот же `Google Sheets account`, что у соседней ноды.
5. В поле **Always Output Data**: оставь выкл, как у соседней ноды.
6. Save.
7. Соедини **Goal Parser → Goal Sheets append**. Но! Только если `action=add_goal`. Для этого добавь после Goal Parser маленькую Code-ноду **«Только если add_goal»** (по аналогии с существующей «Только если add_reminder»):

```javascript
const item = $input.first().json;
if (item && item.action === 'add_goal' && item.kcal) {
  return [{ json: item }];
}
return [];
```

Соединение: Goal Parser → Только если add_goal → Goal Sheets append.

### Шаг 7. Подключи ответ в Telegram

У тебя уже есть нода **«Ответить в Telegram»** в существующем потоке (после «Распарсить ответ Claude»). Туда же надо отправлять и из Goal Parser.

1. От ноды **«Goal Parser»** (output, т.е. напрямую, не через «Только если add_goal») проведи стрелку в существующую ноду **«Ответить в Telegram»**.

   Так Goal Parser отвечает в Telegram при любом исходе (help / show / valid / invalid), а в Sheets идёт только если `add_goal`.

### Шаг 8. Save и активация

1. Save (вверху страницы).
2. Toggle Active **off**, потом **on** — чтобы n8n пересобрал routing.
3. Проверка: открой Telegram, отправь боту:
   - `/goal help` → должна прийти справка.
   - `/goal kcal=1800 protein=120 fat=60 carbs=180` → должно прийти «✅ Цель сохранена».
4. Открой Google Sheets вкладку `nutrition_goals` — там должна появиться новая строка.

## Если что-то пошло не так

- **Бот молчит**: проверь, что **Active** включён, и нет красных индикаторов на нодах.
- **Reminder перестал работать**: проверь шаг 4 — False-output IF должен идти в «Claude: парсит reminder».
- **Цель не пишется в Sheets**: открой Executions, найди последний запуск, посмотри на ноде «Goal Sheets append» — какая ошибка.

## Финал

После этого:
- `/goal` работает.
- Старая логика напоминаний работает как раньше.
- Дайджесты (после импорта morning-digest_v2 и Weekly-digest_v2) используют свежую цель из `nutrition_goals`.
