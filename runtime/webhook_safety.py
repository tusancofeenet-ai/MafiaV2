from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from aiogram import types
from aiogram.dispatcher.middlewares import BaseMiddleware


class UpdateLatencyMiddleware(BaseMiddleware):
    """Measure complete Telegram update latency without changing handler flow."""

    async def on_pre_process_update(self, update: types.Update, data: dict[str, Any]):
        data["_mafia_started_at"] = time.perf_counter()

    async def on_post_process_update(self, update: types.Update, result: Any, data: dict[str, Any]):
        started = data.get("_mafia_started_at")
        if started is None:
            return
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        kind = "callback" if update.callback_query else "message" if update.message else "other"
        logging.info("latency.update kind=%s update_id=%s total_ms=%.1f", kind, getattr(update, "update_id", "-"), elapsed_ms)


def install_latency(dp) -> bool:
    if getattr(dp, "_mafia_latency_installed", False):
        return False
    dp.middleware.setup(UpdateLatencyMiddleware())
    dp._mafia_latency_installed = True
    logging.info("latency middleware installed")
    return True


def install_safe_callback_answer() -> bool:
    """Make callback.answer() best-effort so expired Telegram callbacks never 500 a webhook."""
    if getattr(types.CallbackQuery, "_mafia_safe_answer", False):
        return False
    original = types.CallbackQuery.answer

    async def safe_answer(self, *args, **kwargs):
        try:
            return await original(self, *args, **kwargs)
        except (asyncio.TimeoutError, OSError) as exc:
            logging.warning("callback.answer transport failure ignored: %s", exc)
            return None
        except Exception as exc:
            # Telegram can reject stale/expired callback queries. The callback
            # action itself must not turn that benign UI failure into HTTP 500.
            logging.warning("callback.answer failure ignored: %s", exc)
            return None

    types.CallbackQuery.answer = safe_answer
    types.CallbackQuery._mafia_safe_answer = True
    logging.info("safe callback.answer installed")
    return True
