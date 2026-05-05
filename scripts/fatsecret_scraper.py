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
# Persistent Chrome user-data-dir — сохраняем cookies сессии FS между запусками,
# чтобы не логиниться (и не проходить CAPTCHA) каждый раз. После первого
# успешного ручного логина cookies живут в этой папке.
CHROME_PROFILE_DIR = DATA_DIR / "chrome_profile"
CHROME_PROFILE_DIR.mkdir(exist_ok=True)

LOGIN_URL = "https://www.fatsecret.com/Auth.aspx?pa=s"
# pa=fj — настоящая Food Diary (раздел "Food", "View Food Diary").
# pa=fjrd, который мы использовали раньше, — это My Fatsecret feed: он
# игнорирует параметр dt и всегда показывает агрегаты за сегодняшний
# день + ленту постов, поэтому записи за прошлые даты с него не вытащить.
DIARY_URL_TPL = "https://www.fatsecret.com/Diary.aspx?pa=fj&dt={date_int}"

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


def _find_cached_chromedriver() -> str | None:
    """Ищет уже скачанный chromedriver в кеше webdriver-manager (~/.wdm).
    Если есть — возвращает путь к самой свежей версии. Это позволяет работать
    в офлайне или при сетевых проблемах с storage.googleapis.com.
    """
    home = Path.home()
    base = home / ".wdm" / "drivers" / "chromedriver"
    if not base.exists():
        return None
    # Возможные пути для разных платформ:
    # mac64/<version>/chromedriver-mac-x64/chromedriver
    # mac_arm64/<version>/chromedriver-mac-arm64/chromedriver
    # win64/<version>/chromedriver-win64/chromedriver.exe
    candidates = list(base.glob("*/*/chromedriver-*/chromedriver*"))
    candidates = [p for p in candidates if p.is_file() and os.access(p, os.X_OK)]
    if not candidates:
        return None
    # Берём с самой свежей mtime
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return str(candidates[0])


def _unlock_chrome_profile() -> None:
    """Снимает Singleton-локи на Chrome user-profile.

    После предыдущего запуска (особенно если он завершился по Ctrl+C
    или RuntimeError) в `data/chrome_profile/` могут остаться файлы
    SingletonLock / SingletonSocket / SingletonCookie. Если они есть,
    новый Chrome не стартует и selenium виснет на 120 сек.
    """
    for name in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
        try:
            (CHROME_PROFILE_DIR / name).unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            log.warning(f"Не удалось снять лок {name}: {e}")


def make_driver(headless: bool = True, use_profile: bool = True):
    """Создаём selenium driver.

    Сначала пробуем кешированный chromedriver (~/.wdm) — это надёжнее, чем
    каждый раз ходить в сеть за свежей версией. Только если кеша нет —
    скачиваем через webdriver-manager.

    use_profile=False — не использовать persistent profile data/chrome_profile/.
    Нужно для CI (GitHub Actions): там нет сохранённого профиля и не нужен.
    """
    # Снимаем возможные locks с предыдущей зависшей сессии.
    if use_profile:
        _unlock_chrome_profile()
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
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
    # Persistent профиль — cookies живут между запусками, скрипт не будет
    # логиниться повторно (и не нарвётся на CAPTCHA) после первого раза.
    # Отключаем для CI: там профиля нет, cookies подсаживаем из ENV.
    if use_profile:
        options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    # «обычный» user-agent — чтобы не вызвать защиту от ботов
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )

    # 1. Пробуем кешированный chromedriver — без обращения в сеть.
    cached = _find_cached_chromedriver()
    if cached:
        log.info(f"Использую кешированный chromedriver: {cached}")
        try:
            service = Service(cached)
            return webdriver.Chrome(service=service, options=options)
        except Exception as e:
            log.warning(f"Кешированный chromedriver не запустился ({e}), пробую скачать свежий.")

    # 2. Fallback: скачиваем через webdriver-manager.
    try:
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        log.error(
            "Кеша нет, а webdriver-manager не установлен:\n"
            "    python3.11 -m pip install webdriver-manager --break-system-packages"
        )
        sys.exit(1)
    try:
        service = Service(ChromeDriverManager().install())
    except Exception as e:
        log.error(
            f"Не удалось скачать chromedriver: {e}\n"
            "Это сетевая проблема (storage.googleapis.com / github недоступен). "
            "Проверь Wi-Fi/VPN и попробуй ещё раз."
        )
        raise
    return webdriver.Chrome(service=service, options=options)


