"""Role distribution for the canonical production lobby and first-day control UI."""
from __future__ import annotations

import html
import json
import logging
import random
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


def _sync_gameplay_bridge(app: Any, group_id: int, game: dict[str, Any], players: list[dict[str, Any]]) -> None:
    app.group_chat_id = int(group_id)
    app.ui.group_chat_id = int(group_id)
    app.moderator_id = int(game.get("moderator_id") or 0) or None
    app.player_slots = {int(row["seat"]): int(row["player_id"]) for row in players if row.get("seat") is not None}
    app.players = {int(row["player_id"]): str(row.get("nickname") or row.get("first_name") or row.get("username") or row["player_id"]) for row in players}
    app.turn_order = sorted(app.player_slots)
    app.current_turn_index = 0
    app.game_running = True
    app._stable_day_active = False
    app._stable_day_ended = False
    app._stable_phase = "normal"
    app.challenge_active = bool(getattr(app, "challenge_enabled", {}).get(int(group_id), True))
    app.challenge_mode = False
    app.pending_challenges = {}
    app.active_challenger_seats = set()


def _day_markup(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎩 انتخاب سردست", callback_data=f"day:{int(game_id)}:head"),
        InlineKeyboardButton("⚔ وضعیت چالش", callback_data=f"mgmt:{int(game_id)}:challenge"),
        InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"),
        InlineKeyboardButton("⚙️ مدیریت بازی", callback_data=f"mgmt:{int(game_id)}:open"),
    )


def _role_text(role: str, seat: int, scenario_name: str) -> str:
    return "༄\n<b>🎭 MAFIA NIGHTS</b>\n\n" + f"🎭 <b>نقش شما:</b> {html.escape(role)}\n" + f"💺 <b>صندلی:</b> {seat}\n" + f"📝 <b>سناریو:</b> {html.escape(scenario_name)}"


