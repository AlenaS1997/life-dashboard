"""
Одноразовая чистка вкладки `gcal_events` в Google Sheets.

Зачем: после переезда с Make.com на n8n / правильно настроенный Make,
в таблице остался мусор от старого сценария (повторяющиеся записи
за 13–14 апреля). Этот скрипт чистит всё кроме строки заголовков.

Использует тот же service-account, что и `garmin_sync.py`
(`life-dashboard-writer@...`), уже расшаренный в эту таблицу с правами Editor.

Использование:
    python3.11 scripts/clear_gcal_events.py --dry-run   # показать что удалит
    python3.11 scripts/clear_gcal_events.py             # реально почистить

После запуска n8n / Make сами зальют свежие данные на следующее утро.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

import gspread
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("clear_gcal_events")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать, сколько строк будет удалено, но ничего не менять",
    )
    parser.add_argument(
        "--worksheet",
        default="gcal_events",
        help="Имя вкладки (по умолчанию: gcal_events)",
    )
    args = parser.parse_args()

    # Грузим .env (рядом со скриптом или из текущей директории)
    repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(repo_root / ".env")

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    sa_rel = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", ".secrets/service-account.json")
    if not sheet_id:
        log.error("GOOGLE_SHEET_ID не задан в .env")
        return 1

    sa_path = (repo_root / sa_rel).resolve()
    if not sa_path.exists():
        log.error(f"Service-account JSON не найден: {sa_path}")
        return 1

    log.info(f"Открываю таблицу {sheet_id}, вкладка '{args.worksheet}'...")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(sa_path), scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)

    try:
        ws = sh.worksheet(args.worksheet)
    except gspread.WorksheetNotFound:
        available = [w.title for w in sh.worksheets()]
        log.error(
            f"Вкладка '{args.worksheet}' не найдена. Доступные: {available}"
        )
        return 1

    all_values = ws.get_all_values()
    total_rows = len(all_values)
    if total_rows == 0:
        log.warning("Вкладка пустая — даже заголовка нет. Ничего не делаю.")
        return 0
    if total_rows == 1:
        log.info("На вкладке только заголовок, чистить нечего. Готово.")
        return 0

    headers = all_values[0]
    data_rows = total_rows - 1
    log.info(f"Заголовок: {headers}")
    log.info(f"Строк данных к удалению: {data_rows}")
    if data_rows <= 5:
        # Для небольшого количества — покажем что именно сносим
        for i, row in enumerate(all_values[1:], start=2):
            log.info(f"  row {i}: {row}")

    if args.dry_run:
        log.info("--dry-run — ничего не меняю. Запусти без флага, чтобы реально почистить.")
        return 0

    # Очищаем содержимое строк 2..N. Заголовок (строка 1) не трогаем.
    # batch_clear очищает значения в указанном диапазоне.
    last_col = len(headers) if headers else 26
    # gspread понимает A1-нотацию; колонки A..Z покрывают до 26 столбцов,
    # для большего нужен colnum_to_a1, но у нас 5 колонок.
    last_col_letter = chr(ord("A") + last_col - 1) if last_col <= 26 else "Z"
    last_row = total_rows
    range_to_clear = f"A2:{last_col_letter}{last_row}"
    log.info(f"Очищаю диапазон {range_to_clear}...")
    ws.batch_clear([range_to_clear])

    # Дополнительно — физически удаляем пустые строки, чтобы вкладка стала компактной.
    # delete_rows удаляет строки физически (ряды смещаются вверх).
    if data_rows > 0:
        log.info(f"Удаляю строки 2..{last_row} физически...")
        ws.delete_rows(2, last_row)

    log.info(f"Готово: вкладка '{args.worksheet}' содержит только заголовок.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.warning("Прервано пользователем (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        log.exception(f"Неожиданная ошибка: {e}")
        sys.exit(1)
