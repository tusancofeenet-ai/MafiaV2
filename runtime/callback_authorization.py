from __future__ import annotations

import logging
from functools import wraps


_ADMIN_ONLY_EXACT = {
    "lv6_new", "new_game", "manage_game", "manage_scenarios", "add_scenario",
    "remove_scenario", "back_main", "choose_scenario", "choose_moderator",
}
_ADMIN_ONLY_PREFIXES = ("lv6_s:", "lv6_m:", "delete_scen_", "scenario_", "moderator_")

_ADMIN_OR_MOD_EXACT = {
    "lv6_manage", "lv6_cancel", "lv6_change_s", "lv6_change_m", "lv6_challenge",
    "lv6_remove", "lv6_ready", "speaker_auto", "speaker_manual", "choose_head",
    "challenge_toggle", "lv6_back_s",
}
_ADMIN_OR_MOD_PREFIXES = ("remove_player:", "remove_")

_MODERATOR_ONLY_EXACT = {
    "lv6_distribute", "distribute_roles", "start_round", "start_turn", "start_night",
    "start_new_day", "show_roles", "view_roles", "send_roles", "roles",
}
_MODERATOR_ONLY_PREFIXES = (
    "role:", "roles:", "show_role:", "view_role:", "send_role:", "distribute:",
)


def _callback_of(item):
    callback = getattr(item, "callback", None)
    if callback is None and isinstance(item, dict):
        callback = item.get("callback")
    return callback


def _set_callback(item, callback):
    if hasattr(item, "callback"):
        item.callback = callback
    elif isinstance(item, dict):
        item["callback"] = callback


def _moderator_id(main):
    """Return the selected moderator from whichever runtime layer owns it."""
    for obj in (main, getattr(main, "addons", None)):
        value = getattr(obj, "moderator_id", None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def install(main):
    dp = main.dp
    bot = main.bot
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.warning("callback authorization: callback registry unavailable")
        return

    def data_of(callback):
        return str(getattr(callback, "data", "") or "")

    def requires_admin(data):
        return data in _ADMIN_ONLY_EXACT or any(data.startswith(p) for p in _ADMIN_ONLY_PREFIXES)

    def requires_admin_or_moderator(data):
        return data in _ADMIN_OR_MOD_EXACT or any(data.startswith(p) for p in _ADMIN_OR_MOD_PREFIXES)

    def requires_moderator(data):
        return data in _MODERATOR_ONLY_EXACT or any(data.startswith(p) for p in _MODERATOR_ONLY_PREFIXES)

    def configured_group_id():
        for obj in (main, getattr(main, "addons", None)):
            for attr in ("group_chat_id", "group_id", "ALLOWED_GROUP_ID"):
                value = getattr(obj, attr, None)
                if value:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        pass
        return None

    async def is_admin(user_id, group_id):
        try:
            admins = await bot.get_chat_administrators(group_id)
            return any(a.user.id == user_id for a in admins)
        except Exception:
            logging.exception("callback authorization: admin lookup failed")
            return False

    async def allowed(callback):
        data = data_of(callback)
        sensitive = requires_moderator(data)
        admin_action = requires_admin(data)
        shared_action = requires_admin_or_moderator(data)
        if not (sensitive or admin_action or shared_action):
            return True, ""

        chat = getattr(getattr(callback, "message", None), "chat", None)
        group_id = getattr(chat, "id", None) if chat else None
        if not group_id:
            group_id = configured_group_id()
        if not group_id:
            return False, "⛔ گروه بازی مشخص نیست."

        user_id = int(callback.from_user.id)
        admin = await is_admin(user_id, int(group_id))
        moderator = _moderator_id(main) == user_id

        if sensitive:
            if moderator:
                return True, ""
            return False, "⛔ این بخش فقط برای گرداننده بازی مجاز است."
        if admin_action:
            if admin:
                return True, ""
            return False, "⛔ فقط مدیران گروه به این گزینه دسترسی دارند."
        if admin or moderator:
            return True, ""
        return False, "⛔ فقط گرداننده یا مدیر گروه به این گزینه دسترسی دارند."

    wrapped_count = 0
    for item in list(registry):
        callback_fn = _callback_of(item)
        if callback_fn is None or getattr(callback_fn, "_callback_auth_guard", False):
            continue

        @wraps(callback_fn)
        async def guarded(callback, _original=callback_fn):
            ok, reason = await allowed(callback)
            if not ok:
                await callback.answer(reason, show_alert=True)
                return
            return await _original(callback)

        guarded._callback_auth_guard = True
        guarded._callback_auth_original = callback_fn
        _set_callback(item, guarded)
        wrapped_count += 1

    main._callback_authorization_installed = True
    logging.info("Callback authorization pass installed on %s unguarded handlers", wrapped_count)
