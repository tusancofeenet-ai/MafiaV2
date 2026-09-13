from __future__ import annotations

import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler

ADMIN_ONLY_EXACT = {
    "lv6_new", "new_game", "manage_game", "manage_scenarios",
    "add_scenario", "remove_scenario", "back_main", "choose_scenario",
    "choose_moderator",
}
ADMIN_ONLY_PREFIXES = ("lv6_s:", "lv6_m:", "delete_scen_", "scenario_", "moderator_")
ADMIN_OR_MOD_EXACT = {
    "lv6_manage", "lv6_cancel", "lv6_change_s", "lv6_change_m",
    "lv6_challenge", "lv6_remove", "lv6_ready", "lv6_distribute",
    "distribute_roles", "start_round", "start_turn", "start_night",
    "start_new_day", "speaker_auto", "speaker_manual", "choose_head",
    "challenge_toggle", "lv6_back_s", "lv6_challenge_status",
}
ADMIN_OR_MOD_PREFIXES = ("remove_player:", "remove_", "next_")

LEGACY_GAME_HANDLERS = {
    "start_round_handler", "handle_start_turn", "start_night", "start_new_day",
    "distribute_roles_callback",
}

# These callbacks are owned by the single private UI authority. They must not
# be passed through a group-admin guard because their callback message lives
# in the user's private chat. The private UI performs its own group-admin
# authorization against the configured game group.
PRIVATE_UI_EXACT = {"manage_game", "final:start", "final:scenarios", "final:help", "addons_menu"}
PRIVATE_UI_PREFIXES = ("finalgm:", "final:scenario:", "adm2:add:")


def _handler(item):
    return getattr(item, "handler", None)


def _set_handler(item, fn):
    if hasattr(item, "handler"):
        item.handler = fn
        return True
    if hasattr(item, "callback"):
        item.callback = fn
        return True
    if isinstance(item, dict):
        item["handler"] = fn
        return True
    return False


def _configured_group_id(main):
    for attr in ("ALLOWED_GROUP_ID", "GROUP_ID", "group_id", "group_chat_id"):
        value = getattr(main, attr, None)
        if value:
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def install(main):
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("FINAL runtime guard: callback registry unavailable")
        return

    before = len(registry)
    registry[:] = [
        item for item in registry
        if getattr(_handler(item), "__name__", "") not in LEGACY_GAME_HANDLERS
    ]
    removed_legacy = before - len(registry)

    next_items = [item for item in registry if getattr(_handler(item), "__name__", "") == "next_turn"]
    if len(next_items) > 1:
        keep = next_items[0]
        registry[:] = [
            item for item in registry
            if getattr(_handler(item), "__name__", "") != "next_turn" or item is keep
        ]

    for item in list(registry):
        fn = _handler(item)
        if fn is None or getattr(fn, "_final_runtime_guard", False):
            continue
        original = fn

        @wraps(original)
        async def guarded(callback, _original=original):
            data = str(getattr(callback, "data", "") or "")
            if data in PRIVATE_UI_EXACT or any(data.startswith(p) for p in PRIVATE_UI_PREFIXES):
                return await _original(callback)

            protected_admin = data in ADMIN_ONLY_EXACT or any(data.startswith(p) for p in ADMIN_ONLY_PREFIXES)
            protected_game = data in ADMIN_OR_MOD_EXACT or any(data.startswith(p) for p in ADMIN_OR_MOD_PREFIXES)
            if protected_admin or protected_game:
                group_id = _configured_group_id(main)
                user_id = getattr(getattr(callback, "from_user", None), "id", None)
                is_admin = False
                if group_id and user_id:
                    try:
                        admins = await main.bot.get_chat_administrators(group_id)
                        is_admin = any(a.user.id == user_id for a in admins)
                    except Exception:
                        logging.exception("FINAL runtime guard: admin lookup failed for configured group %s", group_id)
                is_mod = user_id == getattr(main, "moderator_id", None)
                allowed = is_admin if protected_admin else (is_admin or is_mod)
                if not allowed:
                    reason = (
                        "⛔ فقط مدیران گروه به این گزینه دسترسی دارند."
                        if protected_admin else
                        "⛔ فقط گرداننده یا مدیر گروه به این گزینه دسترسی دارند."
                    )
                    await callback.answer(reason, show_alert=True)
                    raise CancelHandler()
            return await _original(callback)

        guarded._final_runtime_guard = True
        guarded._final_runtime_original = original
        _set_handler(item, guarded)

    for wanted in reversed(("handle_challenge_response", "challenge_request", "start_round_clean")):
        for i, item in enumerate(registry):
            if getattr(_handler(item), "__name__", "") == wanted:
                registry.insert(0, registry.pop(i))
                break

    main._final_runtime_guard_installed = True
    logging.info(
        "FINAL runtime guard installed: handlers=%d legacy_removed=%d protected_exact=%d",
        len(registry), removed_legacy, len(ADMIN_ONLY_EXACT | ADMIN_OR_MOD_EXACT),
    )
