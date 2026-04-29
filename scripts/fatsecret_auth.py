"""
FatSecret OAuth 1.0a setup — одноразовая авторизация user-аккаунта.

Запускается один раз. Получает request_token, открывает браузер с
authorize URL, ждёт PIN-код от FatSecret, обменивает на access_token,
сохраняет в .secrets/fatsecret_token.json.

Использование:
    python3.11 scripts/fatsecret_auth.py

Перед запуском:
    1. .env содержит FATSECRET_CONSUMER_KEY / FATSECRET_CONSUMER_SECRET
       (получены на platform.fatsecret.com → My Apps → твой app).
    2. В настройках приложения на FS Platform указан Callback URL: oob
       (out-of-band) — это режим, где FS показывает PIN на странице
       вместо редиректа.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import webbrowser
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("fatsecret_auth")

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"
TOKEN_PATH = ROOT / ".secrets" / "fatsecret_token.json"

FS_REQUEST_URL = "https://oauth.fatsecret.com/oauth/request_token"
FS_AUTHORIZE_URL = "https://www.fatsecret.com/oauth/authorize"
FS_ACCESS_URL = "https://oauth.fatsecret.com/oauth/access_token"


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ENV_PATH)
    except ImportError:
        log.warning("python-dotenv не установлен")

    try:
        from requests_oauthlib import OAuth1Session
    except ImportError:
        log.error(
            "Нужен пакет requests-oauthlib. Установи:\n"
            "    python3.11 -m pip install requests-oauthlib --break-system-packages"
        )
        return 1

    consumer_key = os.getenv("FATSECRET_CONSUMER_KEY")
    consumer_secret = os.getenv("FATSECRET_CONSUMER_SECRET")
    if not consumer_key or not consumer_secret:
        log.error(
            "FATSECRET_CONSUMER_KEY / FATSECRET_CONSUMER_SECRET не заданы в .env\n"
            "Получи их на https://platform.fatsecret.com → My Apps."
        )
        return 1

    # 1. Request token (callback=oob — out-of-band, FS покажет PIN)
    log.info("Шаг 1/3: запрашиваю request_token у FatSecret...")
    oauth = OAuth1Session(consumer_key, client_secret=consumer_secret, callback_uri="oob")
    fetch_response = oauth.fetch_request_token(FS_REQUEST_URL)
    request_token = fetch_response.get("oauth_token")
    request_token_secret = fetch_response.get("oauth_token_secret")
    if not request_token:
        log.error(f"Не получил request_token. Ответ: {fetch_response}")
        return 1

    # 2. Открываем browser, пользователь авторизуется и получает PIN
    auth_url = oauth.authorization_url(FS_AUTHORIZE_URL)
    log.info(f"Шаг 2/3: открываю браузер для авторизации:\n  {auth_url}")
    log.info("Залогинься в FatSecret своим user-аккаунтом, разреши доступ.")
    log.info("На итоговой странице FS покажет PIN-код (4–6 цифр) — скопируй его сюда.")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass  # если браузер не открылся — пользователь скопирует URL руками

    pin = input("\nВведи PIN от FatSecret: ").strip()
    if not pin:
        log.error("PIN пустой, отменяю.")
        return 1

    # 3. Обмениваем PIN на access_token
    log.info("Шаг 3/3: обмениваю PIN на access_token...")
    oauth = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=request_token,
        resource_owner_secret=request_token_secret,
        verifier=pin,
    )
    access_token_data = oauth.fetch_access_token(FS_ACCESS_URL)

    access_token = access_token_data.get("oauth_token")
    access_token_secret = access_token_data.get("oauth_token_secret")
    if not access_token:
        log.error(f"Не получил access_token. Ответ: {access_token_data}")
        return 1

    # Сохраняем токен
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(json.dumps({
        "oauth_token": access_token,
        "oauth_token_secret": access_token_secret,
    }, indent=2))
    log.info(f"✅ User-токен сохранён в {TOKEN_PATH}")
    log.info("Теперь можно запускать: python3.11 scripts/fatsecret_sync.py")
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
