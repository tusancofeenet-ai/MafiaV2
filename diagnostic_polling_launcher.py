# diagnostic_polling_launcher.py
#
# Diagnostic launcher for MafiaV2
#
# Purpose:
#   Trace the complete Telegram -> aiogram polling -> Dispatcher.process_update
#   -> handler routing path, with special diagnostics for /start handlers.
#
# This file does NOT replace player_runtime_entry.py.
# It only launches player_runtime_entry.py with diagnostic instrumentation.

import logging
import runpy
import sys
import traceback
from functools import wraps


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)

logger = logging.getLogger("diagnostic_launcher")


# ============================================================
# IMPORT AIROGRAM CLASSES
# ============================================================

try:
    from aiogram import Bot
    from aiogram import Dispatcher

    logger.info(
        "[DIAG BOOT] aiogram imported successfully"
    )

except Exception:
    logger.exception(
        "[DIAG BOOT] failed to import aiogram"
    )
    raise


# ============================================================
# SAVE ORIGINAL METHODS
# ============================================================

_original_bot_init = Bot.__init__
_original_get_updates = Bot.get_updates
_original_process_update = Dispatcher.process_update
_original_start_polling = Dispatcher.start_polling


# ============================================================
# BOT INIT TRACE
# ============================================================

@wraps(_original_bot_init)
def _diagnostic_bot_init(self, *args, **kwargs):

    logger.info(
        "[BOT INIT] Bot.__init__ called"
    )

    try:

        token = None

        if args:
            token = args[0]

        if token is None:
            token = kwargs.get("token")

        if token:
            try:
                token_preview = str(token)[:12] + "..."
            except Exception:
                token_preview = "<unavailable>"
        else:
            token_preview = "<missing>"

        logger.info(
            "[BOT INIT] token=%s",
            token_preview,
        )

    except Exception:
        logger.exception(
            "[BOT INIT] failed to inspect token"
        )

    result = _original_bot_init(
        self,
        *args,
        **kwargs,
    )

    logger.info(
        "[BOT INIT] Bot.__init__ completed"
    )

    return result


Bot.__init__ = _diagnostic_bot_init


# ============================================================
# TELEGRAM getUpdates TRACE
# ============================================================

@wraps(_original_get_updates)
async def _diagnostic_get_updates(
    self,
    *args,
    **kwargs,
):

    logger.info(
        "[GET_UPDATES] calling Telegram getUpdates "
        "offset=%r timeout=%r allowed_updates=%r",
        kwargs.get("offset"),
        kwargs.get("timeout"),
        kwargs.get("allowed_updates"),
    )

    try:

        result = await _original_get_updates(
            self,
            *args,
            **kwargs,
        )

        logger.info(
            "[GET_UPDATES] Telegram returned %d update(s)",
            len(result) if result is not None else 0,
        )

        if result:

            for update in result:

                try:

                    update_id = getattr(
                        update,
                        "update_id",
                        None,
                    )

                    message = getattr(
                        update,
                        "message",
                        None,
                    )

                    text_value = getattr(
                        message,
                        "text",
                        None,
                    )

                    chat = getattr(
                        message,
                        "chat",
                        None,
                    )

                    chat_id = getattr(
                        chat,
                        "id",
                        None,
                    )

                    user = getattr(
                        message,
                        "from_user",
                        None,
                    )

                    user_id = getattr(
                        user,
                        "id",
                        None,
                    )

                    logger.info(
                        "[GET_UPDATES] "
                        "update_id=%r "
                        "chat_id=%r "
                        "user_id=%r "
                        "text=%r",
                        update_id,
                        chat_id,
                        user_id,
                        text_value,
                    )

                except Exception:
                    logger.exception(
                        "[GET_UPDATES] "
                        "failed to inspect update"
                    )

        return result

    except Exception:

        logger.exception(
            "[GET_UPDATES] Telegram getUpdates FAILED"
        )

        raise


Bot.get_updates = _diagnostic_get_updates


# ============================================================
# HANDLER DUMP
# ============================================================

