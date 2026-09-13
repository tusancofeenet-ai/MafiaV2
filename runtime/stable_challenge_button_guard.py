"""Prevent stale challenge buttons after a player has already challenged."""
from __future__ import annotations

import asyncio
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _group_id(app):
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None


async def _hide_challenge_button(app, seat):
    """Remove the challenge action from the currently displayed turn."""
    mid = getattr(app, "current_turn_message_id", None)
    gid = _group_id(app)
    if not mid or not gid:
        return
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("⏭ نکست", callback_data=f"next_{int(seat)}")
    )
    try:
        await app.bot.edit_message_reply_markup(gid, int(mid), reply_markup=kb)
    except Exception as exc:
        logging.debug("challenge button UI update failed: %s", exc)


def install(app):
    if getattr(app, "_stable_challenge_button_guard_installed", False):
        return False
    handlers = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None:
        return False
    for item in handlers:
        fn = getattr(item, "handler", None)
        if getattr(fn, "__name__", "") != "challenge_request":
            continue
        original = fn
        if getattr(original, "_stable_wrapped", False):
            app._stable_challenge_button_guard_installed = True
            return True

        async def guarded(callback):
            data = str(callback.data or "")
            try:
                target_seat = int(data.split("_", 2)[2])
            except Exception:
                return await original(callback)
            challenger_uid = int(callback.from_user.id)
            slots = getattr(app, "player_slots", {}) or {}
            challenger_seat = next(
                (int(s) for s, uid in slots.items() if int(uid) == challenger_uid),
                None,
            )
            used = getattr(app, "_stable_challenge_used", set())
            locked = getattr(app, "_stable_challenge_locked", set())
            if challenger_uid in used:
                await callback.answer("❌ شما در این دور قبلاً چالش داده‌اید.", show_alert=True)
                return
            # _stable_challenge_locked contains TARGET seats whose challenge
            # has already been consumed. It must never contain the requester.
            if target_seat in locked:
                await callback.answer("⛔ برای این نوبت دیگر چالش پذیرفته نمی‌شود.", show_alert=True)
                return
            # Hide the stale action before the request is processed. The
            # authoritative handler still performs all semantic validation and
            # records _stable_challenge_used only after validation succeeds.
            await _hide_challenge_button(app, target_seat)
            return await original(callback)

        guarded.__name__ = "challenge_request"
        guarded._stable_wrapped = True
        item.handler = guarded
        logging.info("Stable challenge button guard installed")
        app._stable_challenge_button_guard_installed = True
        return True
    logging.warning("Stable challenge button guard: challenge handler not found")
    return False
