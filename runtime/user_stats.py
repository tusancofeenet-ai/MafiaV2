"""Private profile, public ranking and player statistics."""
from __future__ import annotations

import html
import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.rating_repository import RatingRepository


COMMANDS = {
    "profile": {"پروفایل", "profile"},
    "ranking": {"رتبه", "رتبه بندی", "رتبه‌بندی", "ranking", "rank"},
    "stats": {"آمار", "stats", "statistics"},
}


def normalize(value: str | None) -> str:
    value = (value or "").strip().replace("‌", " ")
    value = " ".join(value.split()).casefold()
    return value[1:] if value.startswith("/") else value


def resolve(value: str | None):
    value = normalize(value)
    for name, aliases in COMMANDS.items():
        if value in {normalize(x) for x in aliases}:
            return name
    return None


def name(row: dict[str, Any] | None, fallback="بازیکن") -> str:
    if not row:
        return fallback
    return str(row.get("nickname") or row.get("display_name") or row.get("first_name") or row.get("username") or row.get("user_id") or fallback)


def mention(uid: int, display: str) -> str:
    return f"<a href='tg://user?id={int(uid)}'>{html.escape(display)}</a>"


def _profile_text(row, rank):
    display = name(row, str(row.get("user_id"))) if row else "بازیکن"
    return (
        "👤 <b>پروفایل بازیکن</b>\n\n"
        f"🧑 نام: {html.escape(display)}\n"
        f"🎮 تعداد بازی: {int(row.get('games',0)) if row else 0}\n"
        f"🏆 برد: {int(row.get('wins',0)) if row else 0}\n"
        f"❌ باخت: {int(row.get('losses',0)) if row else 0}\n"
        f"🤝 مساوی: {int(row.get('draws',0)) if row else 0}\n"
        f"⭐ امتیاز: {int(row.get('score',50)) if row else 50}\n"
        f"🏅 رتبه: {rank.get('rank') or '—'} از {rank.get('total_players',0)}"
    )


def _profile_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(InlineKeyboardButton("🏆 رتبه‌بندی", callback_data="ustats:ranking"), InlineKeyboardButton("📊 آمار", callback_data="ustats:stats"))
    kb.row(InlineKeyboardButton("🔄 بروزرسانی", callback_data="ustats:profile"))
    return kb


def _ranking_text(rows, title="🏆 <b>رتبه‌بندی بازیکنان</b>"):
    if not rows:
        return title + "\n\nهنوز آماری برای رتبه‌بندی ثبت نشده است."
    medals = ["🥇", "🥈", "🥉"]
    lines = [title, ""]
    for i, row in enumerate(rows, 1):
        prefix = medals[i - 1] if i <= 3 else f"{i}."
        lines.append(f"{prefix} {mention(row['user_id'], name(row))} — ⭐ {row['score']} | 🏆 {row['wins']} | 🎮 {row['games']}")
    return "\n".join(lines)


def _signed(value: int) -> str:
    value = int(value)
    return f"+{value}" if value > 0 else str(value)


def _score_breakdown(details: dict[str, Any]) -> str:
    win = int(details.get("win_bonus") or 0)
    challenge = int(details.get("challenge_bonus") or 0)
    warning = int(details.get("warning_penalty") or 0)
    kick = int(details.get("kick_penalty") or 0)
    challenges = int(details.get("challenges") or 0)
    warnings = int(details.get("warnings") or 0)
    kicks = int(details.get("kicks") or 0)
    net = win + challenge - warning - kick
    return (
        "⭐ <b>جزئیات امتیاز</b>\n"
        f"├ 🏆 امتیاز برد ساید: <b>+{win}</b>\n"
        f"├ ⚔️ امتیاز چالش: <b>+{challenge}</b> ({challenges} چالش)\n"
        f"├ ⚠️ کسر تذکر: <b>-{warning}</b> ({warnings} تذکر)\n"
        f"├ 🚫 کسر کیک: <b>-{kick}</b> ({kicks} بار)\n"
        f"└ 📈 تغییر خالص: <b>{_signed(net)}</b>\n\n"
        f"🎯 امتیاز پایه: <b>50</b>\n"
        f"💰 امتیاز فعلی: <b>{int(details.get('score') or 50)}</b>"
    )


