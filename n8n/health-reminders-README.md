# Health Reminders — напоминания по здоровью в Telegram

Workflow `health-reminders-workflow.json` — Sheets-driven система
напоминаний. Каждый день в 09:00 МСК читает вкладку `health_reminders`
в твоей таблице, отправляет в Telegram все reminder'ы с
`next_date <= сегодня`, обновляет `next_date` на следующее значение
по `frequency`.

**Главный плюс:** добавлять новые reminder'ы → просто новая строка
в Google Sheets, без захода в n8n.

## Schema вкладки `health_reminders`

Создай новую вкладку в [таблице](https://docs.google.com/spreadsheets/d/1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE/edit)
с именем `health_reminders` и заголовком в первой строке:

| reminder_id | title | description | next_date | frequency | enabled | last_sent |
|-------------|-------|-------------|-----------|-----------|---------|-----------|

### Что значат колонки

- **reminder_id** — уникальный id (любая строка). Используется n8n чтобы
  обновлять конкретную строку. Примеры: `weight`, `blood_test`, `dentist`.
  ⚠️ Не повторяться.
- **title** — что напомнить. Появится жирным в Telegram. Примеры:
  «Взвеситься», «Сдать общий анализ крови», «Записаться к зубному».
- **description** — (опционально) дополнительный текст для контекста.
  «Натощак, до завтрака», «Не забудь талон записи».
- **next_date** — дата следующего срабатывания в формате `YYYY-MM-DD`.
  Например `2026-05-05`. Когда наступит — workflow отправит и
  пересчитает.
- **frequency** — как часто повторять:
  - `once` — один раз, после отправки `enabled` станет `FALSE`.
  - `daily` — каждый день.
  - `weekly` — каждую неделю.
  - `monthly` — раз в 30 дней.
  - `yearly` — раз в год.
  - **Число** (например `14`) — раз в N дней.
- **enabled** — `TRUE` чтобы reminder работал, `FALSE` чтобы выключить
  (или после `once` workflow сам поставит FALSE).
- **last_sent** — дата последней отправки (заполняется автоматически).
  Можешь оставить пустым при создании.

### Примеры начальных reminder'ов

```
reminder_id     title                        description                    next_date    frequency  enabled  last_sent
weight          Взвеситься                   Утром натощак                  2026-04-30   weekly     TRUE
blood_test      Общий анализ крови           Натощак, лаборатория около    2026-05-15   monthly    TRUE
                                             дома (Хеликс)
dentist         Запись к зубному             Раз в полгода                  2026-09-15   180        TRUE
vitamins        Принять витамин D            3000 МЕ                        2026-04-30   daily      TRUE
```

⚠️ В Sheets вводи `TRUE` / `FALSE` точно (с большой буквы или «1»/«0» —
оба работают). `daily` каждый день — лучше для важных регулярных штук
(витамины, лекарства).

## Импорт workflow в n8n

1. **Workflows → + → Import from File** →
   `Desktop/LifeDashboard/n8n/health-reminders-workflow.json`.
2. Откроется схема из 7 нод.
3. На нодах с ⚠️ подвяжи credentials:
   - `Отправить в Telegram` → выбери `Life Dashboard Bot`.
   - `Обновить next_date в Sheets` → выбери Google Sheets credential
     (тот что для gcal-sync).
4. Открой ноду **Конфиг** → поле `telegram_chat_id` → подставь свой
   chat_id.
5. Сохрани (Cmd+S).

## Тест

1. В Sheets создай тестовую строку:
   - `reminder_id`: `test`
   - `title`: `Тест напоминаний`
   - `next_date`: сегодняшняя дата (`2026-04-29`)
   - `frequency`: `once`
   - `enabled`: `TRUE`
2. В n8n → **Execute workflow**.
3. В Telegram должно прийти `🔔 Напоминание / Тест напоминаний`.
4. После выполнения проверь Sheets — у строки `test` должно быть
   `enabled=FALSE`, `last_sent=2026-04-29`.
5. Если ок — **Publish** (активация). Каждый день 09:00 МСК.

## Логика workflow

```
Schedule 09:00 МСК
  → Конфиг (sheet_id, chat_id, reminders_tab)
  → HTTP: gviz CSV health_reminders
  → Code: фильтр (next_date <= today AND enabled=TRUE)
       → для каждого rema: рассчитать new next_date по frequency
  → IF: есть ли reminder'ы?
       → Telegram: отправить
       → Google Sheets: appendOrUpdate (matching: reminder_id)
       → пропустить если __nothing
```

## Идеи reminder'ов для старта

- **Daily:** витамины, лекарства, утренний стакан воды натощак.
- **Weekly:** взвешивание, влажная уборка, вынести мусор.
- **Monthly:** общий анализ крови (для слежки за гемоглобином / ферритином),
  оплата интернета, проверка пробега машины.
- **Quarterly (90):** стоматологическая чистка, осмотр у эндокринолога.
- **Yearly:** полный чекап, ИФА на аллергены, обновление страховок.
- **Once:** разовые задачи (записаться на МРТ, оформить визу).

## Изменение / отключение reminder'а

- **Поменять дату:** просто отредактируй `next_date` в Sheets.
- **Выключить временно:** `enabled` = `FALSE`. Включить обратно — `TRUE`.
- **Удалить:** удали строку или поставь `enabled=FALSE` навсегда.

## Что дальше (опционально)

- **Кнопки в Telegram:** «Сделано» / «Перенести на завтра». Сейчас
  reminder просто отправляется, без интерактива. Можно добавить inline
  buttons и обработку callback в новом workflow.
- **Snooze:** сейчас если день пропущен — reminder отправится на
  следующем запуске. Если хочешь чтобы пропущенные не отправлялись —
  можно добавить условие `next_date == today` (вместо `<=`) в Code-ноде.