def _dump_message_handlers(dispatcher):

    logger.info(
        "[HANDLERS] inspecting Dispatcher.message_handlers"
    )

    try:

        handlers_container = getattr(
            dispatcher,
            "message_handlers",
            None,
        )

        if handlers_container is None:

            logger.warning(
                "[HANDLERS] message_handlers is None"
            )

            return

        handlers = getattr(
            handlers_container,
            "handlers",
            None,
        )

        if handlers is None:

            logger.warning(
                "[HANDLERS] message_handlers.handlers is None"
            )

            return

        logger.info(
            "[HANDLERS] total message handlers=%d",
            len(handlers),
        )

        for index, handler in enumerate(handlers):

            try:

                callback = getattr(
                    handler,
                    "handler",
                    None,
                )

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
                    None,
                )

                filters = getattr(
                    handler,
                    "filters",
                    None,
                )

                filter_dump = []

                if filters:

                    for filter_obj in filters:

                        try:

                            filter_instance = getattr(
                                filter_obj,
                                "filter",
                                None,
                            )

                            filter_name = (
                                type(filter_instance).__name__
                                if filter_instance is not None
                                else type(filter_obj).__name__
                            )

                            kwargs = getattr(
                                filter_obj,
                                "kwargs",
                                {},
                            )

                            filter_dump.append(
                                {
                                    "type": filter_name,
                                    "kwargs": kwargs,
                                }
                            )

                        except Exception:

                            filter_dump.append(
                                {
                                    "type": "FILTER_INSPECTION_ERROR"
                                }
                            )

                logger.info(
                    "[HANDLER %03d] "
                    "handler=%s "
                    "module=%s "
                    "filters=%r",
                    index,
                    callback_name,
                    callback_module,
                    filter_dump,
                )

            except Exception:

                logger.exception(
                    "[HANDLERS] "
                    "failed inspecting handler=%d",
                    index,
                )

    except Exception:

        logger.exception(
            "[HANDLERS] handler dump FAILED"
        )


# ============================================================
# FILTER MATCH DIAGNOSTIC
# ============================================================

async def _trace_start_filters(
    dispatcher,
    message,
):

    logger.info(
        "[FILTER TRACE] "
        "testing message text=%r",
        getattr(
            message,
            "text",
            None,
        ),
    )

    try:

        handlers_container = getattr(
            dispatcher,
            "message_handlers",
            None,
        )

        handlers = getattr(
            handlers_container,
            "handlers",
            None,
        )

        if not handlers:

            logger.warning(
                "[FILTER TRACE] "
                "no message handlers found"
            )

            return

        for index, handler in enumerate(handlers):

            try:

                callback = getattr(
                    handler,
                    "handler",
                    None,
                )

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

                # فقط _production_start
                if callback_name != "_production_start":
                    continue

                logger.info(
                    "[FILTER TRACE] "
                    "handler=%03d callback=%s",
                    index,
                    callback_name,
                )

                filters = getattr(
                    handler,
                    "filters",
                    None,
                )

                if not filters:

                    logger.info(
                        "[FILTER TRACE] "
                        "handler=%03d has no filters",
                        index,
                    )

                    continue

                for filter_index, filter_obj in enumerate(filters):

                    try:

                        filter_instance = getattr(
                            filter_obj,
                            "filter",
                            None,
                        )

                        filter_kwargs = getattr(
                            filter_obj,
                            "kwargs",
                            {},
                        )

                        filter_name = (
                            type(filter_instance).__name__
                            if filter_instance is not None
                            else "UNKNOWN"
                        )

                        logger.info(
                            "[FILTER TRACE] "
                            "handler=%03d "
                            "filter=%d "
                            "type=%s "
                            "kwargs=%r",
                            index,
                            filter_index,
                            filter_name,
                            filter_kwargs,
                        )

                        if filter_instance is None:

                            logger.info(
                                "[FILTER TRACE] "
                                "handler=%03d "
                                "filter=%d "
                                "NO_FILTER_INSTANCE",
                                index,
                                filter_index,
                            )

                            continue

                        check_method = getattr(
                            filter_instance,
                            "check",
                            None,
                        )

                        if check_method is None:

                            logger.info(
                                "[FILTER TRACE] "
                                "handler=%03d "
                                "filter=%d "
                                "type=%s "
                                "NO_CHECK_METHOD",
                                index,
                                filter_index,
                                filter_name,
                            )

                            continue

                        # ------------------------------------------------
                        # Try check(message, **kwargs)
                        # ------------------------------------------------

                        try:

                            filter_result = await check_method(
                                message,
                                **filter_kwargs,
                            )

                            logger.info(
                                "[FILTER TRACE] "
                                "handler=%03d "
                                "filter=%d "
                                "type=%s "
                                "RESULT=%r",
                                index,
                                filter_index,
                                filter_name,
                                filter_result,
                            )

                            continue

                        except TypeError as first_error:

                            logger.info(
                                "[FILTER TRACE] "
                                "handler=%03d "
                                "filter=%d "
                                "type=%s "
                                "first_check_TypeError=%r",
                                index,
                                filter_index,
                                filter_name,
                                first_error,
                            )

                        # ------------------------------------------------
                        # Fallback: check(message)
                        # ------------------------------------------------

                        try:

                            filter_result = await check_method(
                                message,
                            )

                            logger.info(
                                "[FILTER TRACE] "
                                "handler=%03d "
                                "filter=%d "
                                "type=%s "
                                "RESULT=%r "
                                "(without kwargs)",
                                index,
                                filter_index,
                                filter_name,
                                filter_result,
                            )

                        except Exception:

                            logger.exception(
                                "[FILTER TRACE] "
                                "handler=%03d "
                                "filter=%d "
                                "type=%s "
                                "CHECK_ERROR",
                                index,
                                filter_index,
                                filter_name,
                            )

                    except Exception:

                        logger.exception(
                            "[FILTER TRACE] "
                            "handler=%03d "
                            "filter=%d "
                            "INSPECTION_ERROR",
                            index,
                            filter_index,
                        )

            except Exception:

                logger.exception(
                    "[FILTER TRACE] "
                    "handler=%03d "
                    "HANDLER_INSPECTION_ERROR",
                    index,
                )

    except Exception:

        logger.exception(
            "[FILTER TRACE] "
            "FAILED"
        )