def is_logged_in(driver) -> bool:
    """Простая эвристика: на залогиненной странице FS обычно виден линк
    'My FatSecret' или 'Sign Out', а на гостевой — 'Sign In'.
    """
    try:
        page = driver.page_source.lower()
        return ("sign out" in page or "logout" in page) and "ctl00$body$email" not in page
    except Exception:
        return False


def _save_debug_html(driver, label: str) -> None:
    """Сохраняет HTML текущей страницы для диагностики (когда не нашли селектор).
    label — короткий тег для имени файла, например 'login' или 'login_failed'.
    """
    try:
        path = DATA_DIR / f"fatsecret_{label}.html"
        path.write_text(driver.page_source, encoding="utf-8")
        log.info(f"HTML страницы '{label}' сохранён: {path}  (URL={driver.current_url})")
    except Exception as e:
        log.warning(f"Не удалось сохранить HTML '{label}': {e}")


def _try_dismiss_cookie_banner(driver) -> None:
    """FS может показывать GDPR cookie-баннер, перекрывающий форму логина.
    Пробуем найти и закрыть.
    """
    from selenium.webdriver.common.by import By
    candidates = [
        # Кнопки "Accept" / "Agree" — английский, регистронезависимо
        (By.XPATH, "//button[contains(translate(., 'ACEPGRT', 'acepgrt'), 'accept')]"),
        (By.XPATH, "//button[contains(translate(., 'ACEPGRT', 'acepgrt'), 'agree')]"),
        # Русский
        (By.XPATH, "//button[contains(., 'Принять') or contains(., 'Согласен') or contains(., 'Согласна')]"),
        # Common ID/class patterns
        (By.CSS_SELECTOR, "button[id*='accept' i]"),
        (By.CSS_SELECTOR, "button[class*='accept' i]"),
        (By.CSS_SELECTOR, "#onetrust-accept-btn-handler"),
        (By.CSS_SELECTOR, ".cookie-accept, .cc-accept, .gdpr-accept"),
    ]
    for by, sel in candidates:
        try:
            btn = driver.find_element(by, sel)
            if btn.is_displayed():
                log.info(f"Закрываю cookie/GDPR-баннер ({sel})")
                btn.click()
                time.sleep(1)
                return
        except Exception:
            continue


def _is_email_confirmation_page(driver) -> bool:
    """FS показывает 'Account confirmation required' пока email не подтверждён.
    Возвращает True если мы на этой странице.
    """
    try:
        page = (driver.page_source or "").lower()
        return (
            "account confirmation required" in page
            or "you need to verify your account" in page
            or "registration success" in page
        )
    except Exception:
        return False


def _trigger_resend_confirmation(driver) -> bool:
    """На странице 'Account confirmation required' есть линк 'click here'
    для повторной отправки подтверждения. Это ASP.NET postback
    (javascript:__doPostBack(...)). Найдём и кликнем — FS отправит свежее
    письмо на email аккаунта.
    Возвращает True если клик прошёл.
    """
    from selenium.webdriver.common.by import By
    log.info("Ищу линк 'request another one' для повторной отправки письма...")
    candidates = [
        # Конкретный линк который виден в HTML — javascript postback
        (By.XPATH, "//a[contains(@href, '__doPostBack') and (contains(., 'here') or contains(., 'click'))]"),
        (By.XPATH, "//a[contains(translate(., 'CLIKHER', 'clikher'), 'click here')]"),
        (By.XPATH, "//a[contains(., 'request another') or contains(., 'resend')]"),
        (By.CSS_SELECTOR, "a[href*='__doPostBack']"),
    ]
    for by, sel in candidates:
        try:
            link = driver.find_element(by, sel)
            if link.is_displayed():
                log.info(f"Кликаю resend-линк: {sel!r}")
                link.click()
                time.sleep(3)
                _save_debug_html(driver, "after_resend")
                return True
        except Exception:
            continue
    log.warning("Линк resend на странице confirmation не найден.")
    return False


