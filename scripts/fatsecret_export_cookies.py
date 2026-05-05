"""
Экспорт cookies fatsecret.com из локального Chrome-профиля.

Зачем нужен:
- На GitHub Actions нельзя пройти FS-логин (CAPTCHA + email confirmation).
- Поэтому логинимся один раз локально (chrome_profile уже хранит сессию),
  выгружаем cookies этим скриптом, кладём JSON в GitHub Secret
  FATSECRET_COOKIES_JSON, а CI-воркфлоу подсаживает их в свежий Chrome.

Использование:
    python3.11 scripts/fatsecret_export_cookies.py

Скрипт:
    1. Откроет Chrome с твоим persistent профилем (data/chrome_profile).
    2. Зайдёт на fatsecret.com, проверит что ты залогинена.
    3. Сохранит ВСЕ cookies fatsecret.com в data/fatsecret_cookies.json.
    4. Распечатает короткий итог.

Дальше:
    cat data/fatsecret_cookies.json | pbcopy   # скопировать содержимое
    → GitHub repo → Settings → Secrets and variables → Actions →
       New repository secret → имя: FATSECRET_COOKIES_JSON, значение: paste.

Cookies FS живут долго (месяцы), но иногда протухают — тогда воркфлоу
упадёт с понятным сообщением, и просто перезапустишь этот скрипт.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Импортируем из основного скрипта — переиспользуем make_driver / is_logged_in.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fatsecret_scraper import (  # noqa: E402
    DATA_DIR,
    DIARY_URL_TPL,
    fs_date_int,
    log,
    make_driver,
)
from datetime import date, timedelta  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main() -> int:
    output_path = DATA_DIR / "fatsecret_cookies.json"

    log.info("Открываю Chrome с локальным профилем (data/chrome_profile)...")
    driver = make_driver(headless=True, use_profile=True)
    try:
        # Открываем настоящий Food Diary за вчера. Если cookies живые —
        # FS отдаст страницу с дневником. Если нет — отредиректит на
        # /Auth.aspx (страницу логина).
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        diary_url = DIARY_URL_TPL.format(date_int=fs_date_int(yesterday))
        log.info(f"Проверяю сессию через {diary_url}")
        driver.get(diary_url)
        time.sleep(3)

        if "auth.aspx" in driver.current_url.lower():
            log.error(
                "FS редиректнул на страницу логина — в локальном профиле нет "
                "активной FS-сессии. Сначала залогинься через основной скрипт "
                "(scripts/fatsecret_scraper.py --no-headless), потом запусти "
                "этот скрипт ещё раз."
            )
            return 1
        log.info(f"Сессия живая (URL: {driver.current_url})")

        # Cookies нужно собирать и с www., и с корневого fatsecret.com —
        # пройдём через оба домена.
        all_cookies = list(driver.get_cookies())
        try:
            driver.get("https://www.fatsecret.com/")
            time.sleep(2)
            for c in driver.get_cookies():
                if c["name"] not in {x["name"] for x in all_cookies}:
                    all_cookies.append(c)
        except Exception:
            pass
        cookies = all_cookies
        # Оставляем только относящиеся к домену fatsecret (на всякий случай).
        cookies = [
            c for c in cookies
            if "fatsecret" in (c.get("domain") or "").lower()
        ]
        if not cookies:
            log.error("Не нашёл ни одного cookie fatsecret.com.")
            return 1

        output_path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2))
        names = sorted({c.get("name", "?") for c in cookies})
        log.info(f"Сохранено cookies: {len(cookies)} → {output_path}")
        log.info(f"Имена: {', '.join(names)}")
        log.info("")
        log.info("Дальше:")
        log.info("  1. cat data/fatsecret_cookies.json | pbcopy")
        log.info("  2. Открой GitHub → Settings → Secrets and variables → Actions")
        log.info("  3. New repository secret → имя FATSECRET_COOKIES_JSON, paste значение.")
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
        log.exception(f"Ошибка экспорта: {e}")
        sys.exit(1)
