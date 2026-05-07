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

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kcal",    type=float, help="Целевые калории (ккал)")
    parser.add_argument("--protein", type=float, help="Целевой белок (г)")
    parser.add_argument("--fat",     type=float, help="Целевые жиры (г)")
    parser.add_argument("--carbs",   type=float, help="Целевые углеводы (г)")
    parser.add_argument("--source",  default="manual", help="Источник записи (default: manual)")
    args = parser.parse_args()

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

    # Цель можно задать тремя способами (приоритет сверху вниз):
    #   1. CLI аргументы --kcal/--protein/--fat/--carbs (самый удобный)
    #   2. .env переменные NUTRITION_GOAL_KCAL и т.д.
    #   3. Не задавать — потом /goal в Telegram-боте.
    cli_goal = args.kcal is not None
    env_goal = os.getenv("NUTRITION_GOAL_KCAL")

    if cli_goal:
        row = [
            date.today().isoformat(),
            float(args.kcal),
            float(args.protein or 0),
            float(args.fat or 0),
            float(args.carbs or 0),
            args.source,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        log.info(f"✅ Цель из CLI записана: {row}")
    elif env_goal and len(ws.col_values(1)) <= 1:
        row = [
            date.today().isoformat(),
            float(env_goal),
            float(os.getenv("NUTRITION_GOAL_PROTEIN_G") or 0),
            float(os.getenv("NUTRITION_GOAL_FAT_G") or 0),
            float(os.getenv("NUTRITION_GOAL_CARBS_G") or 0),
            "init_script",
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        log.info(f"✅ Цель из .env записана: {row}")
    elif env_goal:
        log.info("В листе уже есть данные — цель из .env не добавляю.")
    else:
        log.info(
            "Цель не задана. Лист создан/обновлён. "
            "Чтобы записать цель прямо сейчас, перезапусти с аргументами:\n"
            "  python3.11 scripts/init_nutrition_goals_sheet.py "
            "--kcal 2190 --protein 190 --fat 70 --carbs 200"
        )

    log.info("Готово.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log.exception(f"Ошибка: {e}")
        sys.exit(1)
