"""Friendly text commands for players, members and the game moderator."""
from __future__ import annotations

import html
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


COMMAND_ALIASES = {
    "help": {"راهنما", "کمک", "/help"},
    "new_game": {"بازی جدید", "/newgame"},
    "management": {"مدیریت", "مدیریت بازی"},
    "score": {"امتیاز", "امتیاز من"},
    "turn": {"نوبت", "نوبت من"},
    "players": {"بازیکنان"},
    "seats": {"صندلی ها", "صندلی‌ها"},
    "challenge": {"چالش"},
}


def _norm(value: str | None) -> str:
    value = (value or "").strip().casefold().replace("‌", " ")
    return " ".join(value.split())


def _resolve(value: str | None) -> str | None:
    value = _norm(value)
    for command, aliases in COMMAND_ALIASES.items():
        if value in {_norm(x) for x in aliases}:
            return command
    return None


class TextCommands:
    def __init__(self, app: Any):
        self.app = app
        self.scenarios = ScenarioRepository()

    def _game(self, gid: int):
        return self.app.runtime.state.active_game(int(gid))

    async def _is_manager(self, message: types.Message, game: dict[str, Any] | None = None) -> bool:
        uid = int(message.from_user.id)
        if game and uid == int(game.get("moderator_id") or 0):
            return True
        try:
            return (await self.app.bot.get_chat_member(message.chat.id, uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    async def _new_game(self, message: types.Message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("ℹ️ ایجاد بازی جدید فقط داخل گروه قابل استفاده است.")
            return
        if self._game(message.chat.id):
            await message.reply("⚠️ یک بازی فعال وجود دارد. ابتدا آن را تمام یا لغو کنید.")
            return
        if not await self._is_manager(message):
            await message.reply("⛔ فقط مدیر گروه می‌تواند بازی جدید ایجاد کند.")
            return
        try:
            game = self.app.runtime.lobby.start_new(message.chat.id)
            kb = InlineKeyboardMarkup(row_width=1)
            for row in self.scenarios.list_active():
                sid = int(row["id"])
                kb.add(InlineKeyboardButton(
                    f"📝 {row.get('name') or sid} ({len(row.get('roles') or [])})",
                    callback_data=f"lobby:{int(game['id'])}:scenario:{sid}",
                ))
            sent = await message.reply(
                "📝 <b>انتخاب سناریو</b>\n\nسناریوی بازی را انتخاب کنید:",
                parse_mode="HTML",
                reply_markup=kb,
            )
            state = dict(game.get("state") or {})
            state["selection_message_id"] = int(sent.message_id)
            state["lobby_message_id"] = int(sent.message_id)
            self.app.runtime.state.games.update_game(game["id"], state=state)
            self.app.ui.group_chat_id = message.chat.id
        except RuntimeError as exc:
            await message.reply(str(exc))
        except Exception:
            await message.reply("❌ ایجاد بازی انجام نشد.")

    async def _management(self, message: types.Message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("ℹ️ مدیریت بازی فقط داخل گروه قابل استفاده است.")
            return
        game = self._game(message.chat.id)
        if not game:
            await message.reply("❌ بازی فعالی وجود ندارد.")
            return
        if not await self._is_manager(message, game):
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند مدیریت بازی را باز کند.")
            return
        from runtime.game_management import GameManagement
        status = str(game.get("status") or "lobby")
        await message.reply(
            "⚙️ <b>مدیریت بازی</b>\n\n"
            f"🔢 شماره بازی: <b>{int(game.get('event_number') or 1)}</b>\n"
            f"📌 وضعیت: <b>{html.escape(status)}</b>\n\n"
            "پنل مدیریت از دکمه‌های زیر در دسترس است.",
            parse_mode="HTML",
            reply_markup=GameManagement.panel(self, int(game["id"])),
        )

    async def _turn(self, message: types.Message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("ℹ️ وضعیت نوبت در گروه بازی نمایش داده می‌شود.")
            return
        turn = self.app.runtime.current_turn(message.chat.id)
        if not turn:
            await message.reply("ℹ️ در حال حاضر نوبت فعالی وجود ندارد.")
            return
        seat = int(turn.get("seat") or 0)
        rows = self.app._players_by_seat(message.chat.id)
        row = rows.get(seat)
        uid = int(row["player_id"]) if row else 0
        name = self.app._name(uid) if uid else str(seat)
        marker = "🟢 نوبت شماست." if uid == int(message.from_user.id) else ""
        await message.reply(
            f"🎯 <b>نوبت فعلی</b>\n\n💺 صندلی: <b>{seat}</b>\n"
            f"👤 بازیکن: <b>{html.escape(name)}</b>\n{marker}",
            parse_mode="HTML",
        )

    async def _players(self, message: types.Message):
        fp = getattr(self.app, "feature_parity", None)
        if fp and hasattr(fp, "players_command"):
            await fp.players_command(message)
            return
        rows = self.app._players_by_seat(message.chat.id)
        if not rows:
            await message.reply("🚫 هیچ بازیکنی ثبت نشده است.")
            return
        await message.reply("📜 <b>لیست بازیکنان</b>\n\n" + "\n".join(
            f"{seat:02d}. {html.escape(self.app._name(int(row['player_id'])))}"
            for seat, row in sorted(rows.items())
        ), parse_mode="HTML")

    async def _seats(self, message: types.Message):
        fp = getattr(self.app, "feature_parity", None)
        if fp and hasattr(fp, "seats_command"):
            await fp.seats_command(message)
            return
        rows = self.app._players_by_seat(message.chat.id)
        if not rows:
            await message.reply("🚫 هیچ صندلی فعالی وجود ندارد.")
            return
        await message.reply("📋 <b>لیست صندلی‌ها</b>\n\n" + "\n".join(
            f"{seat:02d}. {html.escape(self.app._name(int(row['player_id'])))}"
            for seat, row in sorted(rows.items())
        ), parse_mode="HTML")

    async def _score(self, message: types.Message):
        stats = getattr(self.app, "_user_stats_instance", None)
        if stats is None:
            await message.reply("⚠️ بخش آمار هنوز آماده نیست.")
            return
        target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
        gid = message.chat.id if message.chat.type in {"group", "supergroup"} else None
        await stats.show_stats(message, int(target.id), gid)

    async def _challenge(self, message: types.Message):
        if message.chat.type not in {"group", "supergroup"}:
            await message.reply("ℹ️ چالش فقط داخل گروه بازی قابل استفاده است.")
            return
        gid = int(message.chat.id)
        game = self._game(gid)
        if not game:
            await message.reply("❌ بازی فعالی وجود ندارد.")
            return
        if not getattr(self.app, "challenge_enabled", {}).get(gid, True):
            await message.reply("⚔️ چالش در این بازی خاموش است.")
            return
        reply = getattr(message, "reply_to_message", None)
        target = getattr(reply, "from_user", None)
        if not target:
            await message.reply("❗ برای چالش، روی پیام بازیکن موردنظر ریپلای کنید و بنویسید «چالش».")
            return
        challenger = int(message.from_user.id)
        target_id = int(target.id)
        if challenger == target_id:
            await message.reply("❌ نمی‌توانید خودتان را چالش کنید.")
            return
        rows = self.app._players_by_seat(gid)
        target_seat = next((s for s, r in rows.items() if int(r["player_id"]) == target_id), None)
        challenger_seat = next((s for s, r in rows.items() if int(r["player_id"]) == challenger), None)
        if target_seat is None or challenger_seat is None:
            await message.reply("❌ هر دو نفر باید بازیکن فعال بازی باشند.")
            return
        state = dict(game.get("state") or {})
        pending = dict(state.get("challenge_requests") or {})
        bucket = dict(pending.get(str(target_seat)) or {})
        if str(challenger) in bucket:
            await message.reply("⚠️ درخواست چالش شما قبلاً ثبت شده است.")
            return
        bucket[str(challenger)] = "pending"
        pending[str(target_seat)] = bucket
        state["challenge_requests"] = pending
        self.app.runtime.state.games.update_game(game["id"], state=state)
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("✅ قبول قبل", callback_data=f"fp:accept:before:{challenger}:{target_id}"),
            InlineKeyboardButton("✅ قبول بعد", callback_data=f"fp:accept:after:{challenger}:{target_id}"),
            InlineKeyboardButton("❌ رد", callback_data=f"fp:reject:{challenger}:{target_id}"),
        )
        await self.app.bot.send_message(
            gid,
            f"⚔ <b>{html.escape(self.app._name(challenger))}</b> برای <b>{html.escape(self.app._name(target_id))}</b> درخواست چالش داد.",
            parse_mode="HTML",
            reply_markup=kb,
        )

    async def _help(self, message: types.Message):
        text = (
            "📚 <b>دستورات Mafia Nights</b>\n\n"
            "👤 <b>بازیکنان</b>\n"
            "• پروفایل — پروفایل و رتبه\n"
            "• آمار / امتیاز — آمار و جزئیات امتیاز\n"
            "• رتبه — رتبه‌بندی\n"
            "• صندلی من — شماره صندلی شما\n"
            "• صندلی‌ها — نمایش صندلی‌ها\n"
            "• نقش من — نمایش نقش در پیوی\n"
            "• وضعیت بازی — وضعیت کلی بازی\n"
            "• نوبت من — نوبت فعلی\n"
            "• جایگزین — ورود به لیست جایگزین\n"
            "• چالش — درخواست چالش با ریپلای\n\n"
            "📢 <b>گروه</b>\n"
            "• تگ لیست — تگ بازیکنان\n"
            "• تگ ادمین — تگ مدیران\n\n"
            "🎩 <b>مدیریت و نظم</b>\n"
            "• بازی جدید — ایجاد بازی و انتخاب سناریو\n"
            "• مدیریت بازی — پنل مدیریت\n"
            "• تذکر — ثبت تذکر روی بازیکن با ریپلای\n"
            "• تذکر منفی — کم‌کردن یک تذکر با ریپلای\n"
            "• کیک — خروج اجباری بازیکن با ریپلای\n"
            "• لغو بازی — لغو بازی جاری\n\n"
            "💡 دستورات مدیریتی فقط برای گرداننده یا مدیر گروه فعال هستند."
        )
        await message.reply(text, parse_mode="HTML")

    async def command(self, message: types.Message):
        command = _resolve(message.text)
        if not command:
            return
        if command == "help":
            await self._help(message)
        elif command == "new_game":
            await self._new_game(message)
        elif command == "management":
            await self._management(message)
        elif command == "score":
            await self._score(message)
        elif command == "turn":
            await self._turn(message)
        elif command == "players":
            await self._players(message)
        elif command == "seats":
            await self._seats(message)
        elif command == "challenge":
            await self._challenge(message)

    def install(self) -> bool:
        if getattr(self.app, "_text_commands_installed", False):
            return False
        self.app.dp.register_message_handler(
            self.command,
            lambda m: _resolve(getattr(m, "text", None)) is not None,
            content_types=types.ContentTypes.TEXT,
            state="*",
        )
        self.app._text_commands_installed = True
        return True


def install(app: Any) -> bool:
    return TextCommands(app).install()
