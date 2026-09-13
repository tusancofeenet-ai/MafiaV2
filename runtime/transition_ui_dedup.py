"""Final transition UI deduplication.

The legacy UI cleanup layer registered its own start_round/start_turn handlers
before the stable round engine. That allowed two generations of round UI to
compete. The stable engine is the sole owner of those two callbacks.
"""
from __future__ import annotations
import logging


def install(app):
    if getattr(app, "_transition_ui_dedup_installed", False):
        return False
    reg = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if reg is None:
        return False

    removed = []
    kept = []
    for item in list(reg):
        fn = getattr(item, "callback", None) or getattr(item, "handler", None)
        name = getattr(fn, "__name__", "")
        if name in {"start_round_clean", "start_turn_clean"}:
            removed.append(name)
            continue
        kept.append(item)
    reg[:] = kept

    # The stable engine registers one handler for both start_round/start_turn.
    # Put it first so no older matching callback can render another round UI.
    for i, item in enumerate(reg):
        fn = getattr(item, "callback", None) or getattr(item, "handler", None)
        if getattr(fn, "__name__", "") == "start_round":
            reg.insert(0, reg.pop(i))
            break

    app._transition_ui_dedup_installed = True
    logging.info("Transition UI dedup installed; removed=%s", removed)
    return True