def _find_field(driver, kind: str):
    """Ищет input-поле на странице логина по набору эвристик.
    kind: 'email' | 'password'
    Возвращает WebElement или None.
    """
    from selenium.webdriver.common.by import By
    if kind == "email":
        selectors = [
            (By.NAME, "ctl00$Body$Email"),
            (By.ID, "ctl00_Body_Email"),
            (By.CSS_SELECTOR, "input[type='email']"),
            (By.CSS_SELECTOR, "input[autocomplete='email']"),
            (By.CSS_SELECTOR, "input[autocomplete='username']"),
            (By.CSS_SELECTOR, "input[name*='email' i]"),
            (By.CSS_SELECTOR, "input[id*='email' i]"),
            (By.XPATH, "//input[contains(@placeholder, 'mail') or contains(@placeholder, 'Mail')]"),
            (By.XPATH, "//input[@name='username' or @id='username']"),
        ]
    elif kind == "password":
        selectors = [
            (By.NAME, "ctl00$Body$Password"),
            (By.ID, "ctl00_Body_Password"),
            (By.CSS_SELECTOR, "input[type='password']"),
            (By.CSS_SELECTOR, "input[autocomplete='current-password']"),
            (By.CSS_SELECTOR, "input[autocomplete='password']"),
            (By.CSS_SELECTOR, "input[name*='password' i]"),
            (By.CSS_SELECTOR, "input[id*='password' i]"),
        ]
    else:
        return None
    for by, sel in selectors:
        try:
            el = driver.find_element(by, sel)
            if el.is_displayed() and el.is_enabled():
                log.info(f"{kind}-поле найдено: {by}={sel!r}")
                return el
        except Exception:
            continue
    return None


def login(driver, email: str, password: str) -> None:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    log.info("Открываю страницу FS, проверяю не залогинены ли уже из профиля...")
    driver.get("https://www.fatsecret.com/")
    time.sleep(2)
    if is_logged_in(driver):
        log.info("Уже залогинены (cookies из chrome_profile). Логин пропускаю.")
        return

    log.info("Логинимся в FatSecret...")
    driver.get(LOGIN_URL)
    time.sleep(2)

    # Закрываем cookie/GDPR-баннер, если он перекрывает форму
    _try_dismiss_cookie_banner(driver)

    # Если после клика по login URL нас всё равно вынесло на залогиненную страницу
    # (например, FS сам редиректнул) — выходим.
    if is_logged_in(driver):
        log.info("FS сам редиректнул на залогиненную страницу. Логин не нужен.")
        return

    # Сохраняем HTML страницы логина — пригодится для диагностики, если поля не найдены
    _save_debug_html(driver, "login")

    # Проверка: вдруг Chrome показал свою error-page (ERR_TIMED_OUT, DNS_FAIL и т.п.) —
    # тогда это не FS-проблема, а сеть. Дадим осмысленное сообщение.
    page_lower = (driver.page_source or "").lower()
    if any(marker in page_lower for marker in [
        "err_timed_out", "err_connection", "err_name_not_resolved",
        "this site can", "не удается получить доступ", "dns_probe",
    ]):
        log.error(
            "Chrome не смог загрузить страницу FS — это сетевая проблема, не FS. "
            f"URL: {driver.current_url}. Проверь VPN/Wi-Fi и доступность сайта в Safari."
        )
        # Окно остаётся открытым 30 секунд — успеешь посмотреть, что там
        time.sleep(30)
        raise RuntimeError("Сеть не пускает на FS. См. лог выше.")

    # Ищем поля по расширенному набору селекторов (FS мог поменять вёрстку)
    email_field = _find_field(driver, "email")
    password_field = _find_field(driver, "password")
    if not email_field or not password_field:
        _save_debug_html(driver, "login_failed")
        # Даём 20 секунд чтобы успеть посмотреть страницу или кликнуть руками
        log.warning("Поля не найдены. Окно Chrome остаётся открытым 20 сек — можешь посмотреть/кликнуть.")
        time.sleep(20)
        raise RuntimeError(
            "Не нашёл поля email/password на странице логина FS. "
            f"HTML страницы сохранён в {DATA_DIR}/fatsecret_login_failed.html — "
            "пришли его в чат, я подберу селекторы под актуальную вёрстку. "
            f"(URL: {driver.current_url})"
        )

    email_field.send_keys(email)
    password_field.send_keys(password)

    # Кнопка submit — может быть разной
    submit = None
    for selector in [
        (By.NAME, "ctl00$Body$LoginBtn"),
        (By.CSS_SELECTOR, "input[type='submit']"),
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH, "//button[contains(translate(., 'SIGNLOUE', 'signloue'), 'sign in') or contains(translate(., 'SIGNLOUE', 'signloue'), 'log in')]"),
        (By.XPATH, "//input[@type='button' and (contains(@value, 'Sign') or contains(@value, 'Log'))]"),
    ]:
        try:
            el = driver.find_element(*selector)
            if el.is_displayed() and el.is_enabled():
                submit = el
                log.info(f"Кнопка Login найдена: {selector!r}")
                break
        except Exception:
            continue
    if not submit:
        _save_debug_html(driver, "login_no_submit")
        raise RuntimeError(
            "Не нашёл кнопку Login. HTML сохранён в data/fatsecret_login_no_submit.html"
        )
    submit.click()

    # Ждём редирект — главная или member page
    time.sleep(4)

    # Случай 1: остались на login URL — креды не подошли или CAPTCHA
    if "auth.aspx" in driver.current_url.lower() and not _is_email_confirmation_page(driver):
        raise RuntimeError(
            f"Логин не прошёл (URL после submit: {driver.current_url}). "
            "Проверь email/password в .env. Если корректные — возможно FS показал CAPTCHA: "
            "запусти с --no-headless чтобы пройти CAPTCHA вручную."
        )

    # Случай 2: попали на 'Account confirmation required' — email не подтверждён.
    # Автоматически жмём 'request another one', чтобы FS прислал свежее письмо.
    if _is_email_confirmation_page(driver):
        log.warning("FS требует подтверждение email — мы на странице 'Account confirmation required'.")
        clicked = _trigger_resend_confirmation(driver)
        if clicked:
            log.info("Resend-клик отправлен. FS должен был выслать свежее письмо.")
        log.info("Окно Chrome остаётся открытым 90 секунд — успей попросить владельца почты "
                 "проверить ящик и кликнуть ссылку verify в письме.")
        time.sleep(90)
        raise RuntimeError(
            "Аккаунт FS не подтверждён по email. Свежее письмо отправлено на ящик аккаунта. "
            "Попроси владельца почты кликнуть ссылку verify, потом перезапусти скрипт."
        )

    log.info(f"Логин успешен. URL: {driver.current_url}")


