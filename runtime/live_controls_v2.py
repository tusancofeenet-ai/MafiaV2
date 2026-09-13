from __future__ import annotations

import html
import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _registry(main):
    return getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", [])


def _replace_named(main, names, wrapper_factory):
    registry = _registry(main)
    replaced = False
    for item in list(registry):
        callback = getattr(item, "callback", None)
        if getattr(callback, "__name__", "") not in names:
            continue
        new_callback = wrapper_factory(callback)
        item.callback = new_callback
        replaced = True
    return replaced


def _active_game(main, group_id):
    try:
        return main.runtime.state.active_game(int(group_id))
    except Exception:
        return None


def _next_settings(game):
    return dict((game or {}).get("state", {}).get("next_settings") or {})


def _sync_next_globals(main, group_id, game=None):
    game = game or _active_game(main, group_id)
    settings = _next_settings(game)
    main.next_by_players_enabled = bool(settings.get("allow_players_next", True))
    main.next_by_moderator_enabled = bool(settings.get("allow_moderator_next", True))
    return settings


def _scenario_mode(main, group_id):
    try:
        scenario = main.scenario_runtime.current(int(group_id))
        return "free" if (scenario or {}).get("challenge_mode") == "free" else "limited"
    except Exception:
        return "limited"


def _scope_token(main):
    # A new normal-order list is created at every new day/round.
    return id(getattr(main, "_stable_normal_order", None))


def _challenge_usage(main):
    usage = getattr(main, "_scenario_challenge_usage", None)
    if usage is None:
        usage = set()
        main._scenario_challenge_usage = usage
    return usage


def _challenge_key(main, group_id, challenger_seat, active_seat):
    mode = _scenario_mode(main, group_id)
    token = _scope_token(main)
    if mode == "free":
        return ("free", token, int(active_seat), int(challenger_seat))
    return ("limited", token, int(challenger_seat))


def _show_status(main, group_id):
    game = _active_game(main, group_id)
    return bool((game or {}).get("state", {}).get("challenge_settings", {}).get("show_player_status", True))


async def _render_challenge_roster(main, group_id):
    if not _show_status(main, group_id):
        return
    order = list(getattr(main, "_stable_normal_order", []) or getattr(main, "turn_order", []) or [])
    if not order:
        return
    active = None
    try:
        active = int(main.turn_order[main.current_turn_index])
    except Exception:
        pass
    mode = _scenario_mode(main, group_id)
    usage = _challenge_usage(main)
    token = _scope_token(main)
    lines = ["📋 <b>وضعیت چالش بازیکنان</b>", ""]
    for seat in order:
        try:
            seat = int(seat)
            uid = int(main.player_slots.get(seat))
        except Exception:
            continue
        name = main.display_name(uid, main.players.get(uid, "بازیکن"))
        if mode == "free":
            used = ("free", token, int(active or -1), seat) in usage
        else:
            used = ("limited", token, seat) in usage
        marker = " 🤏" if used else ""
        lines.append(f"{seat:02d}. <a href=\"tg://user?id={uid}\">{html.escape(str(name))}</a>{marker}")
    text = "\n".join(lines)
    mid = getattr(main, "_scenario_challenge_roster_message_id", None)
    try:
        if mid:
            await main.bot.edit_message_text(text, int(group_id), int(mid), parse_mode="HTML")
            return
    except Exception:
        pass
    try:
        msg = await main.bot.send_message(int(group_id), text, parse_mode="HTML")
        main._scenario_challenge_roster_message_id = msg.message_id
    except Exception:
        logging.exception("challenge roster render failed")


