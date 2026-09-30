# diagnostic_polling_launcher.py

import asyncio
import logging
import runpy
import sys
import traceback
from functools import wraps

from aiogram import Bot
from aiogram.dispatcher import Dispatcher


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
    force=True,
)

logger = logging.getLogger("polling_diagnostics")

logger.info("=" * 70)
logger.info("[DIAGNOSTIC LAUNCHER] Starting player_runtime_entry.py")
logger.info("=" * 70)


# ============================================================
# 1. TRACE BOT.get_updates
# ============================================================

_original_get_updates = Bot.get_updates


@wraps(_original_get_updates)
async def _diagnostic_get_updates(self, *args, **kwargs):
    logger.info(
        "[GET_UPDATES] calling Telegram getUpdates args=%r kwargs=%r",
        args,
        kwargs,
    )

    try:
        result = await _original_get_updates(self, *args, **kwargs)

        logger.info(
            "[GET_UPDATES] returned count=%d",
            len(result) if result else 0,
        )

        if result:
            for update in result:
                try:
                    logger.info(
                        "[GET_UPDATES] update_id=%s",
                        getattr(update, "update_id", "?"),
                    )
                except Exception:
                    logger.exception(
                        "[GET_UPDATES] failed to inspect update"
                    )

        return result

    except Exception:
        logger.exception("[GET_UPDATES] ERROR")
        raise


Bot.get_updates = _diagnostic_get_updates

logger.info("[DIAGNOSTIC] Bot.get_updates patched")


# ============================================================
# 2. TRACE DISPATCHER.process_update
# ============================================================

_original_process_update = Dispatcher.process_update


@wraps(_original_process_update)
async def _diagnostic_process_update(self, update, *args, **kwargs):
    update_id = getattr(update, "update_id", "?")

    logger.info(
        "[INCOMING UPDATE] update_id=%s type=%s",
        update_id,
        type(update).__name__,
    )

    # --------------------------------------------------------
    # Extract useful information from update
    # --------------------------------------------------------

    try:
        if getattr(update, "message", None):
            message = update.message

            logger.info(
                "[UPDATE MESSAGE] chat_id=%s user_id=%s text=%r",
                getattr(message.chat, "id", None),
                getattr(message.from_user, "id", None),
                getattr(message, "text", None),
            )

        elif getattr(update, "callback_query", None):
            callback = update.callback_query

            logger.info(
                "[UPDATE CALLBACK] user_id=%s data=%r",
                getattr(callback.from_user, "id", None),
                getattr(callback, "data", None),
            )

        elif getattr(update, "inline_query", None):
            inline = update.inline_query

            logger.info(
                "[UPDATE INLINE] user_id=%s query=%r",
                getattr(inline.from_user, "id", None),
                getattr(inline, "query", None),
            )

        elif getattr(update, "chat_member", None):
            cm = update.chat_member

            logger.info(
                "[UPDATE CHAT_MEMBER] chat_id=%s user_id=%s",
                getattr(cm.chat, "id", None),
                getattr(cm.from_user, "id", None),
            )

        else:
            logger.info(
                "[UPDATE OTHER] attributes=%s",
                [
                    name
                    for name in (
                        "edited_message",
                        "channel_post",
                        "edited_channel_post",
                        "my_chat_member",
                        "poll",
                        "poll_answer",
                    )
                    if getattr(update, name, None) is not None
                ],
            )

    except Exception:
        logger.exception("[UPDATE INSPECT] failed")

    # --------------------------------------------------------
    # Dispatcher
    # --------------------------------------------------------

    try:
        result = await _original_process_update(
            self,
            update,
            *args,
            **kwargs,
        )

        logger.info(
            "[PROCESS_UPDATE DONE] update_id=%s result=%r",
            update_id,
            result,
        )

        return result

    except Exception:
        logger.exception(
            "[PROCESS_UPDATE ERROR] update_id=%s",
            update_id,
        )
        raise


Dispatcher.process_update = _diagnostic_process_update

logger.info("[DIAGNOSTIC] Dispatcher.process_update patched")


# ============================================================
# 3. TRACE DISPATCHER.start_polling
# ============================================================

_original_start_polling = Dispatcher.start_polling


@wraps(_original_start_polling)
async def _diagnostic_start_polling(self, *args, **kwargs):
    logger.info("=" * 70)
    logger.info("[DISPATCHER] start_polling ENTER")
    logger.info(
        "[DISPATCHER] args=%r kwargs=%r",
        args,
        kwargs,
    )
    logger.info("=" * 70)

    try:
        result = await _original_start_polling(
            self,
            *args,
            **kwargs,
        )

        logger.info(
            "[DISPATCHER] start_polling RETURN result=%r",
            result,
        )

        return result

    except Exception:
        logger.exception("[DISPATCHER] start_polling ERROR")
        raise


Dispatcher.start_polling = _diagnostic_start_polling

logger.info("[DIAGNOSTIC] Dispatcher.start_polling patched")


# ============================================================
# 4. TRACE Bot instance creation
# ============================================================

_original_bot_init = Bot.__init__


def _diagnostic_bot_init(self, *args, **kwargs):
    logger.info(
        "[BOT INIT] creating Bot args=%r kwargs_keys=%s",
        args,
        list(kwargs.keys()),
    )

    try:
        result = _original_bot_init(
            self,
            *args,
            **kwargs,
        )

        logger.info(
            "[BOT INIT] Bot created token_present=%s",
            bool(getattr(self, "token", None)),
        )

        return result

    except Exception:
        logger.exception("[BOT INIT] ERROR")
        raise


Bot.__init__ = _diagnostic_bot_init

logger.info("[DIAGNOSTIC] Bot.__init__ patched")


# ============================================================
# 5. START REAL RUNTIME
# ============================================================

logger.info("=" * 70)
logger.info("[DIAGNOSTIC LAUNCHER] Loading player_runtime_entry.py")
logger.info("=" * 70)

try:
    runpy.run_module(
        "player_runtime_entry",
        run_name="__main__",
    )

except KeyboardInterrupt:
    logger.info("[DIAGNOSTIC LAUNCHER] KeyboardInterrupt")

except SystemExit as exc:
    logger.info(
        "[DIAGNOSTIC LAUNCHER] SystemExit code=%r",
        exc.code,
    )

except Exception:
    logger.error("=" * 70)
    logger.error("[DIAGNOSTIC LAUNCHER] FATAL ERROR")
    logger.error("=" * 70)
    traceback.print_exc()
    raise

finally:
    logger.info("=" * 70)
    logger.info("[DIAGNOSTIC LAUNCHER] player_runtime_entry.py finished")
    logger.info("=" * 70)
