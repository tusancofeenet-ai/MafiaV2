@wraps(_original_process_update)
async def _diagnostic_process_update(self, update, *args, **kwargs):
    update_id = getattr(update, "update_id", "?")

    logger.info(
        "[INCOMING UPDATE] update_id=%s type=%s",
        update_id,
        type(update).__name__,
    )

    try:
        if getattr(update, "message", None):
            message = update.message

            logger.info(
                "[UPDATE MESSAGE] chat_id=%s user_id=%s text=%r",
                getattr(message.chat, "id", None),
                getattr(message.from_user, "id", None),
                getattr(message, "text", None),
            )

            # ==================================================
            # DIAGNOSTIC: dump registered message handlers
            # ==================================================

            logger.info(
                "[HANDLER DIAGNOSTIC] dispatcher=%r",
                self,
            )

            handlers = getattr(
                getattr(self, "message_handlers", None),
                "handlers",
                None,
            )

            if handlers is None:
                logger.warning(
                    "[HANDLER DIAGNOSTIC] message_handlers.handlers NOT FOUND"
                )
            else:
                logger.info(
                    "[HANDLER DIAGNOSTIC] message handler count=%d",
                    len(handlers),
                )

                for index, handler in enumerate(handlers):
                    try:
                        callback = getattr(
                            handler,
                            "callback",
                            None,
                        )

                        logger.info(
                            "[HANDLER %03d] callback=%s module=%s filters=%s",
                            index,
                            getattr(
                                callback,
                                "__qualname__",
                                repr(callback),
                            ),
                            getattr(
                                callback,
                                "__module__",
                                "?",
                            ),
                            getattr(
                                handler,
                                "filters",
                                None,
                            ),
                        )

                    except Exception:
                        logger.exception(
                            "[HANDLER %03d] inspection failed",
                            index,
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

    except Exception:
        logger.exception(
            "[UPDATE INSPECT] failed"
        )

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