def _patch_next(main):
    def wrap(original):
        async def guarded_next(callback):
            gid = int(getattr(callback.message, "chat", None).id)
            game = _active_game(main, gid)
            settings = _sync_next_globals(main, gid, game)
            uid = int(callback.from_user.id)
            moderator = int(getattr(main, "moderator_id", 0) or 0)
            try:
                seat = int(str(callback.data).split("_", 1)[1])
                owner = int(main.player_slots.get(seat) or 0)
            except Exception:
                owner = 0
            if uid == moderator and not bool(settings.get("allow_moderator_next", True)):
                await callback.answer("⛔ نکست برای گرداننده توسط مدیریت بازی غیرفعال است.", show_alert=True)
                raise CancelHandler()
            if uid != moderator and not bool(settings.get("allow_players_next", True)):
                await callback.answer("⛔ نکست برای بازیکنان توسط مدیریت بازی غیرفعال است.", show_alert=True)
                raise CancelHandler()
            if uid != moderator and uid != owner:
                # Keep challenge-engine authority for challenge turns; normal next must belong to owner.
                active_challengers = {int(x) for x in getattr(main, "active_challenger_seats", set()) or set()}
                challenger_ids = {int(main.player_slots.get(s) or 0) for s in active_challengers}
                if uid not in challenger_ids:
                    await callback.answer("⛔ فقط صاحب نوبت یا گرداننده می‌تواند نکست بزند.", show_alert=True)
                    raise CancelHandler()
            return await original(callback)
        guarded_next.__name__ = "next_handler"
        guarded_next._live_controls_v2 = True
        return guarded_next
    return _replace_named(main, {"next_handler"}, wrap)


def _patch_challenge_request(main):
    def wrap(original):
        async def guarded_request(callback):
            gid = int(callback.message.chat.id)
            challenger = int(callback.from_user.id)
            try:
                target_seat = int(str(callback.data).split("_", 1)[1])
                active = int(getattr(main, "turn_order", [])[getattr(main, "current_turn_index", 0)])
                challenger_seat = next((int(s) for s, uid in main.player_slots.items() if int(uid) == challenger), None)
            except Exception:
                await callback.answer("⚠️ اطلاعات چالش نامعتبر است.", show_alert=True)
                raise CancelHandler()
            if challenger_seat is None:
                await callback.answer("⚠️ شما بازیکن این بازی نیستید.", show_alert=True)
                raise CancelHandler()
            key = _challenge_key(main, gid, challenger_seat, active)
            if key in _challenge_usage(main):
                mode = _scenario_mode(main, gid)
                msg = "⚠️ در این نوبت صحبت قبلاً یک چالش گرفته‌اید." if mode == "free" else "⚠️ در این دور قبلاً یک چالش گرفته‌اید."
                await callback.answer(msg, show_alert=True)
                raise CancelHandler()
            before = dict(getattr(main, "_stable_challenge_requests", {}) or {})
            try:
                await original(callback)
            except CancelHandler:
                after = getattr(main, "_stable_challenge_requests", {}) or {}
                if after.get(active) == challenger:
                    _challenge_usage(main).add(key)
                    # The quota belongs to the requester, not the target.
                    try:
                        main._stable_challenge_locked.discard(active)
                    except Exception:
                        pass
                    await _render_challenge_roster(main, gid)
                raise
            except Exception:
                raise
            else:
                after = getattr(main, "_stable_challenge_requests", {}) or {}
                if after.get(active) == challenger and before.get(active) != challenger:
                    _challenge_usage(main).add(key)
                    await _render_challenge_roster(main, gid)
        guarded_request.__name__ = "challenge_request"
        guarded_request._live_controls_v2 = True
        return guarded_request
    return _replace_named(main, {"challenge_request"}, wrap)


