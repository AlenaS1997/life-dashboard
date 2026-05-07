"""
Создаёт вкладку `nutrition_goals` в Google Sheets с правильными заголовками.

Зачем:
- В неё bot-reminder-writer (по команде /goal) пишет цели КБЖУ.
- Из неё morning-digest и weekly-digest читают самую свежую цель,
  чтобы Claude мог сравнивать твоё реальное питание с целью.
- Дашборд тоже читает эту вкладку для блока «Серии в норме».

Запуск (один раз):
    cd ~/Desktop/LifeDashboard
    python3.11 scripts/init_nutrition_goals_sheet.py

Скрипт идемпотентный — если вкладка уже есть, он её не трогает,
только проверяет заголовки и допишет недостающие.

Структура вкладки:
    date_set  | kcal | protein_g | fat_g | carbs_g | source
    ----------+------+-----------+-------+---------+--------
    2026-05-06| 1800 | 120       | 60    | 180     | manual
    ...

Каждая строка = одна установка цели. Когда меняешь /goal в боте —
добавляется новая строка с новой датой. История целей сохраняется,
дашборд и дайджесты используют САМУЮ СВЕЖУЮ.

Если хочешь сразу записать стартовую цель — задай в .env:
    NUTRITION_GOAL_KCAL=1800
    NUTRITION_GOAL_PROTEIN_G=120
    NUTRITION_GOAL_FAT_G=60
    NUTRITION_GOAL_CARBS_G=180
Скрипт запишет её первой строкой.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path

import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("init_goals")

WORKSHEET_NAME = "nutrition_goals"
HEADERS = ["date_set", "kcal", "protein_g", "fat_g", "carbs_g", "source"]


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        log.warning("python-dotenv не установлен — читаю env как есть")

    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        log.error("GOOGLE_SHEET_ID не задан в .env")
        return 1

    sa_rel = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", ".secrets/service-account.json")
    sa_path = (ROOT / sa_rel).resolve()
    if not sa_path.exists():
        log.error(f"Service account не найден: {sa_path}")
        return 1

    log.info("Авторизуюсь в Google Sheets...")
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(sa_path), scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)

    try:
        ws = sh.worksheet(WORKSHEET_NAME)
        log.info(f"Вкладка '{WORKSHEET_NAME}' уже существует — проверяю заголовки.")
        existing_headers = ws.row_values(1)
        if existing_headers == HEADERS:
            log.info("Заголовки совпадают, ничего не делаю.")
        elif not existing_headers:
            ws.append_row(HEADERS)
            log.info("Заголовков не было, добавил.")
        else:
            log.warning(
                f"Заголовки отличаются: текущие={existing_headers}, ожидаемые={HEADERS}. "
                "Не трогаю — проверь руками."
            )
            return 2
    except gspread.WorksheetNotFound:
        log.info(f"Создаю вкладку '{WORKSHEET_NAME}'")
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=200, cols=len(HEADERS))
        ws.append_row(HEADERS)
        log.info(f"Вкладка создана с заголовками: {HEADERS}")

    # Если в .env есть стартовая цель — запишем её, если в листе ещё нет данных.
    starter_kcal = os.getenv("NUTRITION_GOAL_KCAL")
    if starter_kcal and len(ws.col_values(1)) <= 1:
        row = [
            date.today().isoformat(),
            float(starter_kcal),
            float(os.getenv("NUTRITION_GOAL_PROTEIN_G") or 0),
            float(os.getenv("NUTRITION_GOAL_FAT_G") or 0),
            float(os.getenv("NUTRITION_GOAL_CARBS_G") or 0),
            "init_script",
        ]
        ws.append_row(row)
        log.info(f"Записал стартовую цель из .env: {row}")
    elif starter_kcal:
        log.info("В листе уже есть данные — стартовую цель из .env не добавляю.")
    else:
        log.info(
            "NUTRITION_GOAL_KCAL не задан в .env — лист создан пустым. "
            "Задай цель командой /goal в Telegram-боте."
        )

    log.info("Готово.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.exception(f"Ошибка: {e}")
        sys.exit(1)