def install(app: Any) -> bool:
    dp, bot = app.dp, app.bot
    scenario_repo = ScenarioRepository()

    async def send_role_to_user(group_id: int, game: dict[str, Any], player_id: int) -> bool:
        rows = app.runtime.lobby_snapshot(group_id).get("players", [])
        player = next((r for r in rows if int(r["player_id"]) == int(player_id)), None)
        if not player or player.get("seat") is None or not player.get("role"):
            return False
        scenario_id = game.get("scenario_id")
        scenario = scenario_repo.get_by_id(int(scenario_id)) if scenario_id is not None else None
        scenario_name = str((scenario or {}).get("name") or scenario_id or "---")
        try:
            await bot.send_message(int(player_id), _role_text(str(player["role"]), int(player["seat"]), scenario_name), parse_mode="HTML")
            state = dict(game.get("state") or {})
            deliveries = dict(state.get("role_delivery") or {})
            deliveries[str(int(player_id))] = True
            state["role_delivery"] = deliveries
            app.runtime.state.games.update_game(game["id"], state=state)
            return True
        except Exception:
            logging.exception("failed to send role privately: user=%s game=%s", player_id, game.get("id"))
            return False

    async def role_start_command(message: types.Message):
        args = (message.get_args() or "").strip()
        if not args.startswith("role_"):
            return False
        parts = args.split("_")
        if len(parts) != 3:
            return False
        try:
            game_id, group_id = int(parts[1]), int(parts[2])
        except ValueError:
            return False
        game = app.runtime.state.active_game(group_id)
        if not game or int(game.get("id")) != game_id or str(game.get("status") or "") != "running":
            await message.answer("❌ این درخواست مربوط به یک بازی فعال نیست.")
            return True
        await app._ensure_player(message.from_user)
        ok = await send_role_to_user(group_id, game, int(message.from_user.id))
        await message.answer("✅ نقش شما ارسال شد. پیام خصوصی ربات را بررسی کنید." if ok else "❌ نقش شما برای این بازی پیدا نشد.")
        return True

    async def head_menu(callback: types.CallbackQuery):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "day" or parts[2] != "head": return
        group_id = int(callback.message.chat.id); game_id = int(parts[1]); game = app.runtime.state.active_game(group_id)
        if not game or int(game.get("id")) != game_id or str(game.get("status") or "") != "running":
            await callback.answer("❌ بازی فعال نیست.", show_alert=True); return
        if int(callback.from_user.id) != int(game.get("moderator_id") or 0):
            try:
                if (await bot.get_chat_member(group_id, int(callback.from_user.id))).status not in {"creator", "administrator"}: raise PermissionError
            except Exception:
                await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True); return
        rows = [r for r in app.runtime.lobby_snapshot(group_id).get("players", []) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished"}]
        kb = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("🎲 انتخاب تصادفی", callback_data=f"day:{game_id}:head_random"))
        for row in sorted(rows, key=lambda r: int(r.get("seat") or 999)):
            name = str(row.get("nickname") or row.get("first_name") or row.get("username") or row["player_id"])
            kb.insert(InlineKeyboardButton(f"{int(row['seat'])}. {name[:20]}", callback_data=f"day:{game_id}:head_pick:{int(row['seat'])}"))
        kb.row(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"mgmt:{game_id}:close"))
        await callback.message.edit_text("🎩 <b>انتخاب سردست</b>\n\nسردست را انتخاب کنید یا انتخاب تصادفی بزنید:", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def set_head(callback: types.CallbackQuery, random_pick: bool = False):
        parts = str(callback.data or "").split(":"); expected = 3 if random_pick else 4
        if len(parts) != expected or parts[0] != "day": return
        group_id = int(callback.message.chat.id); game_id = int(parts[1]); game = app.runtime.state.active_game(group_id)
        if not game or int(game.get("id")) != game_id or str(game.get("status") or "") != "running":
            await callback.answer("❌ بازی فعال نیست.", show_alert=True); return
        if int(callback.from_user.id) != int(game.get("moderator_id") or 0):
            try:
                if (await bot.get_chat_member(group_id, int(callback.from_user.id))).status not in {"creator", "administrator"}: raise PermissionError
            except Exception:
                await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True); return
        rows = [r for r in app.runtime.lobby_snapshot(group_id).get("players", []) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished"}]
        if not rows: await callback.answer("❌ بازیکنی برای سردست وجود ندارد.", show_alert=True); return
        seat = int(random.choice(rows)["seat"]) if random_pick else int(parts[3])
        if not random_pick and seat not in {int(r["seat"]) for r in rows}: await callback.answer("❌ صندلی نامعتبر است.", show_alert=True); return
        state = dict(game.get("state") or {}); state["head_seat"] = seat
        app.runtime.state.games.update_game(game_id, state=state)
        await callback.message.edit_text(f"🌅 <b>شروع روز</b>\n\n🎩 سردست انتخاب شد: <b>صندلی {seat}</b>", parse_mode="HTML", reply_markup=_day_markup(game_id))
        await callback.answer(f"🎩 سردست: صندلی {seat}")

    async def distribute_roles(callback: types.CallbackQuery):
        group_id = int(callback.message.chat.id); uid = int(callback.from_user.id)
        game = app.runtime.state.active_game(group_id)
        if not game: await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True); return
        canonical_game_id = getattr(callback, "_canonical_lobby_game_id", None)
        if canonical_game_id is not None and int(game["id"]) != int(canonical_game_id): await callback.answer("⚠️ این دکمه مربوط به بازی قبلی است.", show_alert=True); return
        if str(game.get("status") or "") != "lobby": await callback.answer("❌ لابی فعال نیست.", show_alert=True); return
        allowed = uid == int(game.get("moderator_id") or 0)
        if not allowed:
            try: allowed = (await bot.get_chat_member(group_id, uid)).status in {"creator", "administrator"}
            except Exception: allowed = False
        if not allowed: await callback.answer("⛔ فقط گرداننده یا مدیر گروه می‌تواند نقش‌ها را پخش کند.", show_alert=True); return
        scenario_id = game.get("scenario_id"); scenario = scenario_repo.get_by_id(int(scenario_id)) if scenario_id is not None else None
        if not scenario: await callback.answer("❌ سناریوی بازی مشخص نیست.", show_alert=True); return
        roles = scenario.get("roles") or []
        if isinstance(roles, str):
            try: roles = json.loads(roles)
            except Exception: roles = [x.strip() for x in roles.split(",") if x.strip()]
        roles = list(roles)
        players = [r for r in app.runtime.lobby_snapshot(group_id).get("players", []) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}]
        players.sort(key=lambda row: int(row.get("seat") or 999))
        if not players: await callback.answer("❌ بازیکنی در لابی نیست.", show_alert=True); return
        if len(players) != len(roles): await callback.answer(f"❌ تعداد بازیکنان ({len(players)}) با ظرفیت سناریو ({len(roles)}) برابر نیست.", show_alert=True); return
        random.shuffle(roles); game_id = int(game["id"]); role_map: dict[str, str] = {}; save_failures: list[int] = []
        for player, role in zip(players, roles):
            player_id = int(player["player_id"])
            if not app.runtime.state.games.set_player_role(game_id, player_id, str(role)): save_failures.append(player_id)
            role_map[str(player_id)] = str(role)
        if save_failures:
            await callback.answer("❌ ذخیره نقش‌ها کامل نشد؛ بازی شروع نشد.", show_alert=True); logging.error("role distribution failed players=%s game=%s", save_failures, game_id); return

        state = dict(game.get("state") or {})
        state.update({
            "last_role_map": role_map,
            "players_in_game": {str(int(row["seat"])): {"id": int(row["player_id"]), "name": str(row.get("nickname") or row.get("first_name") or row.get("username") or row["player_id"]), "role": role_map[str(int(row["player_id"]))]} for row in players},
            "roles_distributed": True, "gameplay_ready": True, "role_delivery": {},
            "turn_order": [int(row["seat"]) for row in players], "current_turn_index": 0, "head_seat": None,
        })
        if not app.runtime.state.games.update_game(game_id, status="running", state=state, current_turn_index=0, current_turn_seat=None):
            await callback.answer("❌ انتقال بازی به مرحله اجرا انجام نشد.", show_alert=True); return
        game = app.runtime.state.active_game(group_id) or game; _sync_gameplay_bridge(app, group_id, game, players)

        sent = 0; delivery_failures: list[int] = []; scenario_name = str(scenario.get("name") or scenario_id)
        for player in players:
            player_id = int(player["player_id"]); role = role_map[str(player_id)]; seat = int(player["seat"])
            try:
                await bot.send_message(player_id, _role_text(role, seat, scenario_name), parse_mode="HTML"); sent += 1
            except Exception:
                delivery_failures.append(player_id); logging.exception("failed to send role privately: user=%s game=%s", player_id, game_id)

        moderator_id = int(game.get("moderator_id") or 0)
        if moderator_id:
            roster = [f"{int(row['seat']):02d}. {html.escape(str(row.get('nickname') or row.get('first_name') or row.get('username') or row['player_id']))} — <b>{html.escape(role_map[str(int(row['player_id']))])}</b>" for row in players]
            try: await bot.send_message(moderator_id, "༄\n<b>🎭 نقش‌های بازی</b>\n\n" + "\n".join(roster), parse_mode="HTML")
            except Exception: logging.exception("failed to send moderator role roster: game=%s", game_id)

        state = dict(game.get("state") or {})
        state["role_delivery"] = {str(int(p["player_id"])): int(p["player_id"]) not in delivery_failures for p in players}
        lobby_message_id = state.get("lobby_message_id"); state["control_message_id"] = lobby_message_id
        app.runtime.state.games.update_game(game_id, state=state)
        if lobby_message_id:
            try:
                await bot.edit_message_text("🌅 <b>شروع روز</b>\n\n🎭 پخش نقش انجام شد.\n\nگرداننده می‌تواند سردست را انتخاب کند یا دور اول را شروع کند.", group_id, int(lobby_message_id), parse_mode="HTML", reply_markup=_day_markup(game_id))
            except Exception: logging.exception("failed to convert lobby message to day-control message game=%s", game_id)

        if delivery_failures:
            missing = [p for p in players if int(p["player_id"]) in set(delivery_failures)]
            mentions = "\n".join(f"• <a href=\"tg://user?id={int(p['player_id'])}\"><b>{html.escape(str(p.get('nickname') or p.get('first_name') or p.get('username') or p['player_id']))}</b></a>" for p in missing)
            try:
                me = await bot.get_me(); deep_link = f"https://t.me/{me.username}?start=role_{game_id}_{group_id}"
                missing_markup = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🎭 نقش من", url=deep_link))
                await bot.send_message(group_id, "🎭 <b>پخش نقش انجام شد</b>\n\n" + f"📨 تعداد نقش‌های ارسال‌شده: <b>{sent}/{len(players)}</b>\n" + f"❌ تعداد نقش‌های ارسال‌نشده: <b>{len(delivery_failures)}</b>\n\n" + "❗ <b>این بازیکنان نقش دریافت نکردن:</b>\n" + mentions + "\n\nبرای دریافت نقش روی دکمه زیر بزنید.", parse_mode="HTML", reply_markup=missing_markup)
            except Exception: logging.exception("failed to send missing-role report game=%s", game_id)
        else:
            await bot.send_message(group_id, f"🎭 <b>پخش نقش انجام شد</b>\n\n📨 تعداد نقش‌های ارسال‌شده: <b>{sent}/{len(players)}</b>", parse_mode="HTML")

        await callback.answer(f"✅ نقش‌ها پخش شد ({sent}/{len(players)} ارسال موفق)")
        logging.info("roles distributed: game=%s players=%d sent=%d failed=%d", game_id, len(players), sent, len(delivery_failures))

    app._role_distribution_handler = distribute_roles
    app._handle_role_deep_link = role_start_command
    dp.register_callback_query_handler(head_menu, lambda c: str(c.data or "").startswith("day:") and str(c.data or "").endswith(":head"), state="*")
    dp.register_callback_query_handler(lambda c: set_head(c, True), lambda c: str(c.data or "").startswith("day:") and str(c.data or "").endswith(":head_random"), state="*")
    dp.register_callback_query_handler(set_head, lambda c: str(c.data or "").startswith("day:") and ":head_pick:" in str(c.data), state="*")
    dp.register_callback_query_handler(distribute_roles, lambda c: c.data == "distribute_roles", state="*")
    logging.info("PRODUCTION_ROLE_DISTRIBUTION_ACTIVE")
    return True