def _patch_management_handlers(main):
    # Sync legacy globals whenever the management panel changes next settings.
    def next_wrap(original):
        async def handler(callback):
            result = await original(callback)
            gid = int(callback.message.chat.id)
            _sync_next_globals(main, gid)
            return result
        handler.__name__ = "next_toggle"
        return handler
    _replace_named(main, {"next_toggle"}, next_wrap)

    # Compact all player-pick menus from the central management panel.
    try:
        from runtime.game_management import GameManagement

        async def compact_pick(self, callback, action, title, rows):
            gid = int(callback.message.chat.id)
            game = self._game(gid)
            if not game or not await self._allowed(callback, gid, game):
                await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
                return
            kb = InlineKeyboardMarkup(row_width=3)
            for r in rows:
                uid = int(r["player_id"])
                seat = r.get("seat")
                label = f"{seat}. {self._name(r)}" if seat is not None else self._name(r)
                kb.insert(InlineKeyboardButton(label, callback_data=f"mgmt:{game['id']}:{action}:{uid}"))
            kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"))
            await callback.message.edit_text(title, parse_mode="HTML", reply_markup=kb)
            await callback.answer()

        GameManagement._pick = compact_pick
    except Exception:
        logging.exception("failed to compact GameManagement pick menus")

    # Replace the challenge-management screen with a compact 2x2 control area.
    def challenge_wrap(original):
        async def handler(callback):
            gid = int(callback.message.chat.id)
            game = _active_game(main, gid)
            if not game:
                await callback.answer("⛔ بازی فعال نیست.", show_alert=True)
                return
            enabled = bool(getattr(main, "challenge_enabled", {}).get(gid, True))
            show = _show_status(main, gid)
            rows = main.runtime.state.challenges.list_challenges(game["id"])
            pending = sum(1 for r in rows if str(r.get("status")) == "pending")
            active = sum(1 for r in rows if str(r.get("status")) in {"accepted", "active"})
            kb = InlineKeyboardMarkup(row_width=2)
            kb.row(
                InlineKeyboardButton("🟢 چالش: روشن" if enabled else "🔴 چالش: خاموش", callback_data=f"mgmt:{game['id']}:challenge_toggle"),
                InlineKeyboardButton("🤏 نمایش وضعیت: روشن" if show else "🚫 نمایش وضعیت: خاموش", callback_data=f"mgmt:{game['id']}:challenge_visibility_toggle"),
            )
            kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{game['id']}:open"), InlineKeyboardButton(f"📦 {len(rows)} چالش", callback_data=f"mgmt:{game['id']}:noop"))
            await callback.message.edit_text(
                f"⚔ <b>مدیریت چالش</b>\n\n⏳ در انتظار: {pending}\n⚡ فعال: {active}\n\n🤏 نمایش کنار نام بازیکنان: {'فعال' if show else 'غیرفعال'}",
                parse_mode="HTML", reply_markup=kb,
            )
            await callback.answer()
        handler.__name__ = "challenge"
        return handler
    _replace_named(main, {"challenge"}, challenge_wrap)

    # Register the visibility toggle and keep it close to the other management handlers.
    async def visibility_toggle(callback):
        gid = int(callback.message.chat.id)
        game = _active_game(main, gid)
        if not game:
            await callback.answer("⛔ بازی فعال نیست.", show_alert=True)
            return
        state = dict(game.get("state") or {})
        settings = dict(state.get("challenge_settings") or {})
        settings["show_player_status"] = not bool(settings.get("show_player_status", True))
        state["challenge_settings"] = settings
        game["state"] = state
        main.runtime.state.games.update_game(game["id"], state=state)
        await callback.answer("🤏 نمایش وضعیت چالش تغییر کرد.")
        # Reuse the replaced challenge handler.
        for item in _registry(main):
            cb = getattr(item, "callback", None)
            if getattr(cb, "__name__", "") == "challenge":
                await cb(callback)
                return

    main.dp.register_callback_query_handler(
        visibility_toggle,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2] == "challenge_visibility_toggle",
        state="*",
    )


def install(main):
    if getattr(main, "_live_controls_v2_installed", False):
        return False
    main._live_controls_v2_installed = True
    _sync_next_globals(main, getattr(main, "group_chat_id", None) or getattr(main, "ALLOWED_GROUP_ID", 0))
    _patch_management_handlers(main)
    patched_next = _patch_next(main)
    patched_challenge = _patch_challenge_request(main)
    logging.info("LIVE_CONTROLS_V2 active next=%s challenge=%s", patched_next, patched_challenge)
    return True
