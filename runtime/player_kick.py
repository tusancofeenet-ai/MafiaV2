"""Kick/warning controls for moderators."""
from __future__ import annotations

import html
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from runtime.game_management import GameManagement
from runtime.player_scoring import warning_penalty


class PlayerDiscipline:
    def __init__(self, app: Any):
        self.app = app

    def _game(self, gid: int):
        return self.app.runtime.state.active_game(int(gid))

    async def _allowed(self, obj, gid: int, game=None) -> bool:
        game = game or self._game(gid)
        if not game:
            return False
        uid = int(obj.from_user.id)
        if uid == int(game.get("moderator_id") or 0):
            return True
        try:
            return (await self.app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    def _rows(self, game):
        return self.app.runtime.state.games.list_players(game["id"])

    @staticmethod
    def _name(row):
        return str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")

    def patch_panel(self):
        original = GameManagement.panel
        if getattr(GameManagement, "_discipline_panel_patched", False):
            return

        def panel(instance, game_id):
            kb = original(instance, game_id)
            kb.row(
                InlineKeyboardButton("⚠️ تذکر بازیکن", callback_data=f"mgmt:{int(game_id)}:warning"),
                InlineKeyboardButton("🚫 کیک از بازی", callback_data=f"mgmt:{int(game_id)}:kick"),
            )
            return kb

        GameManagement.panel = panel
        GameManagement._discipline_panel_patched = True

    async def pick(self, callback, action: str, title: str):
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        rows = [
            r for r in self._rows(game)
            if r.get("seat") is not None and str(r.get("status") or "") not in {"removed", "kicked"}
        ]
        kb = InlineKeyboardMarkup(row_width=2)
        for row in rows:
            uid = int(row["player_id"])
            seat = int(row.get("seat") or 0)
            count = int((dict(game.get("state") or {}).get("warnings") or {}).get(str(uid), 0))
            suffix = f" ⚠️{count}" if count else ""
            kb.insert(InlineKeyboardButton(f"{seat}. {self._name(row)}{suffix}", callback_data=f"disc:{action}:{int(game['id'])}:{uid}"))
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data=f"mgmt:{int(game['id'])}:open"))
        await callback.message.edit_text(title, parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def kick(self, callback):
        await self.pick(callback, "kick_pick", "🚫 <b>کیک از بازی</b>\n\nبازیکنی را که باید از بازی خارج شود انتخاب کنید:")

    async def kick_pick(self, callback):
        p = str(callback.data or "").split(":")
        if len(p) != 4 or p[0] != "disc" or p[1] != "kick_pick":
            return
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        uid = int(p[3])
        if not game or int(game["id"]) != int(p[2]) or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        row = next((r for r in self._rows(game) if int(r["player_id"]) == uid), None)
        if not row or str(row.get("status") or "") in {"removed", "kicked"}:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True)
            return
        state = dict(game.get("state") or {})
        kicked = dict(state.get("kicked_players") or {})
        kicked[str(uid)] = True
        state["kicked_players"] = kicked
        self.app.runtime.state.games.update_game(game["id"], state=state)
        self.app.runtime.state.games.set_player_status(game["id"], uid, "removed")
        alive = getattr(self.app.runtime.state.games, "set_player_alive", None)
        if alive:
            try:
                alive(game["id"], uid, False)
            except Exception:
                pass
        await callback.message.edit_text(
            f"🚫 <b>{html.escape(self._name(row))}</b> از بازی کیک شد.\n\n"
            f"💥 جریمه کیک: <b>-20</b> امتیاز\n"
            "🎂 تولد این بازیکن دیگر امکان‌پذیر نیست.",
            parse_mode="HTML",
            reply_markup=GameManagement.panel(self, game["id"]),
        )
        await callback.answer("🚫 بازیکن کیک شد.")

    async def warning(self, callback):
        await self.pick(callback, "warning_pick", "⚠️ <b>ثبت تذکر</b>\n\nبازیکن را انتخاب کنید:")

    async def warning_pick(self, callback):
        p = str(callback.data or "").split(":")
        if len(p) != 4 or p[0] != "disc" or p[1] != "warning_pick":
            return
        gid = int(callback.message.chat.id)
        game = self._game(gid)
        uid = int(p[3])
        if not game or int(game["id"]) != int(p[2]) or not await self._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        rows = self._rows(game)
        row = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not row:
            await callback.answer("❌ بازیکن پیدا نشد.", show_alert=True)
            return
        state = dict(game.get("state") or {})
        warnings = dict(state.get("warnings") or {})
        current = int(warnings.get(str(uid), 0) or 0)
        next_no = current + 1
        warnings[str(uid)] = next_no
        state["warnings"] = warnings
        self.app.runtime.state.games.update_game(game["id"], state=state)
        penalty = warning_penalty(next_no) - warning_penalty(current)
        await callback.message.edit_text(
            f"⚠️ <b>تذکر شماره {next_no}</b>\n\n"
            f"👤 {html.escape(self._name(row))}\n"
            f"📉 کسر این تذکر: <b>-{penalty}</b> امتیاز\n"
            f"📊 مجموع کسر تذکرها: <b>-{warning_penalty(next_no)}</b> امتیاز",
            parse_mode="HTML",
            reply_markup=GameManagement.panel(self, game["id"]),
        )
        await callback.answer(f"⚠️ تذکر {next_no} ثبت شد.")

    async def _text_discipline(self, message, decrease: bool = False):
        if message.chat.type not in {"group", "supergroup"}:
            return
        gid = int(message.chat.id)
        game = self._game(gid)
        if not game:
            await message.reply("⚠️ بازی فعالی وجود ندارد.")
            return
        if not await self._allowed(message, gid, game):
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند نظم بازی را مدیریت کند.")
            return
        reply = getattr(message, "reply_to_message", None)
        target_user = getattr(reply, "from_user", None)
        if not target_user:
            command = "تذکر منفی" if decrease else "تذکر"
            await message.reply(f"❗ برای {command} روی پیام بازیکن ریپلای کنید و همین دستور را ارسال کنید.")
            return
        uid = int(target_user.id)
        row = next((r for r in self._rows(game) if int(r["player_id"]) == uid), None)
        if not row or str(row.get("status") or "") in {"removed", "kicked"}:
            await message.reply("❌ این کاربر بازیکن فعال این بازی نیست.")
            return
        state = dict(game.get("state") or {})
        warnings = dict(state.get("warnings") or {})
        current = max(0, int(warnings.get(str(uid), 0) or 0))
        if decrease:
            if current <= 0:
                await message.reply(f"ℹ️ برای <b>{html.escape(self._name(row))}</b> تذکری ثبت نشده است.", parse_mode="HTML")
                return
            new_count = current - 1
            warnings[str(uid)] = new_count
            state["warnings"] = warnings
            self.app.runtime.state.games.update_game(game["id"], state=state)
            restored = warning_penalty(current) - warning_penalty(new_count)
            await message.reply(
                f"↩️ یک تذکر از <b>{html.escape(self._name(row))}</b> کم شد.\n"
                f"📊 تعداد تذکر: <b>{new_count}</b>\n"
                f"📈 امتیاز برگشتی: <b>+{restored}</b>",
                parse_mode="HTML",
            )
            return
        new_count = current + 1
        warnings[str(uid)] = new_count
        state["warnings"] = warnings
        self.app.runtime.state.games.update_game(game["id"], state=state)
        penalty = warning_penalty(new_count) - warning_penalty(current)
        await message.reply(
            f"⚠️ برای <b>{html.escape(self._name(row))}</b> تذکر شماره <b>{new_count}</b> ثبت شد.\n"
            f"📉 کسر این تذکر: <b>-{penalty}</b>\n"
            f"📊 مجموع کسر تذکرها: <b>-{warning_penalty(new_count)}</b>",
            parse_mode="HTML",
        )

    async def text_command(self, message):
        raw = (message.text or "").strip().casefold().replace("‌", " ")
        raw = " ".join(raw.split())
        if raw in {"کیک", "کیک از بازی", "/kick"}:
            await self._text_kick(message)
        elif raw in {"تذکر", "/تذکر", "/warning"}:
            await self._text_discipline(message, decrease=False)
        elif raw in {"تذکر منفی", "/تذکر_منفی", "کاهش تذکر", "/کاهش_تذکر"}:
            await self._text_discipline(message, decrease=True)

    async def _text_kick(self, message):
        if message.chat.type not in {"group", "supergroup"}:
            return
        gid = int(message.chat.id)
        game = self._game(gid)
        if not game or not await self._allowed(message, gid, game):
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازیکن را کیک کند.")
            return
        reply = getattr(message, "reply_to_message", None)
        target_user = getattr(reply, "from_user", None)
        if not target_user:
            await message.reply("❗ برای کیک، روی پیام بازیکن ریپلای کنید و بنویسید «کیک».")
            return
        uid = int(target_user.id)
        row = next((r for r in self._rows(game) if int(r["player_id"]) == uid), None)
        if not row or str(row.get("status") or "") in {"removed", "kicked"}:
            await message.reply("❌ این کاربر بازیکن فعال این بازی نیست.")
            return
        state = dict(game.get("state") or {})
        kicked = dict(state.get("kicked_players") or {})
        kicked[str(uid)] = True
        state["kicked_players"] = kicked
        self.app.runtime.state.games.update_game(game["id"], state=state)
        self.app.runtime.state.games.set_player_status(game["id"], uid, "removed")
        alive = getattr(self.app.runtime.state.games, "set_player_alive", None)
        if alive:
            try:
                alive(game["id"], uid, False)
            except Exception:
                pass
        await message.reply(
            f"🚫 <b>{html.escape(self._name(row))}</b> از بازی کیک شد.\n"
            "💥 جریمه: <b>-20</b> امتیاز\n🎂 تولد این بازیکن امکان‌پذیر نیست.",
            parse_mode="HTML",
        )

    def install(self) -> bool:
        self.patch_panel()
        dp = self.app.dp
        dp.register_callback_query_handler(self.kick, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2] == "kick", state="*")
        dp.register_callback_query_handler(self.warning, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2] == "warning", state="*")
        dp.register_callback_query_handler(self.kick_pick, lambda c: str(c.data or "").startswith("disc:kick_pick:"), state="*")
        dp.register_callback_query_handler(self.warning_pick, lambda c: str(c.data or "").startswith("disc:warning_pick:"), state="*")
        dp.register_message_handler(
            self.text_command,
            lambda m: (m.text or "").strip().casefold().replace("‌", " ") in {
                "کیک", "کیک از بازی", "/kick", "تذکر", "/تذکر", "/warning",
                "تذکر منفی", "/تذکر_منفی", "کاهش تذکر", "/کاهش_تذکر",
            },
            state="*",
        )
        return True


def install(app: Any) -> bool:
    return PlayerDiscipline(app).install()
