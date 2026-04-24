# Life Dashboard — HTML

Одностраничный дашборд для iPhone. Читает данные из Google Sheets через публичный CSV-endpoint (без backend).

## Файлы

- `index.html` — вся страница (HTML + CSS + JS в одном файле)
- `manifest.webmanifest` — PWA-манифест (для «Добавить на экран «Домой»»)
- `icon.svg` — иконка приложения

## Превью локально (прямо сейчас)

Можно открыть `index.html` двойным кликом в Finder — откроется в Safari, будет показаны **demo-данные** (dashboard пока не может достучаться до таблицы, потому что доступ не настроен).

Либо из терминала:
```bash
cd ~/Desktop/LifeDashboard/dashboard
python3 -m http.server 8000
# и открыть http://localhost:8000 в Safari
```

## Подключение реальных данных

1. Открой [таблицу Life Dashboard](https://docs.google.com/spreadsheets/d/1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE/edit).
2. `Share` (справа вверху) → изменить вариант «Restricted» на **«Anyone with the link: Viewer»** → Done.
3. Перезагрузи дашборд — вместо demo увидишь реальные цифры.

Никаких секретов на странице нет: дашборд просто читает опубликованную таблицу.

## Деплой на GitHub Pages

1. Создай публичный репозиторий `life-dashboard-web` (или имя на свой вкус).
2. В него положи только содержимое папки `dashboard/` (НЕ `scripts/`, НЕ `.secrets/`, НЕ `.env`).
3. В Settings → Pages → Source = `main` branch, folder = `/root`.
4. Через 1–2 минуты дашборд откроется по адресу `https://<твой-github>.github.io/life-dashboard-web/`.

## Добавление на iPhone

1. Открой адрес дашборда в Safari на iPhone.
2. Кнопка «Поделиться» → **«На экран «Домой»»**.
3. Имя можно оставить «Life».
4. Иконка появится на домашнем экране, запуск — как у нативного приложения (без адресной строки Safari).

## Настройка

В файле `index.html` в самом верху `<script>` есть блок `CONFIG`:

```js
const CONFIG = {
  SHEET_ID: "1soLhY5LtrYzcQktWqcmX9Of0YGWqnccuvj37DU3GhKE",
  GARMIN_TAB: "garmin_daily",
  EVENTS_TAB: "gcal_events",
  FORCE_MOCK: false,   // поставь true, если хочешь всегда видеть demo-данные
};
```

Если переименуешь вкладки в таблице — поменяй тут.

## Что показывает

- **Сегодня**: последняя строка из `garmin_daily` — сон, sleep score, HRV, шаги, стресс, Body Battery.
- **Тренды · 7 дней**: мини-графики с последней недели + среднее.
- **События дня**: записи из `gcal_events`, у которых дата = сегодня.
- **Обновлено**: время последней загрузки, кнопка «Обновить» для ручного рефреша.

## Тёмная тема и адаптив

Дизайн сделан iPhone-first (max-width 480px, safe-area-inset для «чёлки»). Работает и на десктопе — просто контент центрируется.

Все цвета вынесены в CSS-переменные в начале `<style>`, легко поменять. Сейчас акцентные цвета:
- Сон — фиолетовый (#9c88ff)
- HRV — голубой (#4fc3f7)
- Шаги — зелёный (#66bb6a)
- Стресс — оранжевый (#ff7043)
- Body Battery — янтарный (#ffca28)

## Что дальше

- [ ] Добавить погоду (OpenWeather API)
- [ ] Интегрировать FatSecret (когда появятся данные о питании)
- [ ] Связать с утренним Telegram-дайджестом (кнопка «показать инсайт»)
- [ ] Service worker + offline cache (чтобы дашборд открывался даже без интернета)