def login_with_cookies(driver, cookies_json: str) -> None:
    """Альтернативный путь логина — через сохранённые cookies (CI mode).

    На GitHub Actions нет persistent Chrome profile и нет возможности
    пройти CAPTCHA / email confirmation. Вместо этого логинимся один раз
    локально, выгружаем cookies через scripts/fatsecret_export_cookies.py
    и кладём их в GitHub Secret FATSECRET_COOKIES_JSON. CI подхватывает
    переменную окружения и подсаживает cookies в свежий Chrome.
    """
    import json
    log.info("Логинюсь через cookies из ENV (CI mode)...")
    try:
        cookies = json.loads(cookies_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"FATSECRET_COOKIES_JSON не парсится как JSON: {e}")

    # Selenium add_cookie работает только если мы уже на нужном домене.
    driver.get("https://www.fatsecret.com/")
    time.sleep(2)

    added, failed = 0, 0
    for c in cookies:
        # add_cookie не понимает sameSite=None и ряд служебных полей.
        c.pop("sameSite", None)
        c.pop("storeId", None)
        c.pop("hostOnly", None)
        c.pop("session", None)
        # expirationDate (формат Chrome DevTools) → expiry (selenium).
        if "expirationDate" in c and "expiry" not in c:
            c["expiry"] = int(c.pop("expirationDate"))
        try:
            driver.add_cookie(c)
            added += 1
        except Exception as e:
            failed += 1
            log.warning(f"cookie '{c.get('name')}' не подсадился: {e}")

    log.info(f"Подсажено cookies: {added} (ошибок: {failed})")
    # Перезагружаем страницу — теперь FS должен считать нас залогиненными.
    driver.get("https://www.fatsecret.com/")
    time.sleep(2)
    if not is_logged_in(driver):
        raise RuntimeError(
            "Cookies не сработали — FS не считает залогиненным. "
            "Скорее всего они истекли. Обнови их локально через "
            "scripts/fatsecret_export_cookies.py и положи свежий JSON "
            "в GitHub Secret FATSECRET_COOKIES_JSON."
        )
    log.info(f"Cookies приняты, залогинены. URL: {driver.current_url}")


