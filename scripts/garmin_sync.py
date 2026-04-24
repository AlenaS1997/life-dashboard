"""
Garmin Connect → Google Sheets sync.
Раз в день забирает метрики за вчера и пишет строку в таблицу.

Запуск:
    python scripts/garmin_sync.py                # обычный запуск
    python scripts/garmin_sync.py --dry-run      # без записи в Sheets (для отладки)
    python scripts/garmin_sync.py --date 2026-04-22   # задать конкретную дату
"""

import os
import sys
import json
import time
import logging
import warnings
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

from dotenv import load_dotenv
import garminconnect
import gspread
from google.oauth2.service_account import Credentials

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
SESSION_MARKER = DATA_DIR / "garmin_session.json"
# Папка с токенами garth (oauth1/oauth2). Лежит в .secrets, т.к. это, по сути,
# долгоживущий логин — её нельзя коммитить в гит. Срок жизни oauth1-токена у Garmin
# обычно около года, oauth2 обновляется автоматически через refresh-токен.
GARTH_TOKENS_DIR = ROOT / ".secrets" / "garth"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)
GARTH_TOKENS_DIR.parent.mkdir(exist_ok=True)

load_dotenv(ENV_PATH)

# Логи: и в файл, и в stdout
log_filename = REPORTS_DIR / f"garmin_{date.today().isoformat()}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_filename, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("garmin_sync")


def _try_resume_session(email: str, password: str) -> garminconnect.Garmin | None:
    """Пробует поднять клиент из сохранённых garth-токенов.
    Если токенов нет или они просрочены — возвращает None."""
    if not GARTH_TOKENS_DIR.exists():
        return None
    try:
        log.info(f"Пробую восстановить сессию из {GARTH_TOKENS_DIR} (без логина).")
        client = garminconnect.Garmin(email, password)
        # У garth есть resume(path), который подхватит oauth1_token.json / oauth2_token.json
        client.garth.resume(str(GARTH_TOKENS_DIR))
        # Быстрая проверка, что токен живой — любой дешёвый вызов
        _ = client.get_user_profile()
        log.info("Сессия garth валидна — идём без логина.")
        return client
    except Exception as e:
        log.warning(f"Восстановить сессию не получилось ({e}) — логинюсь заново.")
        return None


def _persist_session(client: garminconnect.Garmin) -> None:
    """Сохраняет токены garth, чтобы следующий запуск пропустил логин."""
    try:
        GARTH_TOKENS_DIR.mkdir(parents=True, exist_ok=True)
        client.garth.dump(str(GARTH_TOKENS_DIR))
        log.info(f"Токены garth сохранены в {GARTH_TOKENS_DIR}.")
    except Exception as e:
        # Не падаем, если не смогли сохранить — это лишь оптимизация
        log.warning(f"Не удалось сохранить токены garth: {e}")


def login_with_backoff(email: str, password: str, max_attempts: int = 4) -> garminconnect.Garmin:
    """Логин в Garmin с приоритетом кэшированной сессии и бэкофом на 429.

    Стратегия:
    1. Если есть валидные garth-токены — используем их, логин вообще не нужен.
    2. Иначе делаем полный логин с экспоненциальным бэкофом на 429 и сохраняем
       токены для следующего запуска.
    """
    # (1) Пробуем сессию из кэша — это спасает от 429, если запускаем руками несколько раз.
    resumed = _try_resume_session(email, password)
    if resumed is not None:
        return resumed

    # (2) Полный логин с ретраями
    delay = 30
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            log.info(f"Логин в Garmin, попытка {attempt}/{max_attempts}...")
            client = garminconnect.Garmin(email, password)
            client.login()
            log.info("Логин успешен.")
            SESSION_MARKER.write_text(
                json.dumps({"last_login": datetime.now().isoformat()}, ensure_ascii=False)
            )
            _persist_session(client)
            return client
        except Exception as e:
            last_exc = e
            msg = str(e)
            if "429" in msg or "Too Many Requests" in msg.lower():
                log.warning(f"429 Too Many Requests. Жду {delay}s и ретраю.")
                time.sleep(delay)
                delay *= 2
            else:
                log.error(f"Неретраибельная ошибка логина: {e}")
                raise
    raise RuntimeError(f"Не смог залогиниться в Garmin за {max_attempts} попыток: {last_exc}")


def _safe_call(fn, *args, default=None, label: str = "?"):
    """Вызов метода клиента с логированием ошибки и дефолтом — чтобы один
    пустой эндпоинт не убивал весь сбор данных."""
    try:
        return fn(*args)
    except Exception as e:
        log.warning(f"{label} недоступен: {e}")
        return default


def _extract_hrv(hrv_raw: dict | None) -> int | float:
    """HRV last-night average из разных форматов Garmin API."""
    if not hrv_raw:
        return 0
    summary = hrv_raw.get("hrvSummary") or {}
    # Пробуем по очереди самые часто встречающиеся ключи
    for key in ("lastNightAvg", "lastNight5MinHigh", "weeklyAvg"):
        value = summary.get(key)
        if value:
            return value
    return 0


def _extract_body_battery(bb_raw: list | None) -> tuple[int, int]:
    """Из списка daily BB достаём max/min за день.

    Формат: bodyBatteryValuesArray: [[timestamp_ms, status, value, version], ...]
    """
    if not bb_raw or not isinstance(bb_raw, list):
        return 0, 0
    day = bb_raw[0] if bb_raw else {}
    values_array = day.get("bodyBatteryValuesArray") or []
    battery_values = [
        v[2] for v in values_array
        if isinstance(v, list) and len(v) > 2 and isinstance(v[2], (int, float))
    ]
    if battery_values:
        return max(battery_values), min(battery_values)
    # Fallback на агрегированные поля, если массив пуст
    return int(day.get("charged") or 0), int(day.get("drained") or 0)


