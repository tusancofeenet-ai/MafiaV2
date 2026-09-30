import logging
import runpy
import sys
import traceback
from functools import wraps

from aiogram import Bot
from aiogram.dispatcher import Dispatcher


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
# BOT.get_updates
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
        result = await _original_get_updates(
            self,
            *args,
            **kwargs,
        )

        logger.info(
            "[GET_UPDATES] returned count=%d",
            len(result) if result else 0,
        )

        if result:
            for update in result:
                logger.info(
                    "[GET_UPDATES] update_id=%s",
                    getattr(update, "update_id", "?"),
                )

        return result

    except Exception:
        logger.exception("[GET_UPDATES] ERROR")
        raise


Bot.get_updates = _diagnostic_get_updates

logger.info("[DIAGNOSTIC] Bot.get_updates patched")


# ============================================================
# Dispatcher.process_update
# ============================================================

_original_process_update = Dispatcher.process_update


@wraps(_original_process_update)
async def _diagnostic_process_update(
    self,
    update,
    *args,
    **kwargs,
):
    update_id = getattr(
        update,
        "update_id",
        "?",
    )

    logger.info(
        "[INCOMING UPDATE] update_id=%s type=%s",
        update_id,
        type(update).__name__,
    )

    # --------------------------------------------------------
    # Inspect incoming update
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

            handlers_container = getattr(
                self,
                "message_handlers",
                None,
            )

            handlers = getattr(
                handlers_container,
                "handlers",
                None,
            )

            if handlers is None:

                logger.warning(
                    "[HANDLER DIAGNOSTIC] "
                    "message_handlers.handlers NOT FOUND"
                )

            else:

                logger.info(
                    "[HANDLER DIAGNOSTIC] "
                    "message handler count=%d",
                    len(handlers),
                )

                # ------------------------------------------------
                # Dump every registered message handler
                # ------------------------------------------------

                for index, handler in enumerate(handlers):

                    try:

                        # aiogram 2.x normally stores callback
                        # in HandlerObj.handler.
                        callback = getattr(
                            handler,
                            "handler",
                            None,
                        )

                        # Compatibility fallback.
                        if callback is None:
                            callback = getattr(
                                handler,
                                "callback",
                                None,
                            )

                        callback_name = getattr(
                            callback,
                            "__qualname__",
                            repr(callback),
                        )

                        callback_module = getattr(
                            callback,
                            "__module__",
                            "?",
                        )

                        filters = getattr(
                            handler,
                            "filters",
                            None,
                        )

                        filter_details = []

                        if filters:

                            for filter_obj in filters:

                                try:

                                    filter_instance = getattr(
                                        filter_obj,
                                        "filter",
                                        None,
                                    )

                                    if filter_instance is None:

                                        filter_details.append(
                                            {
                                                "type": "?",
                                            }
                                        )

                                        continue

                                    filter_name = type(
                                        filter_instance
                                    ).__name__

                                    filter_info = {
                                        "type": filter_name,
                                    }

                                    # --------------------------------
                                    # Dump useful filter attributes
                                    # --------------------------------

                                    for attr in (
                                        "commands",
                                        "prefixes",
                                        "ignore_case",
                                        "ignore_caption",
                                        "regexp",
                                        "commands_prefix",
                                    ):

                                        if hasattr(
                                            filter_instance,
                                            attr,
                                        ):

                                            try:

                                                value = getattr(
                                                    filter_instance,
                                                    attr,
                                                )

                                                filter_info[attr] = repr(
                                                    value
                                                )

                                            except Exception:
                                                pass

                                    filter_details.append(
                                        filter_info
                                    )

                                except Exception as exc:

                                    filter_details.append(
                                        {
                                            "error": repr(exc),
                                        }
                                    )

                        logger.info(
                            "[HANDLER %03d] "
                            "handler=%s "
                            "module=%s "
                            "filters=%s",
                            index,
                            callback_name,
                            callback_module,
                            filter_details,
                        )

                    except Exception:

                        logger.exception(
                            "[HANDLER %03d] inspection failed",
                            index,
                        )

        elif getattr(
            update,
            "callback_query",
            None,
        ):

            callback = update.callback_query

            logger.info(
                "[UPDATE CALLBACK] "
                "user_id=%s data=%r",
                getattr(
                    callback.from_user,
                    "id",
                    None,
                ),
                getattr(
                    callback,
                    "data",
                    None,
                ),
            )

        elif getattr(
            update,
            "inline_query",
            None,
        ):

            inline = update.inline_query

            logger.info(
                "[UPDATE INLINE] "
                "user_id=%s query=%r",
                getattr(
                    inline.from_user,
                    "id",
                    None,
                ),
                getattr(
                    inline,
                    "query",
                    None,
                ),
            )

        else:

            detected = []

            for name in (
                "edited_message",
                "channel_post",
                "edited_channel_post",
                "my_chat_member",
                "chat_member",
                "poll",
                "poll_answer",
            ):

                if getattr(
                    update,
                    name,
                    None,
                ) is not None:

                    detected.append(name)

            logger.info(
                "[UPDATE OTHER] attributes=%s",
                detected,
            )

    except Exception:

        logger.exception(
            "[UPDATE INSPECT] failed"
        )

    # --------------------------------------------------------
    # Let aiogram actually process the update
    # --------------------------------------------------------

    try:

        result = await _original_process_update(
            self,
            update,
            *args,
            **kwargs,
        )

        logger.info(
            "[PROCESS_UPDATE DONE] "
            "update_id=%s result=%r",
            update_id,
            result,
        )

        return result

    except Exception:

        logger.exception(
            "[PROCESS_UPDATE ERROR] "
            "update_id=%s",
            update_id,
        )

        raise


