"""Temporary authenticated Telegram webhook setup endpoint.

Uses the setup secret from the HTTP Authorization header to avoid leaking
credentials into URLs and access logs. Remove this endpoint after setup.
"""
from __future__ import annotations

import hmac
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def _response(body: dict, status: str = "200 OK") -> tuple[str, list[tuple[str, str]], bytes]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload))), ("Cache-Control", "no-store")], payload


def _authorized(environ: dict) -> bool:
    expected = os.getenv("TELEGRAM_SETUP_SECRET")
    supplied = str(environ.get("HTTP_AUTHORIZATION") or "")
    prefix = "Bearer "
    if not expected or not supplied.startswith(prefix):
        return False
    token = supplied[len(prefix):]
    return bool(token) and hmac.compare_digest(token, expected)


def _telegram_request(token: str, method: str, payload: dict | None = None) -> dict:
    request = Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def app(environ: dict, start_response) -> list[bytes]:
    if str(environ.get("REQUEST_METHOD", "GET")).upper() != "GET":
        status, headers, body = _response({"ok": False, "error": "method_not_allowed"}, "405 Method Not Allowed")
        start_response(status, headers)
        return [body]
    if not _authorized(environ):
        status, headers, body = _response({"ok": False, "error": "unauthorized"}, "401 Unauthorized")
        start_response(status, headers)
        return [body]

    token = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("API_TOKEN")
    webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL")
    if not token or not webhook_url:
        status, headers, body = _response({"ok": False, "error": "telegram_configuration_missing"}, "500 Internal Server Error")
        start_response(status, headers)
        return [body]

    payload = {"url": webhook_url}
    webhook_secret = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if webhook_secret:
        payload["secret_token"] = webhook_secret

    try:
        set_result = _telegram_request(token, "setWebhook", payload)
        info_result = _telegram_request(token, "getWebhookInfo")
    except (HTTPError, URLError, TimeoutError, ValueError):
        status, headers, body = _response({"ok": False, "error": "telegram_api_request_failed"}, "502 Bad Gateway")
        start_response(status, headers)
        return [body]

    info = info_result.get("result", {})
    result = {
        "ok": bool(set_result.get("ok")),
        "set_webhook_ok": bool(set_result.get("ok")),
        "webhook": {
            "url": info.get("url", ""),
            "pending_update_count": info.get("pending_update_count", 0),
            "last_error_date": info.get("last_error_date"),
            "last_error_message": info.get("last_error_message"),
        },
    }
    status, headers, body = _response(result, "200 OK" if result["ok"] else "502 Bad Gateway")
    start_response(status, headers)
    return [body]


handler = app
