from __future__ import annotations

import html
import logging
from types import SimpleNamespace
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.game_management import GameManagement


async def _answer(_: Any, *args: Any, **kwargs: Any) -> None:
    return None


def _callback_like(message: types.Message, game_id: int, action: str = "refresh") -> Any:
    return SimpleNamespace(message=message, from_user=message.from_user, data=f"mgmt:{int(game_id)}:{action}", answer=_answer)


def _rows(management: GameManagement, game: dict[str, Any]) -> list[dict[str, Any]]:
    return management.app.runtime.state.games.list_players(game["id"])


def _name(management: GameManagement, row: dict[str, Any]) -> str:
    return management._name(row)


def _mention(row: dict[str, Any]) -> str:
    uid = int(row["player_id"])
    label = row.get("nickname") or row.get("first_name") or row.get("username") or row.get("name") or uid
    return f'<a href="tg://user?id={uid}"><b>{html.escape(str(label))}</b></a>'


def _active_players(management: GameManagement, game: dict[str, Any]) -> list[dict[str, Any]]:
    return [r for r in _rows(management, game) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead", "finished"}]


def _attendance_state(management: GameManagement, game: dict[str, Any]) -> dict[str, Any]:
    return dict(management._state(game).get("attendance") or {})


def _substitute_state(management: GameManagement, game: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Persistent text-command substitute list; this is the canonical source for replacement."""
    raw = management._state(game).get("substitutes") or {}
    return {str(k): dict(v or {}) for k, v in raw.items() if str(k).lstrip("-").isdigit()}


def _substitute_rows(management: GameManagement, game: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge the persistent text-command list with DB waiting/substitute rows."""
    merged: dict[int, dict[str, Any]] = {}
    for key, info in _substitute_state(management, game).items():
        uid = int(key)
        merged[uid] = {"player_id": uid, "seat": None, "status": "waiting", "is_substitute": True,
                       "nickname": info.get("nickname"), "first_name": info.get("first_name"),
                       "username": info.get("username"), "name": info.get("name")}
    for row in _rows(management, game):
        uid = int(row["player_id"])
        if row.get("seat") is None and str(row.get("status") or "") in {"waiting", "substitute"} and bool(row.get("is_substitute", False)):
            existing = merged.get(uid, {})
            for key in ("nickname", "first_name", "last_name", "username", "name"):
                if row.get(key):
                    existing[key] = row[key]
            existing["player_id"] = uid
            existing["seat"] = row.get("seat")
            existing["status"] = row.get("status") or existing.get("status") or "waiting"
            existing["is_substitute"] = True
            merged[uid] = existing
    return list(merged.values())


def _day_control_markup(game_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎩 انتخاب سردست", callback_data=f"day:{int(game_id)}:head"),
        InlineKeyboardButton("⚔ وضعیت چالش", callback_data=f"mgmt:{int(game_id)}:challenge"),
        InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"),
        InlineKeyboardButton("⚙️ مدیریت بازی", callback_data=f"mgmt:{int(game_id)}:open"),
    )


async def _render_attendance(management: GameManagement, game: dict[str, Any]) -> bool:
    state = management._state(game)
    message_id = state.get("attendance_message_id")
    if not message_id:
        return False
    players = _active_players(management, game)
    attendance = _attendance_state(management, game)
    active_ids = {str(int(r["player_id"])) for r in players}
    attendance = {k: bool(v) for k, v in attendance.items() if k in active_ids}
    for uid in active_ids:
        attendance.setdefault(uid, False)
    management._save(game, attendance=attendance)
    lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""]
    for row in sorted(players, key=lambda r: int(r.get("seat") or 999)):
        ready = bool(attendance.get(str(int(row["player_id"])), False))
        lines.append(f"{'✅' if ready else '⚪️'} {int(row['seat']):02d}. {_mention(row)}")
    if not players:
        lines.append("❌ بازیکن فعالی در بازی وجود ندارد.")
    lines.extend(["", "لطفاً برای اعلام حاضری، «آماده‌ام» را بزنید."])
    kb = InlineKeyboardMarkup(row_width=1)
    if players:
        kb.add(InlineKeyboardButton("آماده‌ام ✅", callback_data=f"mgmt:{int(game['id'])}:attendance_ready"))
    try:
        await management.app.bot.edit_message_text("\n".join(lines), int(game["group_chat_id"]), int(message_id), parse_mode="HTML", reply_markup=kb)
        return True
    except Exception:
        logging.exception("attendance render failed game=%s", game.get("id"))
        return False


async def _notify_all_ready(management: GameManagement, game: dict[str, Any]) -> None:
    state = management._state(game)
    if state.get("attendance_announced"):
        return
    management._save(game, attendance_announced=True)
    gid = int(game["group_chat_id"])
    moderator_id = int(game.get("moderator_id") or 0)
    try:
        await management.app.bot.send_message(gid, "🎉 <b>همه بازیکنان آماده‌اند.</b>", parse_mode="HTML")
    except Exception:
        logging.exception("all-ready group notification failed game=%s", game.get("id"))
    if moderator_id:
        try:
            await management.app.bot.send_message(moderator_id, f"🎉 بازی شماره {int(game.get('event_number') or 1)}: همه بازیکنان آماده‌اند.")
        except Exception:
            pass


async def _refresh_lobby_if_needed(management: GameManagement, game: dict[str, Any]) -> None:
    if str(game.get("status") or "") != "lobby":
        return
    renderer = getattr(management.app, "_render_production_lobby", None)
    if renderer:
        try:
            await renderer(int(game["group_chat_id"]), game)
        except Exception:
            logging.exception("lobby refresh after management mutation failed game=%s", game.get("id"))


async def _render_control_message(management: GameManagement, game: dict[str, Any], target_message: Any = None) -> bool:
    state = management._state(game)
    message_id = state.get("control_message_id") or state.get("lobby_message_id")
    if target_message is not None:
        message_id = getattr(target_message, "message_id", None) or message_id
    if not message_id:
        return False
    day = int(state.get("day_number") or 1)
    head = state.get("head_seat")
    head_text = f"\n🎩 <b>سردست:</b> صندلی {int(head)}" if head else ""
    text = f"🌅 <b>شروع روز {day}</b>{head_text}\n\nگرداننده می‌تواند سردست را انتخاب کند یا دور را شروع کند."
    try:
        await management.app.bot.edit_message_text(text, int(game["group_chat_id"]), int(message_id), parse_mode="HTML", reply_markup=_day_control_markup(int(game["id"])))
        if state.get("control_message_id") != int(message_id):
            management._save(game, control_message_id=int(message_id))
        return True
    except Exception:
        logging.exception("failed to restore live-game control message game=%s", game.get("id"))
        return False


def install(app: Any, management: GameManagement) -> bool:
    async def close_to_control(self: GameManagement, callback: Any):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        if str(game.get("status") or "") == "lobby":
            renderer = getattr(self.app, "_render_production_lobby", None)
            ok = bool(renderer and await renderer(gid, game))
            await callback.answer("⬅️ به لابی برگشتید." if ok else "❌ بازگشت به لابی انجام نشد.", show_alert=not ok)
            return
        ok = await _render_control_message(self, game, callback.message)
        await callback.answer("⬅️ پنل مدیریت بسته شد." if ok else "❌ بازگردانی منوی بازی انجام نشد.", show_alert=not ok)

    async def replace(self: GameManagement, callback: Any):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        substitutes = _substitute_rows(self, game)
        kb = InlineKeyboardMarkup(row_width=2)
        for row in substitutes:
            kb.insert(InlineKeyboardButton(_name(self, row), callback_data=f"mgmt:{int(game['id'])}:replace_sub:{int(row['player_id'])}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{int(game['id'])}:open"))
        text = "🔄 <b>جایگزین بازیکن</b>\n\nابتدا بازیکن جایگزین را انتخاب کنید:"
        if not substitutes:
            text += "\n\n❌ در حال حاضر بازیکن جایگزین/رزرو شده‌ای وجود ندارد."
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def replace_sub(self: GameManagement, callback: Any):
        parts = str(callback.data or "").split(":")
        if len(parts) != 4 or parts[0] != "mgmt" or parts[2] != "replace_sub": return
        gid = int(callback.message.chat.id); game = self._game(gid); substitute_id = int(parts[3])
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        substitute = next((r for r in _substitute_rows(self, game) if int(r["player_id"]) == substitute_id), None)
        if not substitute:
            await callback.answer("❌ بازیکن جایگزین معتبر نیست.", show_alert=True); return
        rows = _rows(self, game)
        targets = [r for r in rows if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "dead", "finished"}]
        kb = InlineKeyboardMarkup(row_width=2)
        for row in sorted(targets, key=lambda r: int(r.get("seat") or 999)):
            kb.insert(InlineKeyboardButton(f"{int(row['seat'])}. {_name(self, row)}", callback_data=f"mgmt:{int(game['id'])}:replace_target:{substitute_id}:{int(row['player_id'])}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{int(game['id'])}:open"))
        await callback.message.edit_text(f"🔄 <b>انتخاب بازیکن هدف</b>\n\nجایگزین: {_mention(substitute)}\n\nبازیکنی که باید جایگزین شود را انتخاب کنید:", parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def replace_target(self: GameManagement, callback: Any):
        parts = str(callback.data or "").split(":")
        if len(parts) != 5 or parts[0] != "mgmt" or parts[2] != "replace_target": return
        gid = int(callback.message.chat.id); game = self._game(gid); substitute_id, target_id = int(parts[3]), int(parts[4])
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        substitute = next((r for r in _substitute_rows(self, game) if int(r["player_id"]) == substitute_id), None)
        target = next((r for r in _rows(self, game) if int(r["player_id"]) == target_id), None)
        if not substitute or not target or target.get("seat") is None:
            await callback.answer("❌ اطلاعات جایگزینی نامعتبر است.", show_alert=True); return
        seat = int(target["seat"])
        try:
            # Remove the old player from the active seat.
            self.app.runtime.state.games.set_player_seat(game["id"], target_id, None)
            self.app.runtime.state.games.set_player_status(game["id"], target_id, "substituted")
            # A text-command substitute may not have a DB membership row yet; create it here.
            existing_sub = next((r for r in _rows(self, game) if int(r["player_id"]) == substitute_id), None)
            if existing_sub:
                self.app.runtime.state.games.set_player_seat(game["id"], substitute_id, seat)
                self.app.runtime.state.games.set_player_status(game["id"], substitute_id, "active")
            else:
                self.app.runtime.state.lobby.join(game["id"], substitute_id, seat, is_substitute=False)
            if target.get("role"):
                self.app.runtime.state.games.set_player_role(game["id"], substitute_id, target.get("role"))
            self.app.runtime.state.games.set_player_alive(game["id"], substitute_id, True)
            state = self._state(game)
            subs = dict(state.get("substitutes") or {})
            subs.pop(str(substitute_id), None)
            attendance = dict(state.get("attendance") or {})
            attendance.pop(str(target_id), None); attendance[str(substitute_id)] = False
            self._save(game, substitutes=subs, attendance=attendance)
        except Exception:
            logging.exception("management replacement failed game=%s", game.get("id")); await callback.answer("❌ جایگزینی انجام نشد.", show_alert=True); return
        await callback.message.edit_text(f"✅ {_mention(target)} با {_mention(substitute)} جایگزین شد.\n💺 صندلی {seat}", parse_mode="HTML", reply_markup=self.panel(game["id"]))
        await _refresh_lobby_if_needed(self, game); await _render_attendance(self, game); await callback.answer("✅ جایگزینی انجام شد.")

    async def birthday(self: GameManagement, callback: Any):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = [r for r in _rows(self, game) if str(r.get("status") or "") in {"dead", "removed"} or not bool(r.get("is_alive", True))]
        kb = InlineKeyboardMarkup(row_width=2)
        for row in rows:
            label = f"{row.get('seat')}. {_name(self, row)}" if row.get("seat") is not None else _name(self, row)
            kb.insert(InlineKeyboardButton(label, callback_data=f"mgmt:{int(game['id'])}:birthday_pick:{int(row['player_id'])}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{int(game['id'])}:open"))
        text = "🎂 <b>تولد بازیکن</b>\n\nبازیکن مرده/حذف‌شده را انتخاب کنید:"
        if not rows: text += "\n\n❌ بازیکن مرده یا حذف‌شده‌ای وجود ندارد."
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def birthday_pick(self: GameManagement, callback: Any):
        parts = str(callback.data or "").split(":")
        if len(parts) != 4 or parts[0] != "mgmt" or parts[2] != "birthday_pick": return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(parts[3])
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        rows = _rows(self, game); player = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not player: await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True); return
        seat = player.get("seat")
        if seat is None:
            scenario = self.scenarios.get_by_id(int(game.get("scenario_id"))) if game.get("scenario_id") else None
            capacity = len((scenario or {}).get("roles") or [])
            occupied = {int(r["seat"]) for r in rows if r.get("seat") is not None and int(r["player_id"]) != uid and str(r.get("status") or "") not in {"removed", "dead", "finished"}}
            seat = next((n for n in range(1, capacity + 1) if n not in occupied), None)
        if seat is None: await callback.answer("❌ صندلی خالی برای بازگشت این بازیکن وجود ندارد.", show_alert=True); return
        try:
            self.app.runtime.state.games.set_player_seat(game["id"], uid, int(seat)); self.app.runtime.state.games.set_player_status(game["id"], uid, "active"); self.app.runtime.state.games.set_player_alive(game["id"], uid, True)
            attendance = _attendance_state(self, game); attendance[str(uid)] = False; self._save(game, attendance=attendance)
        except Exception:
            logging.exception("birthday restore failed game=%s user=%s", game.get("id"), uid); await callback.answer("❌ بازگردانی بازیکن انجام نشد.", show_alert=True); return
        await callback.message.edit_text(f"🎂 {_mention(player)} دوباره وارد بازی شد.\n💺 صندلی {int(seat)}", parse_mode="HTML", reply_markup=self.panel(game["id"]))
        await _refresh_lobby_if_needed(self, game); await _render_attendance(self, game); await callback.answer("🎂 بازیکن به بازی برگشت.")

    async def attendance(self: GameManagement, callback: Any):
        gid = int(callback.message.chat.id); game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game): await callback.answer("⛔ دسترسی ندارید.", show_alert=True); return
        players = _active_players(self, game)
        if not players: await callback.answer("❌ بازیکن فعالی در بازی وجود ندارد.", show_alert=True); return
        state = self._state(game); attendance = dict(state.get("attendance") or {})
        active_ids = {str(int(r["player_id"])) for r in players}; attendance = {k: bool(v) for k, v in attendance.items() if k in active_ids}
        for uid in active_ids: attendance.setdefault(uid, False)
        self._save(game, attendance=attendance, attendance_announced=False)
        lines = ["🟢 <b>بازیکنان حاضر در لیست</b>", ""] + [f"⚪️ {int(r['seat']):02d}. {_mention(r)}" for r in sorted(players, key=lambda r: int(r.get("seat") or 999))] + ["", "لطفاً برای اعلام حاضری، «آماده‌ام» را بزنید."]
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("آماده‌ام ✅", callback_data=f"mgmt:{int(game['id'])}:attendance_ready"))
        old_id = state.get("attendance_message_id")
        try:
            if old_id:
                await self.app.bot.edit_message_text("\n".join(lines), gid, int(old_id), parse_mode="HTML", reply_markup=kb); message_id = int(old_id)
            else:
                msg = await self.app.bot.send_message(gid, "\n".join(lines), parse_mode="HTML", reply_markup=kb); message_id = int(msg.message_id)
            self._save(game, attendance_message_id=message_id); await callback.answer("✅ لیست حاضری ایجاد شد.")
        except Exception:
            logging.exception("attendance message creation failed game=%s", game.get("id")); await callback.answer("❌ ایجاد لیست حاضری انجام نشد.", show_alert=True)

    async def attendance_ready(self: GameManagement, callback: Any):
        parts = str(callback.data or "").split(":")
        if len(parts) != 3 or parts[0] != "mgmt" or parts[2] != "attendance_ready": return
        gid = int(callback.message.chat.id); game = self._game(gid); uid = int(callback.from_user.id)
        if not game: await callback.answer("❌ بازی فعالی وجود ندارد.", show_alert=True); return
        player = next((r for r in _rows(self, game) if int(r["player_id"]) == uid), None)
        if not player or player.get("seat") is None or str(player.get("status") or "") in {"removed", "dead", "finished"}:
            await callback.answer("⛔ فقط بازیکنان حاضر در بازی می‌توانند اعلام آمادگی کنند.", show_alert=True); return
        attendance = _attendance_state(self, game); attendance[str(uid)] = True; self._save(game, attendance=attendance)
        await _render_attendance(self, game)
        players = _active_players(self, game)
        if players and all(bool(attendance.get(str(int(r["player_id"])), False)) for r in players): await _notify_all_ready(self, game)
        await callback.answer("✅ آمادگی شما ثبت شد.")

    GameManagement.close = close_to_control
    GameManagement.replace = replace
    GameManagement.replace_sub = replace_sub
    GameManagement.replace_target = replace_target
    GameManagement.birthday = birthday
    GameManagement.birthday_pick = birthday_pick
    GameManagement.attendance = attendance
    GameManagement.attendance_ready = attendance_ready

    async def restore_lobby(message: types.Message):
        gid = int(message.chat.id); game = management._game(gid)
        if not game: await message.reply("❌ بازی فعالی وجود ندارد."); return
        if not await management._allowed(message, gid, game): await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند لابی را بازسازی کند."); return
        if str(game.get("status") or "") != "lobby":
            await message.reply("ℹ️ بازی در حال اجراست؛ برای بازگشت به منوی شروع روز از «بستن» استفاده کنید."); return
        try:
            renderer = getattr(app, "_render_production_lobby", None)
            ok = bool(renderer and await renderer(gid, game))
            if not ok: await message.reply("❌ بازسازی لابی انجام نشد؛ لابی فعال نیست یا پیام قابل ویرایش نیست.")
        except Exception:
            logging.exception("MANAGEMENT_NAVIGATION: failed to restore lobby")
            await message.reply("❌ بازسازی لابی انجام نشد؛ خطا در لاگ ثبت شد.")

    app.dp.register_message_handler(restore_lobby, lambda message: (message.text or "").strip().lower() in {"بازسازی لابی", "بازگردانی لابی", "برگرداندن لابی", "لابی", "/لابی", "/lobby"}, content_types=types.ContentTypes.TEXT, state="*")
    app.dp.register_callback_query_handler(management.attendance_ready, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").endswith(":attendance_ready"), state="*")
    logging.info("MANAGEMENT_NAVIGATION installed: replacement, birthday, attendance and lobby restore")
    return True