Dispatcher.process_update = _diagnostic_process_update

logger.info(
    "[DIAGNOSTIC] Dispatcher.process_update patched"
)


# ============================================================
# Dispatcher.start_polling
# ============================================================

_original_start_polling = Dispatcher.start_polling


@wraps(_original_start_polling)
async def _diagnostic_start_polling(
    self,
    *args,
    **kwargs,
):

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

        logger.exception(
            "[DISPATCHER] start_polling ERROR"
        )

        raise


Dispatcher.start_polling = _diagnostic_start_polling

logger.info(
    "[DIAGNOSTIC] Dispatcher.start_polling patched"
)


# ============================================================
# Bot.__init__
# ============================================================

_original_bot_init = Bot.__init__


@wraps(_original_bot_init)
def _diagnostic_bot_init(
    self,
    *args,
    **kwargs,
):

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
            bool(
                getattr(
                    self,
                    "token",
                    None,
                )
            ),
        )

        return result

    except Exception:

        logger.exception(
            "[BOT INIT] ERROR"
        )

        raise


Bot.__init__ = _diagnostic_bot_init

logger.info(
    "[DIAGNOSTIC] Bot.__init__ patched"
)


# ============================================================
# Start production runtime
# ============================================================

logger.info("=" * 70)
logger.info(
    "[DIAGNOSTIC LAUNCHER] "
    "Loading player_runtime_entry.py"
)
logger.info("=" * 70)


try:

    runpy.run_module(
        "player_runtime_entry",
        run_name="__main__",
    )

except KeyboardInterrupt:

    logger.info(
        "[DIAGNOSTIC LAUNCHER] KeyboardInterrupt"
    )

except SystemExit as exc:

    logger.info(
        "[DIAGNOSTIC LAUNCHER] "
        "SystemExit code=%r",
        exc.code,
    )

except Exception:

    logger.error("=" * 70)
    logger.error(
        "[DIAGNOSTIC LAUNCHER] FATAL ERROR"
    )
    logger.error("=" * 70)

    traceback.print_exc()

    raise

finally:

    logger.info("=" * 70)
    logger.info(
        "[DIAGNOSTIC LAUNCHER] "
        "player_runtime_entry.py finished"
    )
    logger.info("=" * 70)
