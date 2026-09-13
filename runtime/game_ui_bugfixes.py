"""Runtime hotfixes for the legacy Telegram UI during migration.

This module is intentionally isolated from main1.py. It fixes callback handlers
that are currently shadowed/broken in the legacy module while the persistent
runtime migration is completed.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


KNOWN_EMPTY_NAMES = {None, "", "?", "❓", "❔"}


def _move_handler_front(dp, callback):
    """Move a newly registered callback handler ahead of legacy handlers."""
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if not isinstance(handlers, list):
        return False
    for index, item in enumerate(handlers):
        candidate = getattr(item, "callback", None)
        if candidate is callback or candidate is getattr(callback, "__wrapped__", None):
            handlers.insert(0, handlers.pop(index))
            return True
    return False


def _remember_user(main, user) -> None:
    if not user:
        return
    uid = int(user.id)
    full_name = (getattr(user, "full_name", None) or "").strip()
    username = getattr(user, "username", None)
    if not full_name:
        full_name = username or str(uid)

    try:
        service = getattr(main, "player_service", None)
        if service is not None:
            service.ensure_player_data(uid, full_name=full_name, username=username)
    except Exception:
        logging.exception("player identity persistence failed for %s", uid)

    # Only update the in-game mapping when this UID is already a player. This
    # prevents merely opening a private panel from adding users to the game.
    try:
        players = main.players
        if uid in players:
            current = dict.get(players, uid, None)
            if current in KNOWN_EMPTY_NAMES:
                dict.__setitem__(players, uid, full_name)
    except Exception:
        pass


def install(main) -> None:
    """Install all hotfixes after main1 and the persistent bridges are loaded."""
    dp = main.dp
    bot = main.bot

    # ------------------------------------------------------------------
    # 1) Keep Telegram full_name/username fresh before every update.
    # ------------------------------------------------------------------
    original_process_update = dp.process_update
    if not getattr(dp, "_mafia_identity_hotfix", False):
        async def process_update(update):
            try:
                message = getattr(update, "message", None) or getattr(update, "edited_message", None)
                if message is not None:
                    _remember_user(main, getattr(message, "from_user", None))

                callback = getattr(update, "callback_query", None)
                if callback is not None:
                    _remember_user(main, getattr(callback, "from_user", None))
                    callback_message = getattr(callback, "message", None)
                    if callback_message is not None:
                        _remember_user(main, getattr(callback_message, "from_user", None))
            except Exception:
                logging.exception("identity cache update failed")
            return await original_process_update(update)

        dp.process_update = process_update
        dp._mafia_identity_hotfix = True

    # Replace the legacy display function with a DB-backed + Telegram-cached
    # resolver. This also protects places where the old code passes "❓" as
    # its fallback value.
    try:
        player_service = main.player_service

        def robust_display_name(user_id, fallback=None):
            fallback = fallback if fallback not in KNOWN_EMPTY_NAMES else None
            try:
                name = player_service.display_name(int(user_id), fallback or "")
            except Exception:
                name = None
            if name and name not in KNOWN_EMPTY_NAMES:
                return name
            try:
                raw = dict.get(main.players, int(user_id), None)
                if raw and raw not in KNOWN_EMPTY_NAMES:
                    return raw
            except Exception:
                pass
            return fallback or str(user_id)

        main.display_name = robust_display_name
    except Exception:
        logging.exception("failed to install robust display_name")

    # ------------------------------------------------------------------
    # Common helper: persistent game row.
    # ------------------------------------------------------------------
    def _active_game(group_id):
        runtime = getattr(main, "persistent_runtime", None)
        if runtime is None or not group_id:
            return None
        try:
            return runtime.state.active_game(int(group_id))
        except Exception:
            logging.exception("active game lookup failed")
            return None

    async def _persist_player_change(group_id, old_uid=None, new_uid=None, seat=None):
        game = _active_game(group_id)
        runtime = getattr(main, "persistent_runtime", None)
        if not game or runtime is None:
            return
        game_id = game["id"]
        try:
            if old_uid is not None:
                runtime.state.games.remove_player(game_id, int(old_uid))
            if new_uid is not None:
                runtime.state.games.add_player(game_id, int(new_uid), seat=seat)
        except Exception:
            logging.exception("persistent player change failed")

    # ------------------------------------------------------------------
    # 2) Remove player: fix the old player_uid typo and answer immediately.
    # ------------------------------------------------------------------
    async def remove_player_confirm_fixed(callback: types.CallbackQuery):
        await callback.answer()
        data = str(callback.data or "")
        try:
            if data.startswith("confirm_remove_uid_"):
                uid = int(data.removeprefix("confirm_remove_uid_"))
                seat = next((s for s, u in main.player_slots.items() if int(u) == uid), None)
            else:
                seat = int(data.removeprefix("confirm_remove_"))
                uid = main.player_slots.get(seat)
                uid = int(uid) if uid is not None else None
        except (TypeError, ValueError):
            await callback.message.answer("⚠️ اطلاعات بازیکن نامعتبر است.")
            return

        if uid is None:
            await callback.message.answer("⚠️ بازیکن پیدا نشد.")
            return

        name = main.display_name(uid, dict.get(main.players, uid, None))
        group_id = main.group_chat_id
        main.removed_players.setdefault(group_id, {})[seat] = {
            "id": uid,
            "name": name,
        }
        main.player_slots.pop(seat, None)
        try:
            main.players.pop(uid, None)
        except Exception:
            pass
        try:
            main.players_in_game.get(group_id, {}).pop(seat, None)
        except Exception:
            pass
        await _persist_player_change(group_id, old_uid=uid, seat=seat)
        await callback.message.answer(f"✅ بازیکن <b>{name}</b> از بازی خارج شد (صندلی {seat}).", parse_mode="HTML")

    dp.register_callback_query_handler(
        remove_player_confirm_fixed,
        lambda c: str(c.data or "").startswith(("confirm_remove_",)),
    )
    _move_handler_front(dp, remove_player_confirm_fixed)

    # ------------------------------------------------------------------
    # 3) Replace player: make the operation atomic in memory + persistence.
    # ------------------------------------------------------------------
    async def do_replace_fixed(callback: types.CallbackQuery):
        await callback.answer()
        try:
            _, _, uid_sub_str, seat_str = str(callback.data).split("_")
            uid_sub = int(uid_sub_str)
            seat = int(seat_str)
        except (ValueError, TypeError):
            await callback.message.answer("⚠️ اطلاعات جایگزینی نامعتبر است.")
            return

        group_id = main.group_chat_id
        subs = main.substitute_list.get(group_id, {}) or {}
        sub_info = subs.pop(uid_sub, None)
        if not sub_info:
            await callback.message.answer("⚠️ بازیکن جایگزین پیدا نشد؛ ممکن است قبلاً استفاده شده باشد.")
            return

        old_uid = main.player_slots.get(seat)
        if old_uid is None:
            await callback.message.answer("⚠️ این صندلی دیگر بازیکن فعالی ندارد.")
            return

        old_name = main.display_name(old_uid, dict.get(main.players, old_uid, None))
        new_name = main.display_name(uid_sub, sub_info.get("name"))

        main.player_slots[seat] = uid_sub
        main.players[uid_sub] = new_name
        try:
            main.players.pop(old_uid, None)
        except Exception:
            pass

        role_map = getattr(main, "last_role_map", {})
        if old_uid in role_map:
            role_map[uid_sub] = role_map.pop(old_uid)

        await _persist_player_change(group_id, old_uid=old_uid, new_uid=uid_sub, seat=seat)
        await callback.message.answer(
            f"✅ بازیکن <b>{old_name}</b> با <b>{new_name}</b> جایگزین شد (صندلی {seat}).",
            parse_mode="HTML",
        )
        try:
            await main.update_lobby()
        except Exception:
            pass

    dp.register_callback_query_handler(
        do_replace_fixed,
        lambda c: str(c.data or "").startswith("do_replace_"),
    )
    _move_handler_front(dp, do_replace_fixed)

    # ------------------------------------------------------------------
    # 4) Moderator change: remove undefined uid/callback.from_display_name.
    # ------------------------------------------------------------------
    async def change_moderator_fixed(callback: types.CallbackQuery):
        await callback.answer()
        group_id = main.group_chat_id
        if not group_id:
            await callback.message.answer("🚫 بازی فعالی وجود ندارد.")
            return
        admins = await bot.get_chat_administrators(group_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for member in admins:
            uid = member.user.id
            name = main.display_name(uid, member.user.full_name)
            kb.add(InlineKeyboardButton(name, callback_data=f"set_mod_{uid}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="back_manage_game"))
        await callback.message.edit_text("🔄 انتخاب گرداننده جدید:", reply_markup=kb)

    async def set_moderator_fixed(callback: types.CallbackQuery):
        await callback.answer()
        try:
            new_id = int(str(callback.data).removeprefix("set_mod_"))
        except ValueError:
            await callback.message.answer("⚠️ گرداننده نامعتبر است.")
            return
        main.moderator_id = new_id
        try:
            main.reserved_god = {"id": new_id}
        except Exception:
            pass
        group_id = main.group_chat_id
        game = _active_game(group_id)
        runtime = getattr(main, "persistent_runtime", None)
        if game and runtime is not None:
            try:
                runtime.state.games.update_game(game["id"], moderator_id=new_id)
            except Exception:
                logging.exception("failed to persist moderator change")
        member = await bot.get_chat_member(group_id, new_id)
        name = main.display_name(new_id, member.user.full_name)
        await callback.message.edit_text(f"✅ گرداننده جدید تنظیم شد: <b>{name}</b>", parse_mode="HTML")

    dp.register_callback_query_handler(change_moderator_fixed, lambda c: c.data == "change_mod")
    dp.register_callback_query_handler(set_moderator_fixed, lambda c: str(c.data or "").startswith("set_mod_"))
    _move_handler_front(dp, change_moderator_fixed)
    _move_handler_front(dp, set_moderator_fixed)

    # ------------------------------------------------------------------
    # 5) Missing back handler from the moderator submenu.
    # ------------------------------------------------------------------
    async def back_manage_game_fixed(callback: types.CallbackQuery):
        await callback.answer()
        await main.manage_game_handler(callback)

    dp.register_callback_query_handler(back_manage_game_fixed, lambda c: c.data == "back_manage_game")
    _move_handler_front(dp, back_manage_game_fixed)

    # ------------------------------------------------------------------
    # 6) Reject challenge: clear both legacy and persistent pending state.
    # ------------------------------------------------------------------
    async def reject_challenge_fixed(callback: types.CallbackQuery):
        await callback.answer()
        try:
            parts = str(callback.data).split("_")
            challenger_id = int(parts[1])
            target_id = int(parts[2])
        except (IndexError, ValueError):
            await callback.message.answer("⚠️ اطلاعات رد چالش نامعتبر است.")
            return

        target_seat = next((s for s, u in main.player_slots.items() if int(u) == target_id), None)
        if target_seat in main.challenge_requests:
            main.challenge_requests[target_seat].pop(challenger_id, None)
            if not main.challenge_requests[target_seat]:
                main.challenge_requests.pop(target_seat, None)
        main.active_challenger_seats.discard(target_seat)

        group_id = main.group_chat_id
        runtime = getattr(main, "persistent_runtime", None)
        if runtime is not None and group_id:
            try:
                pending = runtime.pending_challenges(int(group_id))
                for challenge in pending or []:
                    if int(challenge.get("challenger_id")) == challenger_id and int(challenge.get("target_id")) == target_id:
                        runtime.resolve_challenge(int(group_id), challenge["id"], "rejected")
                        break
            except Exception:
                logging.exception("persistent challenge rejection failed")

        challenger_name = main.display_name(challenger_id, None)
        target_name = main.display_name(target_id, None)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if group_id:
            await bot.send_message(group_id, f"🚫 {target_name} درخواست چالش {challenger_name} را رد کرد.")

    dp.register_callback_query_handler(
        reject_challenge_fixed,
        lambda c: str(c.data or "").startswith("reject_"),
    )
    _move_handler_front(dp, reject_challenge_fixed)

    # ------------------------------------------------------------------
    # 7) Start new day: acknowledge immediately and use the persistent day
    #    runtime; fall back to the legacy UI if the edit target is stale.
    # ------------------------------------------------------------------
    async def start_new_day_fixed(callback: types.CallbackQuery):
        await callback.answer("🌞 روز جدید در حال شروع است...")
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند روز جدید را شروع کند.", show_alert=True)
            return
        group_id = main.group_chat_id
        if not group_id:
            await callback.message.answer("🚫 بازی فعالی وجود ندارد.")
            return

        main.reset_round_data()
        main.round_active = True
        main.challenge_mode = False
        main.game_running = True

        runtime = getattr(main, "persistent_runtime", None)
        if runtime is not None:
            try:
                runtime.start_new_day(int(group_id))
            except Exception:
                logging.exception("persistent start_new_day failed")

        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("🎲 انتخاب خودکار", callback_data="speaker_auto"),
            InlineKeyboardButton("✋ انتخاب دستی", callback_data="speaker_manual"),
            InlineKeyboardButton("⚔️ وضعیت چالش", callback_data="challenge_toggle"),
            InlineKeyboardButton("▶️ شروع دور", callback_data="start_turn"),
        )
        text = "🌞 روز جدید شروع شد!\n\nسر صحبت را انتخاب کنید:"
        msg_id = main.game_message_id or callback.message.message_id
        try:
            await bot.edit_message_text(text, chat_id=group_id, message_id=msg_id, reply_markup=kb)
            main.game_message_id = msg_id
        except Exception:
            msg = await bot.send_message(group_id, text, reply_markup=kb)
            main.game_message_id = msg.message_id

    dp.register_callback_query_handler(start_new_day_fixed, lambda c: c.data == "start_new_day")
    _move_handler_front(dp, start_new_day_fixed)

    # ------------------------------------------------------------------
    # 8) Cancel game: clear every in-memory collection AND close the
    #    persistent game row so a new game can start immediately.
    # ------------------------------------------------------------------
    async def cancel_game_fixed(callback: types.CallbackQuery):
        await callback.answer()
        group_id = main.group_chat_id
        if not group_id:
            await callback.message.answer("🚫 بازی فعالی وجود ندارد.")
            return

        user_id = callback.from_user.id
        allowed = user_id == main.moderator_id or user_id in getattr(main, "admins", set())
        if not allowed:
            try:
                admin_ids = {m.user.id for m in await bot.get_chat_administrators(group_id)}
                allowed = user_id in admin_ids
            except Exception:
                admin_ids = set()
        if not allowed:
            await callback.answer("⛔ فقط گرداننده یا مدیران گروه می‌توانند بازی را لغو کنند.", show_alert=True)
            return

        runtime = getattr(main, "persistent_runtime", None)
        if runtime is not None:
            try:
                game = runtime.state.active_game(int(group_id))
                if game:
                    game_id = game["id"]
                    for player in runtime.state.games.list_players(game_id):
                        runtime.state.games.remove_player(game_id, player["player_id"])
                    runtime.state.games.update_game(
                        game_id,
                        status="cancelled",
                        finished_at=datetime.now(timezone.utc),
                        state={},
                        current_turn_index=0,
                        current_turn_seat=None,
                    )
            except Exception:
                logging.exception("persistent game cancellation failed")

        task = getattr(main, "turn_timer_task", None)
        if task is not None and not task.done():
            task.cancel()
        main.turn_timer_task = None

        # Complete legacy state reset.
        reset_names = (
            "player_slots", "players_in_game", "removed_players", "substitute_list",
            "challenge_requests", "pending_challenges", "active_challenger_seats",
            "challenges", "waiting_list", "turn_order", "extra_turns",
        )
        for name in reset_names:
            value = getattr(main, name, None)
            if hasattr(value, "clear"):
                value.clear()
            elif isinstance(value, list):
                value[:] = []

        try:
            main.players.clear()
        except Exception:
            pass
        try:
            main.last_role_map.clear()
        except Exception:
            pass

        main.moderator_id = None
        main.selected_scenario = None
        main.game_message_id = None
        main.lobby_message_id = None
        main.group_chat_id = None
        main.game_running = False
        main.lobby_active = False
        main.round_active = False
        main.challenge_mode = False
        main.paused_main_player = None
        main.paused_main_duration = None
        main.post_challenge_advance = False
        main.current_turn_index = 0
        main.current_turn_message_id = None
        main.reserved_god = None
        main.reserved_list = None
        main.reserved_scenario = None

        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await callback.message.answer("✅ بازی به‌طور کامل لغو و وضعیت آن پاک شد. می‌توانید بازی جدید را شروع کنید.")

    dp.register_callback_query_handler(cancel_game_fixed, lambda c: c.data == "cancel_game")
    _move_handler_front(dp, cancel_game_fixed)

    logging.info("✅ Mafia runtime UI bugfixes installed")
