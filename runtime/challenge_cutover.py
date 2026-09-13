"""Compatibility bridge for migrating legacy Telegram challenge callbacks.

The legacy handlers remain responsible for Telegram rendering and turn UX,
while challenge lifecycle state is persisted through PersistentChallengeRuntime.
"""
from __future__ import annotations

import logging
from typing import Any

from runtime.challenge_runtime import PersistentChallengeRuntime


async def _safe_answer(callback: Any, text: str, show_alert: bool = False) -> None:
    try:
        await callback.answer(text, show_alert=show_alert)
    except Exception:
        pass


async def _close_challenge_buttons(callback: Any) -> None:
    """Close the accept/reject controls immediately after a response."""
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass


async def _hydrate_player_names(legacy: Any, *user_ids: int) -> None:
    """Fill legacy.players from Telegram when runtime state lacks a real name.

    Older game state can contain the literal fallback values ``بازیکن`` or
    ``❓``. Those values are not considered valid names and must be hydrated as
    well. The challenger is also hydrated from CallbackQuery.from_user when
    possible, avoiding an unnecessary API call for that side of the message.
    """
    players = getattr(legacy, "players", None)
    if not isinstance(players, dict):
        return
    bot = getattr(legacy, "bot", None)
    group_id = getattr(legacy, "group_chat_id", None)

    callback_user = None
    # The active callback is not passed here, so Telegram lookup remains the
    # authoritative fallback for both participants.
    invalid = {None, "", "بازیکن", "❓", "?"}

    for raw_id in user_ids:
        try:
            user_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        try:
            current = players.get(user_id)
        except Exception:
            current = None
        if current not in invalid:
            continue

        if bot is None or not group_id:
            continue
        try:
            member = await bot.get_chat_member(int(group_id), user_id)
            user = getattr(member, "user", None)
            name = getattr(user, "full_name", None) or getattr(user, "first_name", None)
            if name:
                players[user_id] = name
        except Exception:
            continue


def _group_id(legacy: Any, callback: Any = None) -> int | None:
    value = getattr(legacy, "group_chat_id", None)
    if value:
        try:
            return int(value)
        except (TypeError, ValueError):
            pass
    try:
        chat = getattr(getattr(callback, "message", None), "chat", None)
        if chat and getattr(chat, "id", None):
            return int(chat.id)
    except Exception:
        pass
    return None


def _find_challenge(runtime: PersistentChallengeRuntime, group_id: int, challenger_id: int, target_id: int, status: str | None = None):
    rows = runtime.history(group_id)
    matches = [
        row for row in rows
        if int(row.get("challenger_id")) == int(challenger_id)
        and int(row.get("target_id")) == int(target_id)
        and (status is None or row.get("status") == status)
    ]
    return matches[-1] if matches else None


async def bridged_challenge_request(legacy: Any, callback: Any, original: Any):
    group_id = _group_id(legacy, callback)
    if not group_id:
        return await original(callback)
    try:
        parts = callback.data.split("_", 2)
        target_seat = int(parts[2])
        target_id = (getattr(legacy, "player_slots", {}) or {}).get(target_seat)
        challenger_id = int(callback.from_user.id)
        if not target_id or challenger_id == int(target_id):
            return await original(callback)

        legacy.group_chat_id = group_id
        await _hydrate_player_names(legacy, challenger_id, int(target_id))

        runtime = _runtime(legacy)
        existing = _find_challenge(runtime, group_id, challenger_id, int(target_id), "pending")
        if not existing:
            runtime.request(group_id, challenger_id, int(target_id))
    except Exception:
        logging.exception("challenge request persistence failed")
        await _safe_answer(callback, "⚠️ ثبت درخواست چالش انجام نشد.", True)
        return
    return await original(callback)


async def bridged_challenge_response(legacy: Any, callback: Any, original: Any):
    group_id = _group_id(legacy, callback)
    if not group_id:
        return await original(callback)
    try:
        parts = callback.data.split("_")
        action = parts[0]
        timing = parts[1] if action == "accept" else None
        challenger_id = int(parts[2])
        target_id = int(parts[3])

        legacy.group_chat_id = group_id
        await _hydrate_player_names(legacy, challenger_id, target_id)

        runtime = _runtime(legacy)
        row = _find_challenge(runtime, group_id, challenger_id, target_id, "pending")

        await _close_challenge_buttons(callback)

        if action == "accept" and row:
            pause_state = {
                "turn_order": list(getattr(legacy, "turn_order", []) or []),
                "current_turn_index": int(getattr(legacy, "current_turn_index", 0)),
                "paused_main_player": getattr(legacy, "paused_main_player", None),
                "paused_main_duration": getattr(legacy, "paused_main_duration", None),
                "challenge_mode": bool(getattr(legacy, "challenge_mode", False)),
                "post_challenge_advance": bool(getattr(legacy, "post_challenge_advance", False)),
            }
            runtime.activate(
                group_id,
                str(row["id"]),
                timing,
                pause_main_turn=(timing == "before"),
                pause_state=pause_state,
            )
        elif action == "reject" and row:
            runtime.resolve(group_id, str(row["id"]), "rejected", resume_main_turn=False)
    except Exception:
        logging.exception("challenge response persistence failed")
        await _safe_answer(callback, "⚠️ ثبت وضعیت چالش انجام نشد.", True)
        return
    return await original(callback)


def _runtime(legacy: Any) -> PersistentChallengeRuntime:
    runtime = getattr(legacy, "_persistent_challenge_runtime", None)
    if runtime is None:
        runtime = PersistentChallengeRuntime()
        legacy._persistent_challenge_runtime = runtime
    return runtime


def install_legacy_challenge_cutover(legacy: Any) -> dict[str, bool]:
    """Wrap legacy request/response callbacks with persistent challenge state."""
    result = {"request": False, "response": False, "choice": False}
    dp = getattr(legacy, "dp", None)
    if dp is None:
        return result

    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return result

    def replace(function_name: str, wrapper_factory):
        replaced = False
        for item in registry:
            callback = getattr(item, "callback", None)
            if callback is None and isinstance(item, dict):
                callback = item.get("callback")
            if getattr(callback, "__name__", None) != function_name:
                continue
            if getattr(callback, "_persistent_challenge_bridge", False):
                replaced = True
                continue
            async def wrapper(cb, _original=callback):
                return await wrapper_factory(legacy, cb, _original)
            wrapper.__name__ = function_name
            wrapper._persistent_challenge_bridge = True
            wrapper._legacy_original = callback
            if hasattr(item, "callback"):
                item.callback = wrapper
            elif isinstance(item, dict):
                item["callback"] = wrapper
            replaced = True
        return replaced

    result["request"] = replace("challenge_request", bridged_challenge_request)
    result["response"] = replace("handle_challenge_response", bridged_challenge_response)
    result["choice"] = bool(getattr(legacy, "challenge_choice", None))
    return result
