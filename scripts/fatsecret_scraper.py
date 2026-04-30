"""
FatSecret Web Scraper — обход Premier API через web-логин.

Бесплатная альтернатива FatSecret Premier API ($10/мес).
Логинимся в fatsecret.com под твоим user-account из мобильного
приложения, парсим страницу Food Diary за указанную дату, агрегируем
КБЖУ, пишем в Google Sheets вкладку `fatsecret_daily`.

Требует:
- selenium + webdriver-manager:
    python3.11 -m pip install selenium webdriver-manager --break-system-packages
- Chrome или Chromium установлен (chromedriver подтянется сам).
- В .env:
    FATSECRET_EMAIL=...
    FATSECRET_PASSWORD=...

Запуск:
    python3.11 scripts/fatsecret_scraper.py            # вчера
    python3.11 scripts/fatsecret_scraper.py --date 2026-04-28
    python3.11 scripts/fatsecret_scraper.py --dry-run  # без записи в Sheets

⚠️ ХРУПКОСТЬ: если FatSecret поменяет вёрстку — селекторы перестанут
работать, скрипт упадёт. В этом случае запусти с --debug-html — он
сохранит HTML-страницу diary в `data/fatsecret_diary_*.html`,
по нему я подправлю селекторы.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("fs_scraper")

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

LOGIN_URL = "https://www.fatsecret.com/Default.aspx?pa=memlin"
DIARY_URL_TPL = "https://www.fatsecret.com/Diary.aspx?pa=fjrd&dt={date_int}"

DEFAULT_HEADERS = [
    "date",
    "calories_kcal",
    "protein_g",
    "fat_g",
    "carbs_g",
    "fiber_g",
    "entries_count",
]


def fs_date_int(target_date_str: str) -> int:
    """FS использует количество дней с 1970-01-01 в URL diary."""
    epoch = date(1970, 1, 1)
    target = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    return (target - epoch).days


def make_driver(headless: bool = True):
    """Создаём selenium driver. webdriver-manager сам скачает chromedriver."""
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        log.error(
            "Установи selenium и webdriver-manager:\n"
            "    python3.11 -m pip install selenium webdriver-manager --break-system-packages"
        )
        sys.exit(1)

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,1800")
    # «обычный» user-agent — чтобы не вызвать защиту от ботов
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def login(driver, email: str, password: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    log.info("Логинимся в FatSecret...")
    driver.get(LOGIN_URL)

    # Поля логина: id="ctl00$Body$Email" / "ctl00$Body$Password" (типичные ASP.NET селекторы)
    # Если FS поменяет — придётся обновить.
    try:
        email_field = WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.NAME, "ctl00$Body$Email"))
        )
        password_field = driver.find_element(By.NAME, "ctl00$Body$Password")
    except Exception:
        # Fallback: ищем по type
        log.warning("Не нашёл поля по name, пробую по type=email/password")
        email_field = driver.find_element(By.CSS_SELECTOR, "input[type='email'], input[type='text'][name*='Email']")
        password_field = driver.find_element(By.CSS_SELECTOR, "input[type='password']")

    email_field.send_keys(email)
    password_field.send_keys(password)

    # Кнопка submit — может быть разной
    submit = None
    for selector in [
        (By.CSS_SELECTOR, "input[type='submit']"),
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.NAME, "ctl00$Body$LoginBtn"),
    ]:
        try:
            submit = driver.find_element(*selector)
            break
        except Exception:
            continue
    if not submit:
        raise RuntimeError("Не нашёл кнопку Login")
    submit.click()

    # Ждём редирект — главная или member page
    time.sleep(3)
    if "memlin" in driver.current_url.lower() or "login" in driver.current_url.lower():
        # Возможно неверный логин или CAPTCHA
        raise RuntimeError(
            f"Логин не прошёл (URL после submit: {driver.current_url}). "
            "Проверь email/password в .env. Если корректные — возможно FS показал CAPTCHA: "
            "запусти с --no-headless чтобы пройти CAPTCHA вручную."
        )
    log.info(f"Логин успешен. URL: {driver.current_url}")


def fetch_diary(driver, target_date: str) -> list[dict]:
    """Парсит страницу food diary за указанную дату.

    FS Diary URL: /Diary.aspx?pa=fjrd&dt={days_since_epoch}
    Структура: таблица с полями (food name, serving, calories, fat, carbs, protein, ...).
    """
    from selenium.webdriver.common.by import By

    date_int = fs_date_int(target_date)
    url = DIARY_URL_TPL.format(date_int=date_int)
    log.info(f"Открываю diary URL: {url}")
    driver.get(url)
    time.sleep(2.5)  # подождать рендера

    # Селекторы для таблиц diary в FS обычно содержат класс "generic"
    # или таблица с id. Пробуем несколько вариантов.
    entries = []
    try:
        # Гипотеза: таблица class="generic searchResult" или подобное
        rows = driver.find_elements(By.CSS_SELECTOR, "table.generic tr")
        log.info(f"Найдено tr в table.generic: {len(rows)}")
    except Exception as e:
        log.warning(f"Селектор table.generic не сработал: {e}")
        rows = []

    for row in rows:
        try:
            cells = row.find_elements(By.TAG_NAME, "td")
            if len(cells) < 5:
                continue
            text_cells = [c.text.strip() for c in cells]
            # Типичный порядок: [имя еды, порция, калории, жиры, угл, белки]
            # Точный порядок зависит от FS. Сохраним всё для diagnostics.
            entry = {"raw_cells": text_cells}
            # Парсим числа из ячеек
            nums = []
            for txt in text_cells:
                # Числа могут быть с запятой и единицами: "234 kcal", "12,5 g"
                m = re.search(r"(\d+(?:[.,]\d+)?)", txt.replace(",", "."))
                if m:
                    nums.append(float(m.group(1)))
                else:
                    nums.append(None)
            entry["nums"] = nums
            # Если в строке есть осмысленное название и хотя бы 2 числа — считаем записью
            if text_cells[0] and any(n is not None for n in nums[1:]):
                entries.append(entry)
        except Exception:
            continue

    log.info(f"Распарсено записей: {len(entries)}")
    return entries


def aggregate_entries(entries: list[dict]) -> dict:
    """Суммируем КБЖУ.

    Эвристика: если 6 чисел — порядок [serving, kcal, fat, carbs, protein, ...].
    Без достоверной структуры берём максимум из ячеек как калории, и пытаемся
    угадать остальное. ⚠️ Требует ручной калибровки на её живых данных.
    """
    totals = {"calories_kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0, "fiber_g": 0.0}
    for e in entries:
        nums = [n for n in e.get("nums", []) if n is not None]
        if not nums:
            continue
        # Самая разумная гипотеза для FS: nums[1]=kcal, nums[2]=fat, nums[3]=carbs, nums[4]=protein
        # Откалибруем после первого реального запуска.
        if len(nums) >= 2:
            totals["calories_kcal"] += nums[1] if len(nums) > 1 else 0
        if len(nums) >= 3:
            totals["fat_g"] += nums[2]
        if len(nums) >= 4:
            totals["carbs_g"] += nums[3]
        if len(nums) >= 5:
            totals["protein_g"] += nums[4]

    return {
        "calories_kcal": round(totals["calories_kcal"], 1),
        "protein_g":     round(totals["protein_g"], 1),
        "fat_g":         round(totals["fat_g"], 1),
        "carbs_g":       round(totals["carbs_g"], 1),
        "fiber_g":       round(totals["fiber_g"], 1),
        "entries_count": len(entries),
    }


def write_to_sheet(row: dict, sheet_id: str, worksheet_name: str, sa_path: str) -> None:
    import gspread
    from google.oauth2.service_account import Credentials

    log.info(f"Пишу в Sheets вкладку '{worksheet_name}'")
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

    headers = ws.row_values(1) or DEFAULT_HEADERS
    if not ws.row_values(1):
        ws.append_row(DEFAULT_HEADERS)

    existing_dates = ws.col_values(1)[1:]
    if row["date"] in existing_dates:
        log.info(f"Перезаписываю строку за {row['date']}")
        idx = existing_dates.index(row["date"]) + 2
        last_col = chr(ord("A") + len(headers) - 1) if len(headers) <= 26 else "Z"
        ws.update(f"A{idx}:{last_col}{idx}", [[row.get(h, "") for h in headers]])
    else:
        ws.append_row([row.get(h, "") for h in headers])
        log.info(f"Добавил строку за {row['date']}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Дата YYYY-MM-DD (по умолчанию вчера)")
    parser.add_argument("--dry-run", action="store_true", help="Не писать в Sheets")
    parser.add_argument("--no-headless", action="store_true", help="Показать окно Chrome (для отладки CAPTCHA)")
    parser.add_argument("--debug-html", action="store_true", help="Сохранить HTML diary в data/")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        log.warning("python-dotenv не установлен")

    email = os.getenv("FATSECRET_EMAIL")
    password = os.getenv("FATSECRET_PASSWORD")
    if not email or not password:
        log.error("FATSECRET_EMAIL / FATSECRET_PASSWORD не заданы в .env")
        return 1

    target_date = args.date or (date.today() - timedelta(days=1)).isoformat()
    log.info(f"Дата: {target_date}")

    driver = make_driver(headless=not args.no_headless)
    try:
        login(driver, email, password)
        entries = fetch_diary(driver, target_date)

        if args.debug_html:
            html_path = DATA_DIR / f"fatsecret_diary_{target_date}.html"
            html_path.write_text(driver.page_source, encoding="utf-8")
            log.info(f"HTML сохранён: {html_path}")

        agg = aggregate_entries(entries)
        agg["date"] = target_date
        log.info(f"Агрегаты: {agg}")

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

        write_to_sheet(agg, sheet_id, "fatsecret_daily", str(sa_path))
        log.info("Готово.")
        return 0
    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.warning("Прервано (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        log.exception(f"Неожиданная ошибка: {e}")
        sys.exit(1)
