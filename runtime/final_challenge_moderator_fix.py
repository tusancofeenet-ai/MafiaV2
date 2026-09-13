"""Final runtime corrections for challenge direction and moderator authorization.

Challenge semantics:
- the current speaker is the challenge TARGET;
- every other eligible player may request a challenge from that speaker;
- the target/current speaker accepts or rejects the request;
- accepting locks the target's challenge button for that turn;
- muted players cannot request challenges;
- extra turns never expose a challenge button.

Also normalizes the selected moderator id before the legacy role-distribution
callback executes, because the legacy stack contains several callback layers.
"""
from __future__ import annotations

import html
import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _gid(main):
    for obj in (main, getattr(main, "addons", None)):
        for attr in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
            value = getattr(obj, attr, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _seat_uid(main, seat):
    try:
        return (getattr(main, "player_slots", {}) or {}).get(int(seat))
    except Exception:
        return None


def _seat_for_uid(main, uid):
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    for seat, player_uid in (getattr(main, "player_slots", {}) or {}).items():
        try:
            if int(player_uid) == uid:
                return int(seat)
        except (TypeError, ValueError):
            continue
    return None


def _players(main):
    result = []
    for seat, uid in (getattr(main, "player_slots", {}) or {}).items():
        try:
            seat = int(seat)
            uid = int(uid)
        except (TypeError, ValueError):
            continue
        fallback = (getattr(main, "players", {}) or {}).get(uid)
        try:
            name = main.display_name(uid, fallback)
        except Exception:
            name = fallback
        if not name or str(name).strip() in {"?", "❓", "None", "بازیکن"}:
            name = fallback or f"بازیکن {seat}"
        result.append((seat, uid, str(name)))
    return sorted(result)


def _ensure(main):
    if not isinstance(getattr(main, "challenge_target_locked", None), set):
        main.challenge_target_locked = set()
    if not isinstance(getattr(main, "challenge_request_messages", None), dict):
        main.challenge_request_messages = {}
    if not isinstance(getattr(main, "challenge_requests", None), dict):
        main.challenge_requests = {}


async def _delete(main, message_id):
    gid = _gid(main)
    if not gid or not message_id:
        return
    try:
        await main.bot.delete_message(gid, int(message_id))
    except Exception:
        pass


async def _lock_turn_button(main, seat):
    _ensure(main)
    message_id = getattr(main, "current_turn_message_id", None)
    gid = _gid(main)
    if not gid or not message_id:
        return
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{int(seat)}"))
    try:
        await main.bot.edit_message_reply_markup(gid, int(message_id), reply_markup=kb)
    except Exception:
        logging.debug("challenge: could not lock turn button", exc_info=True)


async def _delete_all_request_messages(main, target_seat):
    _ensure(main)
    requests = main.challenge_requests.get(target_seat, {}) or {}
    for challenger_id in list(requests.keys()):
        message_id = main.challenge_request_messages.pop((int(target_seat), int(challenger_id)), None)
        if message_id:
            await _delete(main, message_id)
    main.challenge_requests.pop(target_seat, None)


async def _delete_one_request_message(main, target_seat, challenger_id):
    _ensure(main)
    message_id = main.challenge_request_messages.pop((int(target_seat), int(challenger_id)), None)
    if message_id:
        await _delete(main, message_id)


async def _hydrate(main, uid):
    gid = _gid(main)
    if not gid or not uid:
        return None
    try:
        member = await main.bot.get_chat_member(gid, int(uid))
        name = getattr(getattr(member, "user", None), "full_name", None)
        if name and isinstance(getattr(main, "players", None), dict):
            current = main.players.get(int(uid))
            if not current or str(current).strip() in {"?", "❓", "None", "بازیکن"}:
                main.players[int(uid)] = name
        return name
    except Exception:
        return None


def _eligible_requester(main, requester_id, target_seat):
    try:
        requester_id = int(requester_id)
        target_seat = int(target_seat)
    except (TypeError, ValueError):
        return False, "⚠️ بازیکن نامعتبر است."

    if not getattr(main, "game_running", False):
        return False, "⚠️ بازی در حال اجرا نیست."
    target_id = _seat_uid(main, target_seat)
    if not target_id:
        return False, "⚠️ بازیکن صاحب نوبت پیدا نشد."
    if requester_id == int(target_id):
        return False, "❌ صاحب نوبت نمی‌تواند از خودش درخواست چالش بدهد."
    if requester_id not in {uid for _, uid, _ in _players(main)}:
        return False, "❌ فقط بازیکنان همین بازی می‌توانند درخواست چالش بدهند."

    muted = {int(x) for x in getattr(main, "_gm_muted_next_round", set())}
    if _seat_for_uid(main, requester_id) in muted:
        return False, "🔇 بازیکن ساکت‌شده نمی‌تواند درخواست چالش بدهد."

    extra_seats = {int(x) for x in getattr(main, "_gm_extra_seats", set())}
    if _seat_for_uid(main, requester_id) in extra_seats or getattr(main, "_gm_extra_turn_active", False):
        return False, "➕ در ترن اضافه امکان درخواست چالش وجود ندارد."

    try:
        active_seat = int(main.turn_order[main.current_turn_index])
    except Exception:
        active_seat = None
    if active_seat != target_seat:
        return False, "⚠️ این نوبت دیگر فعال نیست."
    if getattr(main, "challenge_mode", False):
        return False, "⚔️ در حال حاضر یک چالش در حال اجراست."
    if not getattr(main, "challenge_active", False):
        return False, "⚔️ چالش در این بازی خاموش است."
    _ensure(main)
    if target_seat in main.challenge_target_locked:
        return False, "⛔ برای این نوبت دیگر درخواست چالش پذیرفته نمی‌شود."
    return True, ""


def install(main):
    _ensure(main)
    dp = main.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return False
    if getattr(main, "_final_challenge_moderator_fix", False):
        return True

    # ---- Correct challenge request button ----
    old_keyboard = getattr(main, "turn_keyboard", None)
    if old_keyboard is not None and not getattr(old_keyboard, "_correct_challenge_keyboard", False):
        @wraps(old_keyboard)
        def correct_turn_keyboard(seat, is_challenge=False):
            _ensure(main)
            try:
                seat = int(seat)
            except Exception:
                return old_keyboard(seat, is_challenge)

            # Challenge turns and extra/muted turns never expose a request button.
            if is_challenge or seat in {int(x) for x in getattr(main, "_gm_extra_seats", set())} or seat in {int(x) for x in getattr(main, "_gm_muted_next_round", set())}:
                return InlineKeyboardMarkup(row_width=1).add(
                    InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}")
                )

            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}"))
            if getattr(main, "challenge_active", False) and seat not in main.challenge_target_locked:
                # This button targets THIS turn owner. Other players click it.
                kb.add(InlineKeyboardButton("⚔️ درخواست چالش", callback_data=f"challenge_request_{seat}"))
            return kb

        correct_turn_keyboard._correct_challenge_keyboard = True
        main.turn_keyboard = correct_turn_keyboard

    # ---- Authoritative challenge request ----
    async def challenge_request_final(callback):
        _ensure(main)
        try:
            target_seat = int(str(callback.data).split("_", 2)[2])
        except Exception:
            await callback.answer("⚠️ داده چالش نامعتبر است.", show_alert=True)
            raise CancelHandler()

        requester_id = int(callback.from_user.id)
        allowed, reason = _eligible_requester(main, requester_id, target_seat)
        if not allowed:
            await callback.answer(reason, show_alert=True)
            raise CancelHandler()

        target_id = _seat_uid(main, target_seat)
        await _hydrate(main, requester_id)
        await _hydrate(main, target_id)

        requests = main.challenge_requests.setdefault(target_seat, {})
        if requester_id in requests and requests[requester_id] == "pending":
            await callback.answer("❌ در این نوبت قبلاً درخواست داده‌ای.", show_alert=True)
            raise CancelHandler()

        requests[requester_id] = "pending"
        requester_name = _players(main)
        names = {uid: name for _, uid, name in requester_name}
        challenger_name = names.get(requester_id, f"بازیکن {requester_id}")
        target_name = names.get(int(target_id), f"بازیکن {target_seat}")

        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("✅ قبول (قبل)", callback_data=f"accept_before_{requester_id}_{int(target_id)}"),
            InlineKeyboardButton("✅ قبول (بعد)", callback_data=f"accept_after_{requester_id}_{int(target_id)}"),
            InlineKeyboardButton("❌ رد", callback_data=f"reject_{requester_id}_{int(target_id)}"),
        )
        gid = _gid(main)
        msg = await main.bot.send_message(
            gid,
            f"⚔️ {html.escape(challenger_name)} از {html.escape(target_name)} درخواست چالش کرد.",
            reply_markup=kb,
            parse_mode="HTML",
        )
        main.challenge_request_messages[(target_seat, requester_id)] = msg.message_id
        await callback.answer("⏳ درخواست چالش برای صاحب نوبت ارسال شد.")
        raise CancelHandler()

    # ---- Authoritative challenge response ----
    async def challenge_response_final(callback):
        _ensure(main)
        parts = str(callback.data or "").split("_")
        if parts[0] == "reject":
            if len(parts) != 3:
                await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
                raise CancelHandler()
            timing = None
            try:
                challenger_id, target_id = int(parts[1]), int(parts[2])
            except ValueError:
                await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
                raise CancelHandler()
        else:
            if len(parts) != 4 or parts[0] != "accept":
                await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
                raise CancelHandler()
            timing = parts[1]
            try:
                challenger_id, target_id = int(parts[2]), int(parts[3])
            except ValueError:
                await callback.answer("⚠️ درخواست نامعتبر است.", show_alert=True)
                raise CancelHandler()

        target_seat = _seat_for_uid(main, target_id)
        challenger_seat = _seat_for_uid(main, challenger_id)
        if target_seat is None or challenger_seat is None:
            await callback.answer("⚠️ یکی از بازیکنان دیگر در بازی نیست.", show_alert=True)
            raise CancelHandler()

        active_seat = None
        try:
            active_seat = int(main.turn_order[main.current_turn_index])
        except Exception:
            pass
        if active_seat != target_seat:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()
        if int(callback.from_user.id) != int(target_id):
            await callback.answer("❌ فقط بازیکن صاحب نوبت می‌تواند درخواست چالش را تأیید یا رد کند.", show_alert=True)
            raise CancelHandler()

        requests = main.challenge_requests.get(target_seat, {}) or {}
        if challenger_id not in requests or requests[challenger_id] != "pending":
            await callback.answer("⚠️ این درخواست دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()

        names = {uid: name for _, uid, name in _players(main)}
        target_name = names.get(target_id, f"بازیکن {target_seat}")
        challenger_name = names.get(challenger_id, f"بازیکن {challenger_seat}")

        if parts[0] == "reject":
            await _delete_one_request_message(main, target_seat, challenger_id)
            main.challenge_requests.get(target_seat, {}).pop(challenger_id, None)
            await main.bot.send_message(_gid(main), f"🚫 {html.escape(target_name)} درخواست چالش {html.escape(challenger_name)} را رد کرد.", parse_mode="HTML")
            await callback.answer("❌ درخواست رد شد.")
            raise CancelHandler()

        # One accepted challenge closes every open request for this target.
        await _delete_all_request_messages(main, target_seat)
        main.challenge_target_locked.add(target_seat)

        # Disable further challenge requests from the current turn message.
        await _lock_turn_button(main, target_seat)

        if timing == "before":
            main.paused_main_player = target_seat
            main.paused_main_duration = 120
            main.challenge_mode = True
            main.post_challenge_advance = False
            if getattr(main, "turn_timer_task", None) and not main.turn_timer_task.done():
                main.turn_timer_task.cancel()
            await main.bot.send_message(
                _gid(main),
                f"⚔️ {html.escape(target_name)} به {html.escape(challenger_name)} چالش داد (قبل از صحبت).",
                parse_mode="HTML",
            )
            await main.start_turn(challenger_seat, duration=60, is_challenge=True)
        elif timing == "after":
            main.pending_challenges[target_seat] = challenger_id
            await main.bot.send_message(
                _gid(main),
                f"⚔️ {html.escape(target_name)} به {html.escape(challenger_name)} چالش داد (بعد از صحبت).",
                parse_mode="HTML",
            )
        else:
            await callback.answer("⚠️ نوع چالش نامعتبر است.", show_alert=True)
            raise CancelHandler()

        await callback.answer("✅ چالش تأیید شد.")
        raise CancelHandler()

    # Remove every legacy duplicate for these two callback namespaces and put
    # the authoritative handlers first. This avoids the old inverted actor check.
    kept = []
    for item in list(registry):
        fn = _handler(item)
        name = getattr(fn, "__name__", "")
        data_hint = getattr(item, "filters", None)
        if name in {"challenge_request", "challenge_request_v3", "authoritative_request", "challenge_response_v3", "handle_challenge_response", "authoritative_response"}:
            continue
        kept.append(item)
    registry[:] = kept
    dp.register_callback_query_handler(
        challenge_response_final,
        lambda c: str(c.data or "").startswith(("accept_before_", "accept_after_", "reject_")),
        state="*",
    )
    dp.register_callback_query_handler(
        challenge_request_final,
        lambda c: str(c.data or "").startswith("challenge_request_"),
        state="*",
    )

    # ---- Moderator normalization + role distribution ----
    role_handler = None
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__name__", "") == "distribute_roles_callback":
            role_handler = fn
            break

    if role_handler is not None:
        async def distribute_roles_final(callback, _original=role_handler):
            addons_mod = getattr(getattr(main, "addons", None), "moderator_id", None)
            current_mod = getattr(main, "moderator_id", None)
            try:
                current_mod_int = int(current_mod) if current_mod is not None else None
            except (TypeError, ValueError):
                current_mod_int = None
            try:
                addons_mod_int = int(addons_mod) if addons_mod is not None else None
            except (TypeError, ValueError):
                addons_mod_int = None

            # The selected moderator is the authoritative game moderator. If
            # the legacy global was lost/reset, restore it from MafiaAddons.
            if addons_mod_int is not None and current_mod_int != addons_mod_int:
                main.moderator_id = addons_mod_int
                current_mod_int = addons_mod_int

            if current_mod_int is None:
                await callback.answer("⛔ گرداننده بازی مشخص نشده است.", show_alert=True)
                raise CancelHandler()
            if int(callback.from_user.id) != current_mod_int:
                await callback.answer("⛔ فقط گرداننده بازی می‌تواند نقش‌ها را پخش کند.", show_alert=True)
                raise CancelHandler()
            return await _original(callback)

        distribute_roles_final.__name__ = "distribute_roles_callback"
        registry.append(type(role_handler)(handler=distribute_roles_final, filters=getattr(role_handler, "filters", []), flags=getattr(role_handler, "flags", {}))) if False else None
        # Reuse the original handler object in-place so existing authorization
        # metadata remains intact, then move it to the front.
        for item in registry:
            if _handler(item) is role_handler:
                item.handler = distribute_roles_final
                registry.insert(0, registry.pop(registry.index(item)))
                break

    # Re-front our two challenge handlers after the role handler operation.
    for name in ("challenge_response_final", "challenge_request_final"):
        for i, item in enumerate(registry):
            if getattr(_handler(item), "__name__", "") == name:
                registry.insert(0, registry.pop(i))
                break

    main._final_challenge_moderator_fix = True
    logging.info("Final challenge direction + moderator authorization fix installed")
    return True