def fetch_diary(driver, target_date: str) -> list[dict]:
    """Парсит страницу food diary за указанную дату.

    FS Diary URL: /Diary.aspx?pa=fj&dt={days_since_epoch}
    Структура: 4 блока приёмов пищи (Breakfast / Lunch / Dinner / Other),
    в каждом — список продуктов в `<table class="foodsNutritionTbl">`,
    и итоги в `<td class="sub" title="Total Breakfast Fat: 15.69g">` и т.д.
    Парсим именно эти `title`-атрибуты — они однозначно
    идентифицируемы, в отличие от позиций колонок.
    """
    from selenium.webdriver.common.by import By

    date_int = fs_date_int(target_date)
    url = DIARY_URL_TPL.format(date_int=date_int)
    log.info(f"Открываю diary URL: {url}")
    driver.get(url)
    time.sleep(2.5)  # подождать рендера

    html = driver.page_source

    # 1. Итоги по приёмам пищи через title-атрибуты <td class="sub">.
    # Имя приёма — Breakfast / Lunch / Dinner / Other.
    # NB: FS пишет "Carbohyrates" (с опечаткой) — оставляем как есть.
    # Хронологический порядок (как в приложении), плюс русские подписи для лога.
    MEAL_ORDER = [
        ("Breakfast", "Завтрак"),
        ("Lunch",     "Обед"),
        ("Dinner",    "Ужин"),
        ("Other",     "Перекус"),
    ]
    found_in_html = set(re.findall(r"Total (\w+) Calories:", html))
    meals = []
    for meal_en, meal_ru in MEAL_ORDER:
        if meal_en not in found_in_html:
            continue

        def _grab(metric: str, unit: str, m=meal_en) -> float:
            mt = re.search(
                rf"Total {re.escape(m)} {metric}:\s*(\d+(?:\.\d+)?){unit}",
                html,
            )
            return float(mt.group(1)) if mt else 0.0

        meal_data = {
            "meal":          meal_en,
            "meal_ru":       meal_ru,
            "calories_kcal": _grab("Calories", "kcal"),
            "fat_g":         _grab("Fat", "g"),
            "carbs_g":       _grab("Carbohyrates", "g"),
            "protein_g":     _grab("Protein", "g"),
        }
        meals.append(meal_data)
        log.info(
            f"  {meal_ru:<8} {meal_data['calories_kcal']:>4.0f} kcal · "
            f"Б {meal_data['protein_g']:>5.1f} / "
            f"Ж {meal_data['fat_g']:>5.1f} / "
            f"У {meal_data['carbs_g']:>5.1f}"
        )

    # 2. Сколько отдельных продуктов добавлено за день — по числу
    # таблиц `foodsNutritionTbl` (каждая = одна запись еды).
    try:
        items = driver.find_elements(By.CSS_SELECTOR, "table.foodsNutritionTbl")
        items_count = len(items)
    except Exception:
        items_count = 0

    # 3. Cross-check: общий kcal из шапки страницы.
    header_match = re.search(
        r'<span class="subheading"[^>]*>(\d+(?:\.\d+)?)\s*kcal</span>\s*<span class="normal">RDI',
        html,
    )
    header_total_kcal: float | None = (
        float(header_match.group(1)) if header_match else None
    )
    sum_meals_kcal = sum(m["calories_kcal"] for m in meals)
    if header_total_kcal is not None:
        delta = abs(header_total_kcal - sum_meals_kcal)
        if delta <= 1.0:
            log.info(
                f"Сходится: шапка {header_total_kcal:.0f} kcal == "
                f"сумма приёмов {sum_meals_kcal:.0f} kcal"
            )
        else:
            log.warning(
                f"Расхождение: шапка {header_total_kcal:.0f} kcal vs "
                f"сумма приёмов {sum_meals_kcal:.0f} kcal (Δ={delta:.0f})"
            )

    log.info(f"Найдено приёмов пищи: {len(meals)}, продуктов: {items_count}")

    # Прикрепим items_count к первой записи — aggregate_entries его подхватит.
    if meals:
        meals[0]["_items_count"] = items_count
    return meals


