"""Feature-parity handlers for the clean MafiaNights application.

This module deliberately stores game-affecting compatibility data inside the
persistent game state instead of module globals. It is attached to the clean
application during migration and can later be split into smaller services.
"""
from __future__ import annotations

import html
from typing import Any, Optional

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class AddScenarioParity(StatesGroup):
    waiting_for_name = State()
    waiting_for_roles = State()
    waiting_for_min_players = State()


class FeatureParity:
    def __init__(self, app):
        self.app = app

    def _game(self, group_id: int) -> Optional[dict[str, Any]]:
        return self.app.runtime.state.active_game(group_id)

    def _state(self, group_id: int) -> dict[str, Any]:
        game = self._game(group_id)
        return dict((game or {}).get("state") or {})

    def _save_state(self, group_id: int, **changes: Any) -> bool:
        game = self._game(group_id)
        if not game:
            return False
        state = self._state(group_id)
        state.update(changes)
        if isinstance(game, dict):
            game["state"] = dict(state)
        self.app.runtime.state.games.update_game(game["id"], state=state)
        return True

    def _admin_ids(self, group_id: int) -> set[int]:
        game = self._game(group_id)
        stored = (game or {}).get("state") or {}
        return {int(x) for x in stored.get("admin_ids", [])}

    async def _is_admin(self, callback_or_message: Any, group_id: int) -> bool:
        uid = int(callback_or_message.from_user.id)
        game = self._game(group_id)
        moderator = int((game or {}).get("moderator_id") or 0)
        if uid == moderator:
            return True
        try:
            member = await self.app.bot.get_chat_member(group_id, uid)
            return member.status in {"creator", "administrator"}
        except Exception:
            return False

    def _moderator_id(self, group_id: int) -> Optional[int]:
        game = self._game(group_id)
        value = (game or {}).get("moderator_id")
        return int(value) if value else None

    def _next_settings(self, group_id: int) -> dict[str, bool]:
        state = self._state(group_id)
        settings = dict(state.get("next_settings") or {})
        return {
            "allow_players_next": bool(settings.get("allow_players_next", True)),
            "allow_moderator_next": bool(settings.get("allow_moderator_next", True)),
            "anti_spam": bool(settings.get("anti_spam", True)),
        }

    def _substitutes(self, group_id: int) -> dict[str, dict[str, Any]]:
        return dict(self._state(group_id).get("substitutes") or {})

    def _removed(self, group_id: int) -> dict[str, dict[str, Any]]:
        return dict(self._state(group_id).get("removed_players") or {})

    def panel_keyboard(self, group_id: int) -> InlineKeyboardMarkup:
        settings = self._next_settings(group_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for label, data in [
            ("👥 لیست بازیکنان", "fp:list_players"),
            ("📤 ارسال مجدد نقش‌ها", "fp:resend_roles"),
            ("🗑 حذف بازیکن", "fp:remove_player"),
            ("🔄 جایگزین بازیکن", "fp:replace_player"),
            ("🎂 بازگردانی بازیکن", "fp:revive_player"),
            ("⚔ وضعیت چالش", "fp:challenge_status"),
            ("🎩 تنظیم گرداننده", "fp:moderator"),
            (f"⏭ نکست بازیکن: {'فعال' if settings['allow_players_next'] else 'غیرفعال'}", "fp:toggle_player_next"),
            (f"⏭ نکست گرداننده: {'فعال' if settings['allow_moderator_next'] else 'غیرفعال'}", "fp:toggle_mod_next"),
            (f"🛡 ضداسپم نکست: {'فعال' if settings['anti_spam'] else 'غیرفعال'}", "fp:toggle_next_antispam"),
            ("📜 مدیریت سناریو", "fp:scenarios"),
            ("🚫 لغو بازی", "fp:cancel"),
            ("⬅️ بازگشت", "help"),
        ]:
            kb.add(InlineKeyboardButton(label, callback_data=data))
        return kb

    async def open_panel(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id:
            await callback.answer("🚫 بازی فعالی پیدا نشد.", show_alert=True)
            return
        if not await self._is_admin(callback, group_id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True)
            return
        await callback.message.edit_text("🎮 <b>مدیریت بازی</b>", parse_mode="HTML", reply_markup=self.panel_keyboard(group_id))
        await callback.answer()

    async def list_players(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id:
            await callback.answer("🚫 بازی فعال نیست.", show_alert=True)
            return
        if not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        rows = self.app._players_by_seat(group_id)
        if not rows:
            await callback.message.answer("👥 هیچ بازیکنی در بازی نیست.")
        else:
            lines = [f"{seat:02d}. <a href='tg://user?id={int(row['player_id'])}'>{html.escape(self.app._name(int(row['player_id'])))}</a>" for seat, row in sorted(rows.items())]
            await callback.message.answer("📜 <b>لیست بازیکنان</b>\n\n" + "\n".join(lines), parse_mode="HTML")
        await callback.answer()

    async def resend_roles(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        state = self._state(group_id)
        role_map = {int(k): v for k, v in (state.get("last_role_map") or {}).items()}
        if not role_map:
            await callback.message.answer("⚠️ نقش‌ها هنوز پخش نشده‌اند.")
            await callback.answer()
            return
        sent = 0
        rows = self.app._players_by_seat(group_id)
        for seat, row in sorted(rows.items()):
            uid = int(row["player_id"])
            role = role_map.get(uid)
            if not role:
                continue
            try:
                await self.app.bot.send_message(uid, f"🎭 نقش شما: <b>{html.escape(str(role))}</b>\n💺 صندلی: {seat}")
                sent += 1
            except Exception:
                pass
        mod = self._moderator_id(group_id)
        if mod:
            text = "༄\n<b>Mafia Nights</b>\n\n🎭 <b>لیست نقش‌ها</b>\n"
            for seat, row in sorted(rows.items()):
                uid = int(row["player_id"])
                text += f"{seat:02d} {html.escape(self.app._name(uid))} — {html.escape(str(role_map.get(uid, '❓')))}\n"
            await self.app.bot.send_message(mod, text, parse_mode="HTML")
        await callback.answer(f"✅ نقش‌ها برای {sent} بازیکن ارسال شد.")

    async def remove_player(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, row in sorted(self.app._players_by_seat(group_id).items()):
            kb.add(InlineKeyboardButton(f"{seat}. {self.app._name(int(row['player_id']))}", callback_data=f"fp:remove:{seat}"))
        await callback.message.answer("🗑 بازیکن را انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def remove_confirm(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        seat = int(callback.data.rsplit(":", 1)[1])
        row = self.app._players_by_seat(group_id).get(seat)
        if not row:
            await callback.answer("⚠️ بازیکن پیدا نشد.", show_alert=True)
            return
        uid = int(row["player_id"])
        removed = self._removed(group_id)
        removed[str(seat)] = {"id": uid, "name": self.app._name(uid), "role": (self._state(group_id).get("last_role_map") or {}).get(str(uid))}
        players = dict(self._state(group_id).get("players_in_game") or {})
        players.pop(str(seat), None)
        await self._save_state(group_id, removed_players=removed, players_in_game=players)
        try:
            self.app.runtime.lobby.leave(group_id, uid)
        except Exception:
            pass
        await callback.message.answer(f"✅ {html.escape(self.app._name(uid))} از بازی حذف شد.")
        await callback.answer()

    async def revive_player(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        removed = self._removed(group_id)
        if not removed:
            await callback.message.answer("🚫 لیست بازیکنان خارج‌شده خالی است.")
            await callback.answer()
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, info in sorted(removed.items(), key=lambda item: int(item[0])):
            kb.add(InlineKeyboardButton(f"{seat}. {info.get('name', '❓')}", callback_data=f"fp:revive:{seat}"))
        await callback.message.answer("🎂 بازیکن را برای بازگردانی انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def revive_confirm(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        seat = callback.data.rsplit(":", 1)[1]
        removed = self._removed(group_id)
        info = removed.pop(seat, None)
        if not info:
            await callback.answer("⚠️ موردی پیدا نشد.", show_alert=True)
            return
        uid = int(info["id"])
        self.app.runtime.lobby.join(group_id, uid, int(seat))
        players = dict(self._state(group_id).get("players_in_game") or {})
        players[seat] = {"id": uid, "name": info.get("name") or self.app._name(uid), "role": info.get("role")}
        await self._save_state(group_id, removed_players=removed, players_in_game=players)
        await callback.message.answer(f"✅ {html.escape(info.get('name', '❓'))} با صندلی {seat} بازگردانده شد.")
        await callback.answer()

    async def replace_player(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        subs = self._substitutes(group_id)
        if not subs:
            await callback.message.answer("🚫 لیست جایگزین‌ها خالی است.")
            await callback.answer()
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for uid, info in subs.items():
            kb.add(InlineKeyboardButton(info.get("name") or str(uid), callback_data=f"fp:replace-sub:{uid}"))
        await callback.message.answer("👥 جایگزین را انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def choose_replace_seat(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        sub_id = callback.data.rsplit(":", 1)[1]
        rows = self.app._players_by_seat(group_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, row in sorted(rows.items()):
            kb.add(InlineKeyboardButton(f"{seat}. {self.app._name(int(row['player_id']))}", callback_data=f"fp:replace:{sub_id}:{seat}"))
        await callback.message.answer("👤 بازیکن جایگزین، صندلی را انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def replace_confirm(self, callback: types.CallbackQuery):
        group_id = callback.message.chat.id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        _, _, sub_id, seat_text = callback.data.split(":")
        seat = int(seat_text)
        subs = self._substitutes(group_id)
        sub = subs.pop(str(sub_id), None)
        old = self.app._players_by_seat(group_id).get(seat)
        if not sub or not old:
            await callback.answer("⚠️ اطلاعات جایگزینی معتبر نیست.", show_alert=True)
            return
        old_uid = int(old["player_id"])
        new_uid = int(sub_id)
        self.app.runtime.lobby.leave(group_id, old_uid)
        self.app.runtime.lobby.join(group_id, new_uid, seat)
        state = self._state(group_id)
        role_map = dict(state.get("last_role_map") or {})
        if str(old_uid) in role_map:
            role_map[str(new_uid)] = role_map.pop(str(old_uid))
        players = dict(state.get("players_in_game") or {})
        players[str(seat)] = {"id": new_uid, "name": sub.get("name") or self.app._name(new_uid), "role": role_map.get(str(new_uid))}
        await self._save_state(group_id, substitutes=subs, last_role_map=role_map, players_in_game=players)
        role = role_map.get(str(new_uid))
        if role:
            try:
                await self.app.bot.send_message(new_uid, f"🎭 نقش منتقل‌شده شما: <b>{html.escape(str(role))}</b>\n💺 صندلی: {seat}")
            except Exception:
                pass
        await callback.message.answer(f"✅ {html.escape(self.app._name(old_uid))} با {html.escape(sub.get('name') or self.app._name(new_uid))} جایگزین شد.")
        await callback.answer()

    async def add_substitute_message(self, message: types.Message):
        group_id = message.chat.id
        game = self._game(group_id)
        if not game:
            await message.reply("⚠️ بازی فعالی وجود ندارد.")
            return
        subs = self._substitutes(group_id)
        uid = int(message.from_user.id)
        if str(uid) in subs:
            await message.reply("ℹ️ شما قبلاً در لیست جایگزین هستید.")
            return
        subs[str(uid)] = {"id": uid, "name": message.from_user.full_name}
        self._save_state(group_id, substitutes=subs)
        await message.reply(f"✅ {html.escape(message.from_user.full_name)} به لیست جایگزین اضافه شد.")

    async def seat_command(self, message: types.Message):
        rows = self.app._players_by_seat(message.chat.id)
        uid = int(message.from_user.id)
        seat = next((s for s, row in rows.items() if int(row["player_id"]) == uid), None)
        await message.reply(f"🔹 شما در صندلی شماره {seat} هستید." if seat else "⚠️ شما در بازی ثبت نشده‌اید.")

    async def seats_command(self, message: types.Message):
        rows = self.app._players_by_seat(message.chat.id)
        if not rows:
            await message.reply("🚫 هیچ لیست صندلی فعالی وجود ندارد.")
            return
        await message.reply("📋 لیست صندلی‌ها:\n\n" + "\n".join(f"{s:02d}. {html.escape(self.app._name(int(r['player_id'])))}" for s, r in sorted(rows.items())))

    async def role_command(self, message: types.Message):
        if message.chat.type != "private":
            await message.reply("ℹ️ برای دریافت نقش، این دستور را در پیوی ربات ارسال کنید.")
            return
        group_id = self.app.ui.group_chat_id
        role = None
        if group_id:
            role = (self._state(group_id).get("last_role_map") or {}).get(str(message.from_user.id))
        await message.reply(f"🔐 نقش شما: <b>{html.escape(str(role))}</b>" if role else "⚠️ هنوز نقشی برای شما اختصاص داده نشده.", parse_mode="HTML")

    async def status_command(self, message: types.Message):
        group_id = message.chat.id
        snap = self.app.runtime.snapshot(group_id)
        game = snap.get("game") or {}
        rows = self.app._players_by_seat(group_id)
        day = self.app.runtime.day_snapshot(group_id)
        turn = self.app.runtime.current_turn(group_id)
        text = ("🔎 <b>وضعیت بازی</b>\n\n" f"👥 بازیکنان: {len(rows)}\n" f"📝 سناریو: {game.get('scenario_id') or '---'}\n" f"🎩 گرداننده: {self.app._name(int(game.get('moderator_id'))) if game.get('moderator_id') else '---'}\n" f"🎯 نوبت فعلی: {turn.get('seat') if turn else '---'}\n" f"🌞/🌙 فاز: {(day or {}).get('phase') or game.get('status') or '---'}")
        await message.reply(text, parse_mode="HTML")

    async def players_command(self, message: types.Message):
        group_id = message.chat.id
        if not await self._is_admin(message, group_id):
            await message.reply("⛔ فقط گرداننده یا مدیران گروه.")
            return
        rows = self.app._players_by_seat(group_id)
        if not rows:
            await message.reply("🚫 هیچ بازیکنی ثبت نشده است.")
            return
        await message.reply("📜 لیست بازیکنان:\n\n" + "\n".join(f"{s:02d}. {html.escape(self.app._name(int(r['player_id'])))}" for s, r in sorted(rows.items())))

    async def tag_list(self, message: types.Message):
        rows = self.app._players_by_seat(message.chat.id)
        if not rows:
            await message.reply("👥 هیچ بازیکنی در بازی نیست.")
            return
        mentions = " ".join(f"<a href='tg://user?id={int(r['player_id'])}'>{html.escape(self.app._name(int(r['player_id'])))}</a>" for _, r in sorted(rows.items()))
        await message.reply("📢 تگ بازیکنان حاضر:\n" + mentions, parse_mode="HTML")

    async def tag_admins(self, message: types.Message):
        try:
            admins = await self.app.bot.get_chat_administrators(message.chat.id)
        except Exception:
            await message.reply("⚠️ خطا در دریافت مدیران گروه.")
            return
        mentions = " ".join(f"<a href='tg://user?id={a.user.id}'>{html.escape(a.user.full_name or str(a.user.id))}</a>" for a in admins)
        await message.reply("📢 تگ مدیران گروه:\n" + mentions, parse_mode="HTML")

    async def challenge_request(self, callback: types.CallbackQuery):
        group_id = callback.message.chat.id
        if not self.app.challenge_enabled.get(group_id, True):
            await callback.answer("⚔ چالش خاموش است.", show_alert=True)
            return
        target_seat = int(callback.data.rsplit(":", 1)[1])
        row = self.app._players_by_seat(group_id).get(target_seat)
        if not row:
            await callback.answer("⚠️ بازیکن پیدا نشد.", show_alert=True)
            return
        challenger = int(callback.from_user.id)
        target = int(row["player_id"])
        if challenger == target:
            await callback.answer("❌ نمی‌توانید خودتان را چالش کنید.", show_alert=True)
            return
        pending = dict(self._state(group_id).get("challenge_requests") or {})
        bucket = dict(pending.get(str(target_seat)) or {})
        if str(challenger) in bucket:
            await callback.answer("⚠️ قبلاً درخواست داده‌اید.", show_alert=True)
            return
        bucket[str(challenger)] = "pending"
        pending[str(target_seat)] = bucket
        await self._save_state(group_id, challenge_requests=pending)
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ قبول قبل", callback_data=f"fp:accept:before:{challenger}:{target}"),
            InlineKeyboardButton("✅ قبول بعد", callback_data=f"fp:accept:after:{challenger}:{target}"),
            InlineKeyboardButton("❌ رد", callback_data=f"fp:reject:{challenger}:{target}"),
        )
        await self.app.bot.send_message(group_id, f"⚔ {html.escape(self.app._name(challenger))} برای {html.escape(self.app._name(target))} درخواست چالش داد.", reply_markup=kb)
        await callback.answer("⏳ درخواست چالش ثبت شد.")

    async def challenge_response(self, callback: types.CallbackQuery):
        group_id = callback.message.chat.id
        parts = callback.data.split(":")
        action, timing, challenger, target = parts[2], parts[3] if len(parts) > 3 else None, int(parts[-2]), int(parts[-1])
        if int(callback.from_user.id) not in {target, self._moderator_id(group_id)}:
            await callback.answer("⛔ فقط صاحب نوبت یا گرداننده.", show_alert=True)
            return
        pending = dict(self._state(group_id).get("challenge_requests") or {})
        target_seat = next((s for s, r in self.app._players_by_seat(group_id).items() if int(r["player_id"]) == target), None)
        if target_seat is not None:
            bucket = dict(pending.get(str(target_seat)) or {})
            bucket.pop(str(challenger), None)
            pending[str(target_seat)] = bucket
        if action == "reject":
            await self._save_state(group_id, challenge_requests=pending)
            await callback.message.edit_reply_markup(reply_markup=None)
            await self.app.bot.send_message(group_id, f"🚫 {html.escape(self.app._name(target))} درخواست چالش را رد کرد.")
            await callback.answer()
            return
        if timing not in {"before", "after"}:
            await callback.answer("⚠️ نوع چالش نامعتبر.", show_alert=True)
            return
        if timing == "after":
            after = dict(self._state(group_id).get("pending_challenges") or {})
            after[str(target_seat)] = challenger
            await self._save_state(group_id, challenge_requests=pending, pending_challenges=after)
            await callback.message.edit_reply_markup(reply_markup=None)
            await self.app.bot.send_message(group_id, f"⚔ چالش بعد از صحبت برای {html.escape(self.app._name(target))} ثبت شد.")
            await callback.answer()
            return
        challenger_seat = next((s for s, r in self.app._players_by_seat(group_id).items() if int(r["player_id"]) == challenger), None)
        if challenger_seat is None:
            await callback.answer("⚠️ چالش‌کننده صندلی ندارد.", show_alert=True)
            return
        current = self.app.runtime.current_turn(group_id)
        paused = dict(self._state(group_id).get("paused_turn") or {})
        if current:
            paused = {"turn_id": str(current["id"]), "seat": int(current.get("seat") or target_seat), "duration": int(current.get("duration_seconds") or 120)}
            self.app.runtime.finish_turn(str(current["id"]), {"finish_reason": "challenge_before"})
        await self._save_state(group_id, challenge_requests=pending, paused_turn=paused, challenge_mode=True)
        await callback.message.edit_reply_markup(reply_markup=None)
        await self.app.start_turn(group_id, challenger_seat, self.app._current_index(group_id), challenge=True)
        await callback.answer("⚔ چالش قبل از صحبت شروع شد.")

    async def moderator_menu(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        admins = await self.app.bot.get_chat_administrators(group_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for member in admins:
            kb.add(InlineKeyboardButton(member.user.full_name or str(member.user.id), callback_data=f"fp:setmod:{member.user.id}"))
        await callback.message.edit_text("🎩 گرداننده جدید را انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def set_moderator(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        uid = int(callback.data.rsplit(":", 1)[1])
        game = self._game(group_id)
        if game:
            self.app.runtime.state.games.update_game(game["id"], moderator_id=uid)
            game["moderator_id"] = uid
        await callback.message.edit_text(f"✅ گرداننده جدید: <b>{html.escape(self.app._name(uid))}</b>", parse_mode="HTML", reply_markup=self.panel_keyboard(group_id))
        await callback.answer()

    async def toggle_next(self, callback: types.CallbackQuery, key: str):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        settings = self._next_settings(group_id)
        settings[key] = not settings[key]
        await self._save_state(group_id, next_settings=settings)
        await callback.message.edit_reply_markup(reply_markup=self.panel_keyboard(group_id))
        await callback.answer("✔️ تنظیمات ذخیره شد.")

    async def cancel(self, callback: types.CallbackQuery):
        group_id = self.app.ui.group_chat_id
        if not group_id or not await self._is_admin(callback, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        game = self._game(group_id)
        if game:
            self.app.runtime.state.games.update_game(game["id"], status="finished", state={})
            game["status"] = "finished"
            game["state"] = {}
        if self.app.ui.turn_timer_task and not self.app.ui.turn_timer_task.done():
            self.app.ui.turn_timer_task.cancel()
        await callback.message.edit_text("🚫 بازی لغو شد.")
        await callback.answer("بازی لغو شد.")

    async def scenario_menu(self, callback: types.CallbackQuery):
        if not await self._is_admin(callback, self.app.ui.group_chat_id or 0):
            await callback.answer("⛔ فقط مدیران گروه.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("➕ افزودن سناریو", callback_data="fp:add_scenario"),
            InlineKeyboardButton("➖ حذف سناریو", callback_data="fp:remove_scenario"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="fp:panel"),
        )
        await callback.message.edit_text("📜 <b>مدیریت سناریو</b>", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def add_scenario_start(self, callback: types.CallbackQuery, state: FSMContext):
        await callback.message.answer("📝 نام سناریو را وارد کنید:")
        await state.set_state(AddScenarioParity.waiting_for_name)
        await callback.answer()

    async def add_scenario_name(self, message: types.Message, state: FSMContext):
        name = (message.text or "").strip()
        if not name:
            await message.answer("⚠️ نام سناریو نمی‌تواند خالی باشد.")
            return
        await state.update_data(name=name)
        await message.answer("👥 نقش‌ها را با کاما جدا کنید:")
        await state.set_state(AddScenarioParity.waiting_for_roles)

    async def add_scenario_roles(self, message: types.Message, state: FSMContext):
        roles = [x.strip() for x in (message.text or "").split(",") if x.strip()]
        if not roles:
            await message.answer("⚠️ حداقل یک نقش لازم است.")
            return
        await state.update_data(roles=roles)
        await message.answer("🔢 حداقل تعداد بازیکنان را وارد کنید:")
        await state.set_state(AddScenarioParity.waiting_for_min_players)

    async def add_scenario_min(self, message: types.Message, state: FSMContext):
        if not (message.text or "").isdigit():
            await message.answer("⚠️ یک عدد معتبر وارد کنید.")
            return
        data = await state.get_data()
        minimum = int(message.text)
        roles = list(data["roles"])
        if minimum < 1 or minimum > len(roles):
            await message.answer(f"⚠️ حداقل بازیکن باید بین 1 و {len(roles)} باشد.")
            return
        self.app.scenarios[data["name"]] = {"roles": roles, "min_players": minimum, "max_players": len(roles)}
        self.app._save_scenarios()
        await state.finish()
        await message.answer(f"✅ سناریو <b>{html.escape(data['name'])}</b> ذخیره شد.\n👥 {minimum} تا {len(roles)} بازیکن", parse_mode="HTML")

    async def remove_scenario(self, callback: types.CallbackQuery):
        if not await self._is_admin(callback, self.app.ui.group_chat_id or 0):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for name in self.app.scenarios:
            kb.add(InlineKeyboardButton(f"❌ {name}", callback_data=f"fp:delete_scenario:{name}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="fp:scenarios"))
        await callback.message.edit_text("سناریوی موردنظر را انتخاب کنید:", reply_markup=kb)
        await callback.answer()

    async def delete_scenario(self, callback: types.CallbackQuery):
        if not await self._is_admin(callback, self.app.ui.group_chat_id or 0):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        name = callback.data.split(":", 2)[2]
        if name not in self.app.scenarios:
            await callback.answer("⚠️ سناریو پیدا نشد.", show_alert=True)
            return
        del self.app.scenarios[name]
        self.app._save_scenarios()
        await callback.message.edit_text(f"✅ سناریو «{html.escape(name)}» حذف شد.", reply_markup=self.panel_keyboard(self.app.ui.group_chat_id or 0))
        await callback.answer()

    def register(self):
        dp = self.app.dp
        dp.register_callback_query_handler(self.open_panel, lambda c: c.data == "fp:panel")
        dp.register_callback_query_handler(self.list_players, lambda c: c.data == "fp:list_players")
        dp.register_callback_query_handler(self.resend_roles, lambda c: c.data == "fp:resend_roles")
        dp.register_callback_query_handler(self.remove_player, lambda c: c.data == "fp:remove_player")
        dp.register_callback_query_handler(self.remove_confirm, lambda c: c.data.startswith("fp:remove:"))
        dp.register_callback_query_handler(self.replace_player, lambda c: c.data == "fp:replace_player")
        dp.register_callback_query_handler(self.choose_replace_seat, lambda c: c.data.startswith("fp:replace-sub:"))
        dp.register_callback_query_handler(self.replace_confirm, lambda c: c.data.startswith("fp:replace:"))
        dp.register_callback_query_handler(self.revive_player, lambda c: c.data == "fp:revive_player")
        dp.register_callback_query_handler(self.revive_confirm, lambda c: c.data.startswith("fp:revive:"))
        dp.register_callback_query_handler(self.challenge_request, lambda c: c.data.startswith("fp:challenge:"))
        dp.register_callback_query_handler(self.challenge_response, lambda c: c.data.startswith("fp:accept:") or c.data.startswith("fp:reject:"))
        dp.register_callback_query_handler(self.moderator_menu, lambda c: c.data == "fp:moderator")
        dp.register_callback_query_handler(self.set_moderator, lambda c: c.data.startswith("fp:setmod:"))
        dp.register_callback_query_handler(lambda c: self.toggle_next(c, "allow_players_next"), lambda c: c.data == "fp:toggle_player_next")
        dp.register_callback_query_handler(lambda c: self.toggle_next(c, "allow_moderator_next"), lambda c: c.data == "fp:toggle_mod_next")
        dp.register_callback_query_handler(lambda c: self.toggle_next(c, "anti_spam"), lambda c: c.data == "fp:toggle_next_antispam")
        dp.register_callback_query_handler(self.cancel, lambda c: c.data == "fp:cancel")
        dp.register_callback_query_handler(self.scenario_menu, lambda c: c.data == "fp:scenarios")
        dp.register_callback_query_handler(self.add_scenario_start, lambda c: c.data == "fp:add_scenario")
        dp.register_callback_query_handler(self.remove_scenario, lambda c: c.data == "fp:remove_scenario")
        dp.register_callback_query_handler(self.delete_scenario, lambda c: c.data.startswith("fp:delete_scenario:"))
        dp.register_message_handler(self.add_scenario_name, state=AddScenarioParity.waiting_for_name)
        dp.register_message_handler(self.add_scenario_roles, state=AddScenarioParity.waiting_for_roles)
        dp.register_message_handler(self.add_scenario_min, state=AddScenarioParity.waiting_for_min_players)
        dp.register_message_handler(self.add_substitute_message, lambda m: (m.text or "").strip().lower() in {"جایگزین", "/sub"})
        dp.register_message_handler(self.seat_command, lambda m: (m.text or "").strip() == "صندلی من")
        dp.register_message_handler(self.seats_command, lambda m: (m.text or "").strip() == "لیست صندلی")
        dp.register_message_handler(self.role_command, lambda m: (m.text or "").strip() == "نقش من")
        dp.register_message_handler(self.status_command, lambda m: (m.text or "").strip() == "وضعیت بازی")
        dp.register_message_handler(self.players_command, lambda m: (m.text or "").strip() == "لیست بازیکنان")
        dp.register_message_handler(self.tag_list, lambda m: (m.text or "").strip() == "تگ لیست")
        dp.register_message_handler(self.tag_admins, lambda m: (m.text or "").strip() == "تگ ادمین")
        dp.register_callback_query_handler(self.open_panel, lambda c: c.data == "manage_game")
        dp.register_callback_query_handler(self.scenario_menu, lambda c: c.data == "manage_scenarios")
        dp.register_callback_query_handler(self.resend_roles, lambda c: c.data == "resend_roles")
        dp.register_callback_query_handler(self.remove_player, lambda c: c.data == "remove_player")
        dp.register_callback_query_handler(self.replace_player, lambda c: c.data == "replace_player")
        dp.register_callback_query_handler(self.revive_player, lambda c: c.data == "player_birthday")
        dp.register_callback_query_handler(self.challenge_request, lambda c: c.data.startswith("challenge_request_"))
        dp.register_callback_query_handler(self.challenge_response, lambda c: c.data.startswith("accept_before_") or c.data.startswith("accept_after_") or c.data.startswith("reject_"))
