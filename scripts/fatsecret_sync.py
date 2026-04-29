"""
FatSecret → Google Sheets sync.

ЗАГОТОВКА. Скрипт ждёт API-ключи на FatSecret Platform
(`platform.fatsecret.com`) и user-токен от OAuth 1.0a авторизации.

Что делает (когда заполнишь .env):
    1. Поднимает OAuth 1.0a сессию к FatSecret API v3.
    2. Тянет food_entries.get_v2 за указанную дату (по умолчанию вчера).
    3. Агрегирует калории, белки, жиры, углеводы.
    4. Пишет одну строку в Google Sheets вкладку `fatsecret_daily`.

Запуск:
    python3.11 scripts/fatsecret_sync.py                # вчера
    python3.11 scripts/fatsecret_sync.py --date 2026-04-29
    python3.11 scripts/fatsecret_sync.py --dry-run

Перед первым запуском:
    1. Зарегистрируйся на https://platform.fatsecret.com (бесплатно).
       ⚠️ Это отдельная система от мобильного приложения. Пароль от
       приложения там НЕ работает. Создай новый аккаунт, можно тот же email.
    2. Создай API application → получи Consumer Key + Consumer Secret.
    3. Заполни в .env:
           FATSECRET_CONSUMER_KEY=...
           FATSECRET_CONSUMER_SECRET=...
    4. Запусти один раз scripts/fatsecret_auth.py — он проведёт через
       OAuth 1.0a flow и сохранит user-токен в .secrets/fatsecret_token.json.
    5. После этого можно запускать этот скрипт.

⚠️ ВАЖНО ПРО PREMIER API:
    food_entries.get_v2 (доступ к личному food diary) на FREE TIER
    обычно не работает — endpoint требует Premier API доступ
    (~$10-20/мес). Перед началом работы проверь свой dashboard на
    platform.fatsecret.com → Profile → API Permissions. Если food diary
    недоступен — нужно либо платить за Premier, либо парсить веб-версию
    fatsecret.com через selenium (хак, но работает на бесплатном аккаунте).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("fatsecret_sync")

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
TOKEN_PATH = ROOT / ".secrets" / "fatsecret_token.json"

# FatSecret API endpoints
FS_REQUEST_URL = "https://oauth.fatsecret.com/oauth/request_token"
FS_AUTHORIZE_URL = "https://www.fatsecret.com/oauth/authorize"
FS_ACCESS_URL = "https://oauth.fatsecret.com/oauth/access_token"
FS_API_URL = "https://platform.fatsecret.com/rest/server.api"

DEFAULT_HEADERS = [
    "date",
    "calories_kcal",
    "protein_g",
    "fat_g",
    "carbs_g",
    "fiber_g",
    "entries_count",
]


def load_env():
    """Подгружаем .env через python-dotenv."""
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        log.warning("python-dotenv не установлен, читаем из os.environ напрямую")


def load_user_token() -> dict | None:
    """Читаем сохранённый OAuth user-токен.

    Формат: {"oauth_token": "...", "oauth_token_secret": "..."}
    """
    if not TOKEN_PATH.exists():
        return None
    try:
        return json.loads(TOKEN_PATH.read_text())
    except Exception as e:
        log.error(f"Не смог прочитать {TOKEN_PATH}: {e}")
        return None


def make_oauth_session():
    """Создаёт OAuth1Session готовую к запросам к FS API."""
    try:
        from requests_oauthlib import OAuth1Session
    except ImportError:
        log.error(
            "Нужен пакет requests-oauthlib. Установи:\n"
            "    python3.11 -m pip install requests-oauthlib"
        )
        sys.exit(1)

    consumer_key = os.getenv("FATSECRET_CONSUMER_KEY")
    consumer_secret = os.getenv("FATSECRET_CONSUMER_SECRET")
    if not consumer_key or not consumer_secret:
        log.error(
            "FATSECRET_CONSUMER_KEY / FATSECRET_CONSUMER_SECRET не заданы в .env\n"
            "Зарегистрируйся на https://platform.fatsecret.com и создай API application."
        )
        sys.exit(1)

    user_token = load_user_token()
    if not user_token:
        log.error(
            f"User-токен не найден в {TOKEN_PATH}\n"
            "Сначала запусти: python3.11 scripts/fatsecret_auth.py"
        )
        sys.exit(1)

    return OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=user_token["oauth_token"],
        resource_owner_secret=user_token["oauth_token_secret"],
    )


def fetch_food_entries(session, target_date: str) -> list[dict]:
    """Тянет food entries для указанной даты.

    target_date в формате YYYY-MM-DD. FatSecret использует "date" параметр
    как количество дней с эпохи Unix (2000-01-01 = 0). Конвертируем.
    """
    epoch = date(1970, 1, 1)
    target = datetime.strptime(target_date, "%Y-%m-%d").date()
    days_since_epoch = (target - epoch).days

    params = {
        "method": "food_entries.get_v2",
        "format": "json",
        "date": str(days_since_epoch),
    }
    log.info(f"Запрашиваю food_entries за {target_date} (день {days_since_epoch})")
    r = session.get(FS_API_URL, params=params)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        log.error(f"FS API вернул ошибку: {data['error']}")
        # error.code 21 = Premier API required
        if str(data["error"].get("code")) == "21":
            log.error(
                "Endpoint food_entries.get_v2 требует Premier API. "
                "Альтернатива — selenium-парсер веб-версии fatsecret.com."
            )
        return []

    entries_block = data.get("food_entries") or {}
    raw = entries_block.get("food_entry") or []
    # FS может вернуть один объект (dict) если запись одна, или список — нормализуем
    if isinstance(raw, dict):
        raw = [raw]
    return raw


def aggregate_entries(entries: list[dict]) -> dict:
    """Сворачиваем массив записей в дневные агрегаты."""

    def to_float(v):
        try:
            return float(v) if v not in (None, "") else 0.0
        except (TypeError, ValueError):
            return 0.0

    totals = {"calories_kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0, "fiber_g": 0.0}
    for e in entries:
        totals["calories_kcal"] += to_float(e.get("calories"))
        totals["protein_g"]     += to_float(e.get("protein"))
        totals["fat_g"]         += to_float(e.get("fat"))
        totals["carbs_g"]       += to_float(e.get("carbohydrate"))
        totals["fiber_g"]       += to_float(e.get("fiber"))

    return {
        "calories_kcal": round(totals["calories_kcal"], 1),
        "protein_g":     round(totals["protein_g"], 1),
        "fat_g":         round(totals["fat_g"], 1),
        "carbs_g":       round(totals["carbs_g"], 1),
        "fiber_g":       round(totals["fiber_g"], 1),
        "entries_count": len(entries),
    }


def write_to_sheet(row: dict, sheet_id: str, worksheet_name: str, sa_path: str) -> None:
    """Пишет одну строку в `fatsecret_daily`. Идемпотентно по date."""
    import gspread
    from google.oauth2.service_account import Credentials

    log.info(f"Открываю Sheets (worksheet='{worksheet_name}')")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(sa_path, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)

    try:
        ws = sh.worksheet(worksheet_name)
    except gspread.WorksheetNotFound:
        log.info(f"Создаю вкладку '{worksheet_name}'")
        ws = sh.add_worksheet(title=worksheet_name, rows=400, cols=len(DEFAULT_HEADERS))
        ws.append_row(DEFAULT_HEADERS)

    headers = ws.row_values(1)
    if not headers:
        ws.append_row(DEFAULT_HEADERS)
        headers = DEFAULT_HEADERS

    # Идемпотентность: ищем по date в колонке A
    existing_dates = ws.col_values(1)[1:]  # без заголовка
    if row["date"] in existing_dates:
        log.info(f"Строка с date={row['date']} уже есть, перезаписываю.")
        idx = existing_dates.index(row["date"]) + 2  # +1 за заголовок, +1 за 1-индексирование
        values = [row.get(h, "") for h in headers]
        ws.update(f"A{idx}:{chr(ord('A')+len(headers)-1)}{idx}", [values])
    else:
        ws.append_row([row.get(h, "") for h in headers])
        log.info(f"Добавил строку за {row['date']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Дата YYYY-MM-DD (по умолчанию вчера)")
    parser.add_argument("--dry-run", action="store_true", help="Не писать в Sheets")
    args = parser.parse_args()

    load_env()

    target_date = args.date or (date.today() - timedelta(days=1)).isoformat()
    log.info(f"Дата: {target_date}")

    session = make_oauth_session()
    entries = fetch_food_entries(session, target_date)
    log.info(f"Получено записей: {len(entries)}")

    aggregates = aggregate_entries(entries)
    aggregates["date"] = target_date
    log.info(f"Агрегаты: {aggregates}")

    if args.dry_run:
        log.info("--dry-run, в Sheets не пишу.")
        return 0

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    sa_rel = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", ".secrets/service-account.json")
    if not sheet_id:
        log.error("GOOGLE_SHEET_ID не задан в .env")
        return 1
    sa_path = (ROOT / sa_rel).resolve()
    if not sa_path.exists():
        log.error(f"Service account не найден: {sa_path}")
        return 1

    write_to_sheet(aggregates, sheet_id, "fatsecret_daily", str(sa_path))
    log.info("Готово.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.warning("Прервано (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        log.exception(f"Неожиданная ошибка: {e}")
        sys.exit(1)