# ============================================================
# DISPATCHER.process_update TRACE
# ============================================================

@wraps(_original_process_update)
async def _diagnostic_process_update(
    self,
    update,
    *args,
    **kwargs,
):

    logger.info(
        "[PROCESS_UPDATE] "
        "ENTER update_id=%r",
        getattr(
            update,
            "update_id",
            None,
        ),
    )

    try:

        message = getattr(
            update,
            "message",
            None,
        )

        if message is not None:

            chat = getattr(
                message,
                "chat",
                None,
            )

            user = getattr(
                message,
                "from_user",
                None,
            )

            logger.info(
                "[UPDATE INSPECT] "
                "message.text=%r "
                "chat_id=%r "
                "user_id=%r "
                "chat_type=%r",
                getattr(
                    message,
                    "text",
                    None,
                ),
                getattr(
                    chat,
                    "id",
                    None,
                ),
                getattr(
                    user,
                    "id",
                    None,
                ),
                getattr(
                    chat,
                    "type",
                    None,
                ),
            )

            logger.info(
                "[UPDATE INSPECT] "
                "message=%r",
                message,
            )

        else:

            logger.info(
                "[UPDATE INSPECT] "
                "no message object"
            )

    except Exception:

        logger.exception(
            "[UPDATE INSPECT] failed"
        )

    # ========================================================
    # DUMP ALL HANDLERS
    # ========================================================

    try:

        _dump_message_handlers(
            self
        )

    except Exception:

        logger.exception(
            "[HANDLERS] dump failed"
        )

    # ========================================================
    # FILTER MATCH DIAGNOSTIC
    # ========================================================

    if getattr(update, "message", None):

        try:

            await _trace_start_filters(
                self,
                update.message,
            )

        except Exception:

            logger.exception(
                "[FILTER TRACE] "
                "top-level failure"
            )

    # ========================================================
    # ORIGINAL DISPATCH
    # ========================================================

    logger.info(
        "[PROCESS_UPDATE] "
        "calling original Dispatcher.process_update"
    )

    try:

        result = await _original_process_update(
            self,
            update,
            *args,
            **kwargs,
        )

        logger.info(
            "[PROCESS_UPDATE DONE] "
            "update_id=%r "
            "result=%r",
            getattr(
                update,
                "update_id",
                None,
            ),
            result,
        )

        return result

    except Exception:

        logger.exception(
            "[PROCESS_UPDATE] "
            "original process_update FAILED"
        )

        raise


Dispatcher.process_update = _diagnostic_process_update


# ============================================================
# DISPATCHER.start_polling TRACE
# ============================================================

@wraps(_original_start_polling)
async def _diagnostic_start_polling(
    self,
    *args,
    **kwargs,
):

    logger.info(
        "[DISPATCHER] start_polling ENTER"
    )

    logger.info(
        "[DISPATCHER] "
        "args=%r kwargs=%r",
        args,
        kwargs,
    )

    try:

        result = await _original_start_polling(
            self,
            *args,
            **kwargs,
        )

        logger.info(
            "[DISPATCHER] start_polling EXIT result=%r",
            result,
        )

        return result

    except Exception:

        logger.exception(
            "[DISPATCHER] start_polling FAILED"
        )

        raise


Dispatcher.start_polling = _diagnostic_start_polling


# ============================================================
# BOOT DIAGNOSTICS
# ============================================================

logger.info(
    "[DIAG BOOT] diagnostic_polling_launcher.py loaded"
)

logger.info(
    "[DIAG BOOT] Python=%s",
    sys.version,
)

logger.info(
    "[DIAG BOOT] sys.argv=%r",
    sys.argv,
)

logger.info(
    "[DIAG BOOT] instrumentation installed"
)

logger.info(
    "[DIAG BOOT] launching player_runtime_entry.py"
)


# ============================================================
# RUN REAL PRODUCTION ENTRYPOINT
# ============================================================

try:

    runpy.run_module(
        "player_runtime_entry",
        run_name="__main__",
    )

except SystemExit as exc:

    logger.info(
        "[DIAG BOOT] "
        "player_runtime_entry exited "
        "SystemExit=%r",
        exc,
    )

    raise

except Exception:

    logger.exception(
        "[DIAG BOOT] "
        "player_runtime_entry FAILED"
    )

    traceback.print_exc()

    raise

finally:

    logger.info(
        "[DIAG BOOT] "
        "diagnostic launcher finished"
    )
