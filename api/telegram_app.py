"""Single Vercel entrypoint for the Telegram bot.

Routes public Telegram webhook traffic, setup, and the persistent voting tick.
"""
from __future__ import annotations

from typing import Any


def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
    path = str(environ.get("PATH_INFO") or environ.get("REQUEST_URI") or "")
    normalized = path.split("?", 1)[0].rstrip("/")

    if normalized.endswith("/setup"):
        from api.telegram.setup import app as setup_app
        return setup_app(environ, start_response)

    if normalized.endswith("/tick"):
        from api.telegram.tick import app as tick_app
        return tick_app(environ, start_response)

    from api.telegram.webhook import app as webhook_app
    return webhook_app(environ, start_response)


handler = app