def fetch_garmin_data(client: garminconnect.Garmin, target_date: str) -> dict:
    """Метрики за указанную дату. Мягко переживает отсутствие отдельных фидов."""
    log.info(f"Забираю данные за {target_date}...")

    sleep = _safe_call(client.get_sleep_data, target_date, default={}, label="sleep") or {}
    dto = sleep.get("dailySleepDTO", {}) or {}

    stats = _safe_call(client.get_stats, target_date, default={}, label="stats") or {}

    hrv_raw = _safe_call(client.get_hrv_data, target_date, default={}, label="HRV")
    hrv_val = _extract_hrv(hrv_raw)

    bb_raw = _safe_call(client.get_body_battery, target_date, default=[], label="BodyBattery")
    bb_max, bb_min = _extract_body_battery(bb_raw)

    return {
        "date": target_date,
        "sleep_hours": round((dto.get("sleepTimeSeconds") or 0) / 3600, 2),
        "sleep_score": (dto.get("sleepScores") or {}).get("overall", {}).get("value") or 0,
        "body_battery_max": bb_max,
        "body_battery_min": bb_min,
        "hrv_last_night": hrv_val,
        "steps": stats.get("totalSteps") or 0,
        "stress_avg": stats.get("averageStressLevel") or 0,
    }


# Заголовки по умолчанию, если вкладка пустая (порядок = как будет записан в первой строке)
DEFAULT_HEADERS = [
    "date",
    "sleep_hours",
    "sleep_score",
    "body_battery_max",
    "body_battery_min",
    "hrv_last_night",
    "steps",
    "stress_avg",
]


def write_to_sheet(data: dict, sheet_id: str, worksheet_name: str, sa_path: str) -> None:
    """Пишет строку в Google Sheets. Идемпотентно: не дублирует дату."""
    log.info(f"Открываю Google Sheets (worksheet='{worksheet_name}')...")
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
        available = [w.title for w in sh.worksheets()]
        raise RuntimeError(
            f"Вкладка '{worksheet_name}' не найдена. Доступные вкладки: {available}. "
            f"Создай вкладку '{worksheet_name}' в таблице или поменяй GARMIN_WORKSHEET_NAME в .env."
        )

    # Читаем заголовки из первой строки — они и есть источник истины для порядка
    existing_headers = ws.row_values(1)
    if not existing_headers:
        log.info("Вкладка пустая — записываю заголовки по умолчанию.")
        ws.append_row(DEFAULT_HEADERS)
        existing_headers = DEFAULT_HEADERS

    # Предупреждаем, если в данных есть ключи, которых нет в заголовках (потеряем) или наоборот
    missing_in_data = [h for h in existing_headers if h not in data]
    extra_in_data = [k for k in data if k not in existing_headers]
    if missing_in_data:
        log.warning(f"Заголовки без значений (будут пустыми): {missing_in_data}")
    if extra_in_data:
        log.warning(f"Данные без заголовков в таблице (не запишутся): {extra_in_data}")

    # Идемпотентность: если дата уже записана — не дублируем
    all_dates = ws.col_values(1)
    if str(data.get("date", "")) in all_dates[1:]:
        log.warning(f"Строка за {data['date']} уже есть в таблице — пропускаю.")
        return

    row = [data.get(h, "") for h in existing_headers]
    ws.append_row(row, value_input_option="USER_ENTERED")
    log.info(f"✅ Записана строка: {dict(zip(existing_headers, row))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Garmin → Google Sheets sync")
    parser.add_argument("--dry-run", action="store_true", help="Не писать в Sheets")
    parser.add_argument("--date", help="Дата YYYY-MM-DD (по умолчанию — вчера)")
    args = parser.parse_args()

    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    sa_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", ".secrets/service-account.json")
    worksheet = os.getenv("GARMIN_WORKSHEET_NAME", "Garmin")

    if not email or not password or not sheet_id:
        log.error("Не хватает переменных в .env (GARMIN_EMAIL / GARMIN_PASSWORD / GOOGLE_SHEET_ID).")
        return 1

    sa_abs = (ROOT / sa_path).resolve() if not os.path.isabs(sa_path) else Path(sa_path)
    if not args.dry_run and not sa_abs.exists():
        log.error(f"Service account JSON не найден: {sa_abs}")
        return 1

    target_date = args.date or (date.today() - timedelta(days=1)).isoformat()
    log.info(f"=== Garmin sync: {target_date} ===")

    try:
        client = login_with_backoff(email, password)
        data = fetch_garmin_data(client, target_date)
        log.info(
            f"Сон: {data['sleep_hours']}ч, Score: {data['sleep_score']}, "
            f"HRV: {data['hrv_last_night']}, Шаги: {data['steps']}, "
            f"Стресс: {data['stress_avg']}, BB: {data['body_battery_max']}/{data['body_battery_min']}"
        )

        if args.dry_run:
            log.info("DRY RUN — в Sheets не пишем.")
        else:
            write_to_sheet(data, sheet_id, worksheet, str(sa_abs))

        log.info("ГОТОВО!")
        return 0
    except Exception as e:
        log.error(f"Ошибка: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
