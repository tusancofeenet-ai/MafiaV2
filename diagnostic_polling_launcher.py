"""
Temporary diagnostic launcher for MafiaV2.
Logs incoming Telegram updates without exposing message contents or bot tokens.
"""

import logging
import runpy
import sys
from datetime import datetime, timezone

from aiogram import Dispatcher


# --------------------------------------------------
# Logging configuration
# --------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
    force=True,
)

logger = logging.getLogger("polling_diagnostics")


# --------------------------------------------------
# Incoming update diagnostics
# --------------------------------------------------

_original_process_update = Dispatcher.process_update


async def diagnostic_process_update(self, update):
    """Log minimal metadata for each incoming Telegram update."""

    update_id = getattr(update, "update_id", None)

    message = (
        getattr(update, "message", None)
        or getattr(update, "edited_message", None)
        or getattr(update, "channel_post", None)
        or getattr(update, "edited_channel_post", None)
    )

    callback_query = getattr(update, "callback_query", None)

    if message is not None:
        chat = getattr(message, "chat", None)
        user = getattr(message, "from_user", None)

        text = getattr(message, "text", None) or ""
        command = text.strip().split(maxsplit=1)[0][:40] if text.startswith("/") else None

        logger.info(
            "[INCOMING UPDATE] id=%s type=%s chat_type=%s user_id=%s command=%s",
            update_id,
            "message",
            getattr(chat, "type", None),
            getattr(user, "id", None),
            command,
        )

    elif callback_query is not None:
        user = getattr(callback_query, "from_user", None)

        logger.info(
            "[INCOMING UPDATE] id=%s type=%s user_id=%s",
            update_id,
            "callback_query",
            getattr(user, "id", None),
        )

    else:
        logger.info(
            "[INCOMING UPDATE] id=%s type=%s",
            update_id,
            type(update).__name__,
        )

    return await _original_process_update(self, update)


Dispatcher.process_update = diagnostic_process_update


# --------------------------------------------------
# Launch the existing application
# --------------------------------------------------

logger.info("[DIAGNOSTIC LAUNCHER] Starting player_runtime_entry.py")

try:
    runpy.run_module("player_runtime_entry", run_name="__main__")
except Exception:
    logger.exception("[DIAGNOSTIC LAUNCHER] Application terminated with an exception")
    raise
