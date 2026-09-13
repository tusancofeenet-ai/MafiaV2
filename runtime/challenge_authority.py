from __future__ import annotations

import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


_INVALID_NAMES = {None, "", "بازیکن", "❓", "?"}


async def _hydrate(legacy, callback, *user_ids):
    players = getattr(legacy, "players", None)
    bot = getattr(legacy, "bot", None)
    chat = getattr(getattr(callback, "message", None), "chat", None)
    group_id = getattr(chat, "id", None) or getattr(legacy, "group_chat_id", None)
    if not isinstance(players, dict) or bot is None or not group_id:
        return
    legacy.group_chat_id = int(group_id)

    for raw_id in user_ids:
        try:
            uid = int(raw_id)
        except (TypeError, ValueError):
            continue
        try:
            current = players.get(uid)
        except Exception:
            current = None
        if current not in _INVALID_NAMES:
            continue
        try:
            member = await bot.get_chat_member(int(group_id), uid)
            user = getattr(member, "user", None)
            name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
            if name:
                players[uid] = name
        except Exception:
            logging.exception("challenge name hydration failed for %s", uid)


def install(main):
    """Make legacy challenge handlers authoritative by exact callback_data."""
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return

    request_original = None
    response_original = None
    kept = []

    # Capture the already-bridged callbacks, then remove every duplicate.
    for item in registry:
        callback = getattr(item, "callback", None)
        name = getattr(callback, "__name__", "")
        if name == "challenge_request" and request_original is None:
            request_original = callback
            continue
        if name == "handle_challenge_response" and response_original is None:
            response_original = callback
            continue
        if name in {"challenge_request", "handle_challenge_response"}:
            continue
        kept.append(item)
    registry[:] = kept

    if request_original is not None:
        async def authoritative_request(callback):
            try:
                target_seat = int(callback.data.split("_", 2)[2])
                target_id = (getattr(main, "player_slots", {}) or {}).get(target_seat)
                await _hydrate(main, callback, callback.from_user.id, target_id)
            except Exception:
                logging.exception("authoritative challenge request hydration failed")
            return await request_original(callback)

        authoritative_request.__name__ = "challenge_request"
        dp.register_callback_query_handler(
            authoritative_request,
            lambda c: str(c.data or "").startswith("challenge_request_"),
        )

    if response_original is not None:
        async def authoritative_response(callback):
            try:
                parts = str(callback.data or "").split("_")
                if len(parts) >= 4:
                    await _hydrate(main, callback, int(parts[2]), int(parts[3]))
                try:
                    await callback.message.edit_reply_markup(reply_markup=None)
                except Exception:
                    pass
            except Exception:
                logging.exception("authoritative challenge response hydration failed")
            return await response_original(callback)

        authoritative_response.__name__ = "handle_challenge_response"
        dp.register_callback_query_handler(
            authoritative_response,
            lambda c: str(c.data or "").startswith(("accept_before_", "accept_after_", "reject_")),
        )

    # Move the authoritative challenge handlers to the front.
    registry = getattr(dp.callback_query_handlers, "handlers", [])
    for name in ("handle_challenge_response", "challenge_request"):
        for i, item in enumerate(registry):
            if getattr(getattr(item, "callback", None), "__name__", "") == name:
                registry.insert(0, registry.pop(i))
                break

    logging.info("✅ Challenge authority installed")
