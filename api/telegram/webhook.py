"""Vercel-compatible WSGI Telegram webhook entry point for MafiaNights."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

_seen_updates: set[int] = set()
_runtime_module: Any = None
_startup_complete = False


def _response(body: dict[str, Any], status: str = "200 OK") -> tuple[str, list[tuple[str, str]], bytes]:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(payload)))], payload


def _authorized(environ: dict[str, Any]) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET")
    if not expected:
        return True
    actual = environ.get("HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN")
    return actual == expected


def _get_runtime() -> Any:
    """Return the canonical patched production module.

    player_runtime_entry imports main1 and installs the complete production
    patch stack. main1 is an aiogram module container, not a WSGI application,
    so the webhook dispatches through its Dispatcher directly.
    """
    global _runtime_module
    if _runtime_module is None:
        import player_runtime_entry as runtime_entry
        _runtime_module = runtime_entry
    return _runtime_module


async def _ensure_startup() -> None:
    """Run canonical production startup once per warm Vercel instance."""
    global _startup_complete
    if _startup_complete:
        return

    runtime_entry = _get_runtime()
    await runtime_entry.on_startup(runtime_entry.main.dp)
    _startup_complete = True


async def _dispatch(payload: dict[str, Any]) -> None:
    from aiogram import Bot, types

    runtime_entry = _get_runtime()
    await _ensure_startup()
    update = types.Update(**payload)
    Bot.set_current(runtime_entry.main.bot)
    await runtime_entry.main.dp.process_update(update)


def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
    """WSGI application accepted by the Vercel Python runtime."""
    method = str(environ.get("REQUEST_METHOD", "GET")).upper()

    if method == "GET":
        status, headers, body = _response({"ok": True, "service": "mafia-nights-telegram"})
        start_response(status, headers)
        return [body]

    if method != "POST":
        status, headers, body = _response({"ok": False, "error": "method_not_allowed"}, "405 Method Not Allowed")
        start_response(status, headers)
        return [body]

    if not _authorized(environ):
        status, headers, body = _response({"ok": False, "error": "unauthorized"}, "401 Unauthorized")
        start_response(status, headers)
        return [body]

    try:
        length = int(environ.get("CONTENT_LENGTH") or "0")
    except (TypeError, ValueError):
        length = 0

    raw = environ.get("wsgi.input").read(length) if environ.get("wsgi.input") else b""
    try:
        payload = json.loads(raw.decode("utf-8") if isinstance(raw, bytes) else raw or "{}")
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError):
        status, headers, body = _response({"ok": False, "error": "invalid_json"}, "400 Bad Request")
        start_response(status, headers)
        return [body]

    if not isinstance(payload, dict):
        status, headers, body = _response({"ok": False, "error": "invalid_update"}, "400 Bad Request")
        start_response(status, headers)
        return [body]

    update_id = payload.get("update_id")
    if isinstance(update_id, int):
        if update_id in _seen_updates:
            status, headers, body = _response({"ok": True, "duplicate": True})
            start_response(status, headers)
            return [body]
        _seen_updates.add(update_id)
        if len(_seen_updates) > 5000:
            _seen_updates.clear()
            _seen_updates.add(update_id)

    try:
        asyncio.run(_dispatch(payload))
    except Exception:
        import logging
        logging.exception("Telegram webhook dispatch failed")
        status, headers, body = _response({"ok": False, "error": "dispatch_failed"}, "200 OK")
        start_response(status, headers)
        return [body]

    status, headers, body = _response({"ok": True})
    start_response(status, headers)
    return [body]


handler = app
main = app