def aggregate_entries(entries: list[dict]) -> dict:
    """Суммируем КБЖУ по приёмам пищи.

    На вход приходит список meal-итогов из fetch_diary (по одному на
    Breakfast/Lunch/Dinner/Other). Просто складываем — числа уже
    нормализованы по FS-разметке.
    Fiber FS не отдаёт в Diary view — оставляем 0.
    """
    totals = {"calories_kcal": 0.0, "protein_g": 0.0, "fat_g": 0.0, "carbs_g": 0.0, "fiber_g": 0.0}
    items_count = 0
    for e in entries:
        totals["calories_kcal"] += e.get("calories_kcal", 0.0)
        totals["protein_g"]     += e.get("protein_g", 0.0)
        totals["fat_g"]         += e.get("fat_g", 0.0)
        totals["carbs_g"]       += e.get("carbs_g", 0.0)
        items_count             += e.get("_items_count", 0)

    return {
        "calories_kcal": round(totals["calories_kcal"], 1),
        "protein_g":     round(totals["protein_g"], 1),
        "fat_g":         round(totals["fat_g"], 1),
        "carbs_g":       round(totals["carbs_g"], 1),
        "fiber_g":       round(totals["fiber_g"], 1),
        "entries_count": items_count,
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
    parser.add_argument("--date", help="Дата YYYY-MM-DD (по умолчанию вчера). С --days это последняя дата диапазона.")
    parser.add_argument("--days", type=int, default=1, help="Сколько дней подряд бэкфилить, заканчивая --date (по умолчанию 1).")
    parser.add_argument("--dry-run", action="store_true", help="Не писать в Sheets")
    parser.add_argument("--no-headless", action="store_true", help="Показать окно Chrome (для отладки CAPTCHA)")
    parser.add_argument("--debug-html", action="store_true", help="Сохранить HTML diary в data/")
    args = parser.parse_args()

    if args.days < 1:
        log.error("--days должен быть >= 1")
        return 1

    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        log.warning("python-dotenv не установлен")

    # Два режима логина:
    # 1. CI: FATSECRET_COOKIES_JSON задан → подсаживаем cookies, никакого
    #    логина email/password (CAPTCHA + email confirmation пройти нельзя).
    # 2. Local: используем persistent Chrome profile + email/password.
    cookies_json = os.getenv("FATSECRET_COOKIES_JSON")
    use_cookies = bool(cookies_json)
    email = os.getenv("FATSECRET_EMAIL")
    password = os.getenv("FATSECRET_PASSWORD")
    if not use_cookies and (not email or not password):
        log.error(
            "Логиниться нечем: ни FATSECRET_COOKIES_JSON, "
            "ни FATSECRET_EMAIL/FATSECRET_PASSWORD не заданы."
        )
        return 1

    end_date_str = args.date or (date.today() - timedelta(days=1)).isoformat()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    # Список дат от старой к новой — так в Sheets пойдёт хронологический порядок.
    dates = [
        (end_date - timedelta(days=offset)).isoformat()
        for offset in range(args.days - 1, -1, -1)
    ]
    if args.days > 1:
        log.info(f"Бэкфилл {args.days} дней: {dates[0]} … {dates[-1]}")
    else:
        log.info(f"Дата: {dates[0]}")

    # Подготовим Sheets-параметры заранее, чтобы один раз создать клиента.
    sheet_id = None
    sa_path = None
    if not args.dry_run:
        sheet_id = os.getenv("GOOGLE_SHEET_ID")
        sa_rel = os.getenv("GOOGLE_SERVICE_ACCOUNT_PATH", ".secrets/service-account.json")
        if not sheet_id:
            log.error("GOOGLE_SHEET_ID не задан в .env")
            return 1
        sa_path = (ROOT / sa_rel).resolve()
        if not sa_path.exists():
            log.error(f"Service account не найден: {sa_path}")
            return 1

    # В CI (cookies из ENV) не используем persistent profile — его там нет.
    driver = make_driver(headless=not args.no_headless, use_profile=not use_cookies)
    ok, failed = 0, []
    try:
        if use_cookies:
            login_with_cookies(driver, cookies_json)
        else:
            login(driver, email, password)

        for i, target_date in enumerate(dates, 1):
            log.info("─" * 60)
            log.info(f"[{i}/{len(dates)}] {target_date}")
            try:
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
                else:
                    write_to_sheet(agg, sheet_id, "fatsecret_daily", str(sa_path))

                ok += 1
            except Exception as e:
                # Падение на одном дне не должно валить весь бэкфилл.
                log.exception(f"Ошибка на дате {target_date}: {e}")
                failed.append(target_date)

            # Небольшая пауза между днями, чтобы не нагружать FS.
            if i < len(dates):
                time.sleep(1.5)

        log.info("─" * 60)
        if failed:
            log.warning(f"Готово с ошибками. Успешно: {ok}/{len(dates)}. Не удалось: {failed}")
            return 2
        log.info(f"Готово. Обработано дней: {ok}/{len(dates)}.")
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