class UserStats:
    def __init__(self, app: Any):
        self.app = app
        self.ratings = RatingRepository()

    async def show_profile(self, message: types.Message, uid: int | None = None, edit=False):
        uid = int(uid or message.from_user.id)
        row = self.ratings.player_profile(uid)
        rank = self.ratings.rank(uid)
        if not row and uid != int(message.from_user.id):
            text = "❌ پروفایل این بازیکن هنوز ثبت نشده است."
        else:
            text = _profile_text(row or {"user_id": uid}, rank)
        if edit:
            await message.edit_text(text, parse_mode="HTML", reply_markup=_profile_kb())
        else:
            await message.reply(text, parse_mode="HTML", reply_markup=_profile_kb())

    async def show_ranking(self, message: types.Message, group_id: int | None = None, edit=False):
        if group_id:
            rows = self.ratings.group_top(group_id, 10)
            title = "🏆 <b>رتبه‌بندی این گروه</b>"
        else:
            rows = self.ratings.top(10)
            title = "🏆 <b>رتبه‌بندی بازیکنان</b>"
        text = _ranking_text(rows, title)
        if edit:
            await message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("✖️ بستن", callback_data="ustats:close")))
        else:
            await message.reply(text, parse_mode="HTML")

    async def show_stats(self, message: types.Message, uid: int | None = None, group_id: int | None = None, edit=False):
        uid = int(uid or message.from_user.id)
        row = self.ratings.player_profile(uid)
        if group_id:
            stats = self.ratings.group_summary(uid, group_id)
            scope = "این گروه"
            details = {
                "score": int(stats.get("games", 0) and stats.get("score", 50) or 50),
                "win_bonus": stats.get("win_bonus", 0),
                "challenge_bonus": stats.get("challenge_bonus", 0),
                "warning_penalty": stats.get("warning_penalty", 0),
                "kick_penalty": stats.get("kick_penalty", 0),
                "challenges": int(stats.get("challenge_bonus", 0) or 0) // 3,
                "warnings": int(stats.get("warning_penalty", 0) or 0),
                "kicks": 1 if int(stats.get("kick_penalty", 0) or 0) > 0 else 0,
            }
        else:
            stats = self.ratings.player_summary(uid)
            scope = "کلی"
            details = self.ratings.rating_details(uid)
        if not row and int(stats.get("games", 0)) == 0:
            text = "❌ هنوز آماری برای این بازیکن ثبت نشده است.\n\n⭐ امتیاز پایه: <b>50</b>"
        else:
            display = name(row, str(uid))
            games = int(stats.get("games", 0)); wins = int(stats.get("wins", 0)); losses = int(stats.get("losses", 0)); draws = int(stats.get("draws", 0)); score = int(stats.get("score", 50))
            win_rate = (wins * 100 / games) if games else 0
            text = (
                f"📊 <b>آمار {html.escape(display)}</b>\n\n"
                f"📌 محدوده: {scope}\n"
                f"🎮 بازی‌ها: {games}\n"
                f"🏆 برد: {wins}\n❌ باخت: {losses}\n🤝 مساوی: {draws}\n"
                f"⭐ امتیاز: {score}\n📈 درصد برد: {win_rate:.1f}%\n\n"
                f"{_score_breakdown(details)}"
            )
        if edit:
            await message.edit_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("✖️ بستن", callback_data="ustats:close")))
        else:
            await message.reply(text, parse_mode="HTML")

    async def command(self, message: types.Message):
        command = resolve(message.text)
        if not command:
            return
        if command == "profile":
            await self.show_profile(message)
        elif command == "ranking":
            await self.show_ranking(message, message.chat.id if message.chat.type in {"group", "supergroup"} else None)
        elif command == "stats":
            target = message.reply_to_message.from_user if message.reply_to_message else message.from_user
            gid = message.chat.id if message.chat.type in {"group", "supergroup"} else None
            await self.show_stats(message, target.id, gid)
        raise CancelHandler()

    async def callback(self, callback: types.CallbackQuery):
        action = str(callback.data or "").split(":", 1)[-1]
        if action == "close":
            await callback.message.delete()
        elif action == "profile":
            await self.show_profile(callback.message, callback.from_user.id, edit=True)
        elif action == "ranking":
            await self.show_ranking(callback.message, edit=True)
        elif action == "stats":
            await self.show_stats(callback.message, callback.from_user.id, edit=True)
        await callback.answer()

    def install(self):
        if getattr(self.app, "_user_stats_installed", False):
            return False
        self.app._user_stats_instance = self

        @self.app.dp.message_handler(lambda m: bool(resolve(getattr(m, "text", None))), state="*")
        async def text_handler(message: types.Message):
            await self.command(message)

        @self.app.dp.callback_query_handler(lambda c: str(c.data or "").startswith("ustats:"), state="*")
        async def callback_handler(callback: types.CallbackQuery):
            try:
                await self.callback(callback)
            except Exception:
                logging.exception("user stats callback failed")
                await callback.answer("❌ خطا در نمایش اطلاعات.", show_alert=True)

        self.app._user_stats_installed = True
        return True


def install(app):
    return UserStats(app).install()
