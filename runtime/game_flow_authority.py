from __future__ import annotations

import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    """Remove conflicting legacy game-flow handlers after all bridges load.

    The previous cleanup layer registered newer handlers but left legacy
    handlers with the same callback_data in the dispatcher. Depending on
    registration/order, aiogram could execute the legacy callback first. This
    layer makes the cleanup-owned handlers the only handlers for those exact
    transitions.
    """
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return

    cleanup_names = {
        "start_round_clean",
        "start_turn_clean",
        "start_night_clean",
        "start_new_day_clean",
        "challenge_status",
    }
    legacy_names = {
        "start_round_handler",
        "handle_start_turn",
        "start_night",
        "start_new_day",
        "distribute_roles_callback",
    }

    # Keep the authoritative v2 handlers; remove legacy duplicates.
    registry[:] = [
        item for item in registry
        if getattr(getattr(item, "callback", None), "__name__", "") not in legacy_names
    ]

    # There may be more than one next_turn registration. Keep only the v2
    # wrapper and discard all unwrapped legacy versions.
    kept_next = False
    filtered = []
    for item in registry:
        callback = getattr(item, "callback", None)
        name = getattr(callback, "__name__", "")
        if name == "next_turn":
            if getattr(callback, "_ui_cleanup_v2", False) and not kept_next:
                filtered.append(item)
                kept_next = True
            continue
        filtered.append(item)
    registry[:] = filtered

    # Move cleanup-owned handlers to the front in one deterministic pass.
    for name in reversed((
        "challenge_status",
        "start_new_day_clean",
        "start_night_clean",
        "start_turn_clean",
        "start_round_clean",
    )):
        for i, item in enumerate(registry):
            callback = getattr(item, "callback", None)
            if getattr(callback, "__name__", "") == name:
                registry.insert(0, registry.pop(i))
                break

    logging.info("✅ Game flow authority installed; legacy transition handlers removed")
