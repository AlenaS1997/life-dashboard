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
import garth  # модуль, который garminconnect использует под капотом для OAuth
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
    Если токенов нет или они просрочены — возвращает None.

    Разные версии garminconnect по-разному экспонируют внутренний garth-клиент:
    у одних есть атрибут `client.garth`, у других — нет. Поэтому работаем
    напрямую с модулем garth (он же всё равно под капотом у garminconnect)."""
    if not GARTH_TOKENS_DIR.exists() or not any(GARTH_TOKENS_DIR.iterdir()):
        return None
    try:
        log.info(f"Пробую восстановить сессию из {GARTH_TOKENS_DIR} (без логина).")
        # Загружаем oauth1/oauth2 токены в модуль garth
        garth.resume(str(GARTH_TOKENS_DIR))
        # Создаём клиент garminconnect и подсовываем ему уже залогиненный garth
        client = garminconnect.Garmin()
        # В зависимости от версии garminconnect — разные места, куда положить клиент
        if hasattr(client, "garth"):
            client.garth = garth.client
        # Быстрая проверка, что токен живой — любой дешёвый вызов
        _ = client.get_user_profile()
        log.info("Сессия garth валидна — идём без логина.")
        return client
    except Exception as e:
        log.warning(f"Восстановить сессию не получилось ({e}) — логинюсь заново.")
        return None


def _persist_session(client: garminconnect.Garmin) -> None:
    """Сохраняет токены garth, чтобы следующий запуск пропустил логин.

    Пробуем три пути (версия-зависимо):
      1) client.garth.dump(path) — у некоторых новых garminconnect.
      2) модульный garth.save(path) — после login() глобальный garth.client уже залогинен.
      3) ручной fallback — достаём oauth_token напрямую, если что-то из выше сломается.
    """
    try:
        GARTH_TOKENS_DIR.mkdir(parents=True, exist_ok=True)

        # 1) путь через client
        if hasattr(client, "garth") and hasattr(client.garth, "dump"):
            client.garth.dump(str(GARTH_TOKENS_DIR))
            log.info(f"Токены garth сохранены в {GARTH_TOKENS_DIR} (через client.garth).")
            return

        # 2) модульный garth — garminconnect.login() инициализирует garth.client
        if hasattr(garth, "save"):
            garth.save(str(GARTH_TOKENS_DIR))
            log.info(f"Токены garth сохранены в {GARTH_TOKENS_DIR} (через garth.save).")
            return

        # 3) fallback: если у garth есть client.dump
        if hasattr(garth, "client") and hasattr(garth.client, "dump"):
            garth.client.dump(str(GARTH_TOKENS_DIR))
            log.info(f"Токены garth сохранены в {GARTH_TOKENS_DIR} (через garth.client.dump).")
            return

        log.warning("Ни один из способов сохранить токены garth не подошёл к этой версии.")
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


def _ms_to_hhmm_msk(ms: int | None) -> str:
    """UNIX-миллисекунды → строка 'HH:MM' в МСК (+03:00).
    Возвращает пустую строку, если значения нет.
    """
    if not ms:
        return ""
    try:
        from datetime import datetime, timezone, timedelta
        dt_utc = datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
        dt_msk = dt_utc.astimezone(timezone(timedelta(hours=3)))
        return dt_msk.strftime("%H:%M")
    except Exception:
        return ""


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

    # Фазы сна (в минутах) и время отбоя/подъёма (HH:MM в МСК).
    # dto.sleepStartTimestampLocal/GMT приходит в UNIX-миллисекундах.
    deep_min  = round((dto.get("deepSleepSeconds")  or 0) / 60)
    light_min = round((dto.get("lightSleepSeconds") or 0) / 60)
    rem_min   = round((dto.get("remSleepSeconds")   or 0) / 60)
    awake_min = round((dto.get("awakeSleepSeconds") or 0) / 60)
    bedtime   = _ms_to_hhmm_msk(dto.get("sleepStartTimestampGMT"))
    wakeup    = _ms_to_hhmm_msk(dto.get("sleepEndTimestampGMT"))

    return {
        "date": target_date,
        "sleep_hours": round((dto.get("sleepTimeSeconds") or 0) / 3600, 2),
        "sleep_score": (dto.get("sleepScores") or {}).get("overall", {}).get("value") or 0,
        "body_battery_max": bb_max,
        "body_battery_min": bb_min,
        "hrv_last_night": hrv_val,
        "steps": stats.get("totalSteps") or 0,
        "stress_avg": stats.get("averageStressLevel") or 0,
        "deep_sleep_min":  deep_min,
        "light_sleep_min": light_min,
        "rem_sleep_min":   rem_min,
        "awake_sleep_min": awake_min,
        "bedtime":         bedtime,
        "wakeup":          wakeup,
    }


# Заголовки по умолчанию, если вкладка пустая (порядок = как будет записан в первой строке).
# При расширении уже существующей вкладки новые поля допишутся автоматически в write_to_sheet.
DEFAULT_HEADERS = [
    "date",
    "sleep_hours",
    "sleep_score",
    "body_battery_max",
    "body_battery_min",
    "hrv_last_night",
    "steps",
    "stress_avg",
    "deep_sleep_min",
    "light_sleep_min",
    "rem_sleep_min",
    "awake_sleep_min",
    "bedtime",
    "wakeup",
]


def write_to_sheet(data: dict, sheet_id: str, worksheet_name: str, sa_path: str, overwrite: bool = False) -> None:
    """Пишет строку в Google Sheets.
    overwrite=False — не дублирует существующую дату (идемпотентно).
    overwrite=True  — перезаписывает строку с такой же датой
    (нужно при бэкфилле после расширения схемы — например, добавление фаз сна
    к старым строкам)."""
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

    # Если в data появились новые поля (например, добавили фазы сна),
    # которых ещё нет в шапке — дописываем недостающие заголовки в конец
    # первой строки. Так не теряем новые метрики после расширения схемы.
    new_keys = [k for k in DEFAULT_HEADERS if k in data and k not in existing_headers]
    extra_in_data = [k for k in data if k not in DEFAULT_HEADERS and k not in existing_headers]
    if new_keys:
        log.info(f"Расширяю шапку — добавляю новые столбцы: {new_keys}")
        updated_headers = existing_headers + new_keys
        # Обновляем первую строку целиком, чтобы расширить колонки
        ws.update("A1", [updated_headers])
        existing_headers = updated_headers
    if extra_in_data:
        log.warning(f"Данные без заголовков в таблице (не запишутся): {extra_in_data}")
    missing_in_data = [h for h in existing_headers if h not in data]
    if missing_in_data:
        log.warning(f"Заголовки без значений (будут пустыми): {missing_in_data}")

    # Идемпотентность / overwrite: если дата уже записана — либо пропускаем,
    # либо перезаписываем существующую строку.
    all_dates = ws.col_values(1)
    target_date = str(data.get("date", ""))
    row = [data.get(h, "") for h in existing_headers]

    if target_date in all_dates[1:]:
        if not overwrite:
            log.warning(f"Строка за {target_date} уже есть — пропускаю (используй --overwrite чтобы перезаписать).")
            return
        idx = all_dates.index(target_date) + 1  # 1-based, +1 учитывает шапку (col_values возвращает с header'ом)
        last_col_letter = chr(ord("A") + len(existing_headers) - 1) if len(existing_headers) <= 26 else "Z"
        ws.update(f"A{idx}:{last_col_letter}{idx}", [row], value_input_option="USER_ENTERED")
        log.info(f"♻️ Перезаписана строка за {target_date}: {dict(zip(existing_headers, row))}")
    else:
        ws.append_row(row, value_input_option="USER_ENTERED")
        log.info(f"✅ Записана строка: {dict(zip(existing_headers, row))}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Garmin → Google Sheets sync")
    parser.add_argument("--dry-run", action="store_true", help="Не писать в Sheets")
    parser.add_argument("--date", help="Дата YYYY-MM-DD (по умолчанию — вчера). С --days это последняя дата диапазона.")
    parser.add_argument("--days", type=int, default=1, help="Сколько дней подряд бэкфилить, заканчивая --date (по умолчанию 1).")
    parser.add_argument("--overwrite", action="store_true", help="Перезаписать существующие строки (нужно при бэкфилле после расширения схемы).")
    args = parser.parse_args()

    if args.days < 1:
        log.error("--days должен быть >= 1")
        return 1

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

    end_date_str = args.date or (date.today() - timedelta(days=1)).isoformat()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    dates = [(end_date - timedelta(days=offset)).isoformat() for offset in range(args.days - 1, -1, -1)]

    if args.days > 1:
        log.info(f"=== Garmin sync: бэкфилл {args.days} дней: {dates[0]} … {dates[-1]} ===")
    else:
        log.info(f"=== Garmin sync: {dates[0]} ===")

    try:
        client = login_with_backoff(email, password)
        ok, failed = 0, []
        for i, target_date in enumerate(dates, 1):
            if args.days > 1:
                log.info("─" * 60)
                log.info(f"[{i}/{len(dates)}] {target_date}")
            try:
                data = fetch_garmin_data(client, target_date)
                log.info(
                    f"Сон: {data['sleep_hours']}ч (deep {data['deep_sleep_min']}/light {data['light_sleep_min']}/rem {data['rem_sleep_min']}/awake {data['awake_sleep_min']} мин), "
                    f"отбой {data['bedtime'] or '—'} → подъём {data['wakeup'] or '—'}, "
                    f"score {data['sleep_score']}, HRV {data['hrv_last_night']}, "
                    f"шаги {data['steps']}, стресс {data['stress_avg']}, BB {data['body_battery_max']}/{data['body_battery_min']}"
                )

                if args.dry_run:
                    log.info("DRY RUN — в Sheets не пишем.")
                else:
                    write_to_sheet(data, sheet_id, worksheet, str(sa_abs), overwrite=args.overwrite)
                ok += 1
            except Exception as e:
                log.exception(f"Ошибка на дате {target_date}: {e}")
                failed.append(target_date)
            # Небольшая пауза, чтобы не нагружать Garmin API.
            if i < len(dates):
                time.sleep(1.5)

        if failed:
            log.warning(f"Готово с ошибками. Успешно: {ok}/{len(dates)}. Не удалось: {failed}")
            return 2
        log.info(f"ГОТОВО! Обработано дней: {ok}/{len(dates)}.")
        return 0
    except Exception as e:
        log.error(f"Ошибка: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
