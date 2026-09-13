"""Final guard for private role lookup.

Players may see only their own role while they are part of the current game.
Old role maps must not remain a way to inspect a previous game's role after the
game has ended or for users who were never in the current game.
"""
from __future__ import annotations

import logging


def install(app):
    handlers = getattr(app.dp.message_handlers, "handlers", None)
    if handlers is None or getattr(app, "_role_security_installed", False):
        return

    target = None
    for h in handlers:
        fn = getattr(h, "handler", None)
        if getattr(fn, "__name__", "") == "my_role_handler":
            target = fn
            break
    if target is None:
        logging.warning("role security: my_role_handler not found")
        return

    async def guarded_my_role(message):
        if message.chat.type != "private":
            return await target(message)

        uid = message.from_user.id
        running = bool(getattr(app, "game_running", False))
        slots = getattr(app, "player_slots", {}) or {}
        current_players = set(slots.values())

        if not running or uid not in current_players:
            await message.reply("⚠️ در حال حاضر نقش فعالی برای شما در بازی جاری ثبت نشده است.")
            return

        return await target(message)

    guarded_my_role.__name__ = "guarded_my_role"
    guarded_my_role._role_security_guard = True

    for i, h in enumerate(handlers):
        if getattr(getattr(h, "handler", None), "__name__", "") == "my_role_handler":
            h.handler = guarded_my_role
            handlers.insert(0, handlers.pop(i))
            break

    app._role_security_installed = True
