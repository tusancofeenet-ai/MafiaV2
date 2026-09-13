"""Production-only performance cutover for the aiogram v2 webhook path.

The legacy UI hotfix module historically wrapped Dispatcher.process_update and
performed a synchronous PostgreSQL player upsert before every Telegram update.
That made even cheap callbacks wait on a database round-trip. Player identity
is already persisted when users enter/update a game and display names are
cached by PlayerService, so there is no reason to perform this work globally.

This module removes that accidental per-update wrapper without touching the
actual callback fixes registered by game_ui_bugfixes.
"""
from __future__ import annotations

import logging
from types import MethodType


def _bound_dispatcher_method(value, dp):
    return (
        callable(value)
        and getattr(value, "__self__", None) is dp
        and getattr(value, "__func__", None) is not None
    )


def install(main) -> bool:
    dp = getattr(main, "dp", None)
    if dp is None:
        return False

    current = getattr(dp, "process_update", None)
    restored = False

    # game_ui_bugfixes installed an async closure around the original bound
    # Dispatcher.process_update. Recover that original bound method from the
    # closure instead of disabling the useful callback hotfix handlers.
    if getattr(main, "_mafia_identity_hotfix", False) and getattr(current, "__closure__", None):
        for cell in current.__closure__ or ():
            try:
                candidate = cell.cell_contents
            except ValueError:
                continue
            if _bound_dispatcher_method(candidate, dp) and candidate is not current:
                dp.process_update = candidate
                restored = True
                break

    if restored:
        main._mafia_identity_hotfix = False
        logging.info("PRODUCTION_FASTPATH: removed per-update identity DB wrapper")
    else:
        logging.info("PRODUCTION_FASTPATH: no per-update identity wrapper detected")

    return restored
