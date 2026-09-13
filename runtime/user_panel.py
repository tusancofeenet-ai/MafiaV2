"""Unified private user dashboard for MafiaNights.

This module is intentionally isolated from the legacy game handlers. It exposes
profile, game statistics, history, participation leaderboard, nickname settings
and help without changing the game state machine.
"""
from __future__ import annotations

import html
import os
from datetime import datetime

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


class UserPanelStates(StatesGroup):
    waiting_for_nickname = State()


class UserPanel:
    def __init__(self, app):
        self.app = app
        self._engine = None
        self._sessions = None

    def _db(self):
        if self._sessions is not None:
            return self._sessions
        url = os.getenv("DATABASE_URL")
        if not url:
            return None
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
        try:
            self._engine = create_engine(url, pool_pre_ping=True)
            self._sessions = sessionmaker(autocommit=False, autoflush=False, bind=self._engine)
        except Exception:
            self._sessions = None
        return self._sessions

    def _query_one(self, query, params):
        sessions = self._db()
        if not sessions:
            return None
        try:
            with sessions() as session:
                row = session.execute(text(query), params).mappings().first()
                return dict(row) if row else None
        except Exception:
            return None

    def _query_all(self, query, params=None):
        sessions = self._db()
        if not sessions:
            return []
        try:
            with sessions() as session:
                rows = session.execute(text(query), params or {}).mappings().all()
                return [dict(r) for r in rows]
        except Exception:
            return []

    def _execute(self, query, params):
        sessions = self._db()
        if not sessions:
            return False
        try:
            with sessions() as session:
                session.execute(text(query), params)
                session.commit()
            return True
        except Exception:
            return False

    @staticmethod
    def _name(row, fallback="❓"):
        if not row:
            return fallback
        nickname = (row.get("nickname") or "").strip()
        if nickname:
            return nickname
        real = " ".join(p for p in ((row.get("first_name") or "").strip(), (row.get("last_name") or "").strip()) if p)
        return real or ((row.get("username") or "").strip() or fallback)

    @staticmethod
    def _fmt_date(value):
        if not value:
            return "—"
        if isinstance(value, datetime):
            return value.strftime("%Y/%m/%d %H:%M")
        return str(value)[:16].replace("-", "/")

    def _menu(self):
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(
            InlineKeyboardButton("👤 پروفایل من", callback_data="up:profile"),
            InlineKeyboardButton("📊 آمار بازی", callback_data="up:stats"),
            InlineKeyboardButton("🏆 رتبه‌بندی", callback_data="up:leaderboard"),
            InlineKeyboardButton("📜 تاریخچه بازی‌ها", callback_data="up:history"),
            InlineKeyboardButton("⚙️ تنظیمات", callback_data="up:settings"),
            InlineKeyboardButton("❓ راهنما", callback_data="up:help"),
        )
        return kb

    async def open_panel(self, message: types.Message):
        if message.chat.type != "private":
            await message.reply("⚠️ پنل کاربری فقط در پیوی قابل استفاده است.")
            return
        await message.answer("🎭 <b>پنل کاربری Mafia Nights</b>\n\nیکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=self._menu(), parse_mode="HTML")

    async def profile(self, callback: types.CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer("فقط در پیوی.", show_alert=True)
            return
        uid = callback.from_user.id
        row = self._query_one("select id, username, first_name, last_name, nickname from public.mafia_players where id=:id", {"id": uid})
        if not row:
            row = {"id": uid, "username": callback.from_user.username, "first_name": callback.from_user.first_name, "last_name": callback.from_user.last_name, "nickname": None}
        games = self._query_one("select count(*) as n from public.mafia_game_players where player_id=:id", {"id": uid}) or {"n": 0}
        text_body = (
            "👤 <b>پروفایل من</b>\n\n"
            f"نام نمایشی: <b>{html.escape(self._name(row))}</b>\n"
            f"نام کاربری: @{html.escape(row.get('username')) if row.get('username') else '—'}\n"
            f"شناسه: <code>{uid}</code>\n"
            f"تعداد بازی: <b>{int(games.get('n') or 0)}</b>\n"
        )
        await callback.message.edit_text(text_body, reply_markup=self._back_menu(), parse_mode="HTML")
        await callback.answer()

    async def stats(self, callback: types.CallbackQuery):
        uid = callback.from_user.id
        total = self._query_one("select count(*) as n from public.mafia_game_players where player_id=:id", {"id": uid}) or {"n": 0}
        active = self._query_one(
            """select count(*) as n from public.mafia_game_players gp join public.mafia_games g on g.id=gp.game_id
               where gp.player_id=:id and g.status in ('lobby','running','paused')""", {"id": uid}) or {"n": 0}
        seated = self._query_one("select count(*) as n from public.mafia_game_players where player_id=:id and seat is not null", {"id": uid}) or {"n": 0}
        finished = max(0, int(total.get("n") or 0) - int(active.get("n") or 0))
        body = (
            "📊 <b>آمار بازی من</b>\n\n"
            f"🎮 مجموع حضور: <b>{int(total.get('n') or 0)}</b>\n"
            f"🟢 بازی‌های فعال: <b>{int(active.get('n') or 0)}</b>\n"
            f"🪑 دفعات دارای صندلی: <b>{int(seated.get('n') or 0)}</b>\n"
            f"🏁 حضورهای پایان‌یافته: <b>{finished}</b>\n\n"
            "ℹ️ برد/باخت و امتیاز رسمی بعد از اتصال نتیجه نهایی هر بازی به پروفایل اضافه می‌شود؛ فعلاً عدد ساختگی نمایش داده نمی‌شود."
        )
        await callback.message.edit_text(body, reply_markup=self._back_menu(), parse_mode="HTML")
        await callback.answer()

    async def leaderboard(self, callback: types.CallbackQuery):
        rows = self._query_all(
            """select gp.player_id, count(*) as games, p.nickname, p.first_name, p.last_name, p.username
               from public.mafia_game_players gp join public.mafia_players p on p.id=gp.player_id
               group by gp.player_id, p.nickname, p.first_name, p.last_name, p.username
               order by games desc, gp.player_id asc limit 10"""
        )
        lines = ["🏆 <b>رتبه‌بندی بر اساس تعداد بازی</b>", ""]
        medals = ["🥇", "🥈", "🥉"]
        if not rows:
            lines.append("هنوز داده‌ای برای رتبه‌بندی وجود ندارد.")
        else:
            for i, row in enumerate(rows, 1):
                prefix = medals[i - 1] if i <= 3 else f"{i}."
                lines.append(f"{prefix} {html.escape(self._name(row))} — <b>{int(row['games'])}</b> بازی")
        lines.append("\nℹ️ این رتبه‌بندی فعلاً بر پایه حضور در بازی است؛ رتبه‌بندی مهارتی بعد از ثبت نتایج برد/باخت فعال می‌شود.")
        await callback.message.edit_text("\n".join(lines), reply_markup=self._back_menu(), parse_mode="HTML")
        await callback.answer()

    async def history(self, callback: types.CallbackQuery):
        uid = callback.from_user.id
        rows = self._query_all(
            """select gp.game_id, gp.seat, gp.role, gp.status as player_status, g.event_number, g.status as game_status,
                      g.created_at, g.started_at, g.finished_at, g.scenario_id
               from public.mafia_game_players gp join public.mafia_games g on g.id=gp.game_id
               where gp.player_id=:id order by g.created_at desc limit 10""", {"id": uid})
        lines = ["📜 <b>تاریخچه بازی‌های من</b>", ""]
        if not rows:
            lines.append("هنوز سابقه‌ای ثبت نشده است.")
        else:
            for row in rows:
                event = row.get("event_number") or row.get("game_id")
                scenario = row.get("scenario_id") or "—"
                lines.append(
                    f"🎮 <b>#{html.escape(str(event))}</b> | {html.escape(str(scenario))}\n"
                    f"   🪑 صندلی: {row.get('seat') or '—'} | نقش: {html.escape(str(row.get('role') or '—'))}\n"
                    f"   وضعیت: {html.escape(str(row.get('game_status') or '—'))} | {self._fmt_date(row.get('created_at'))}"
                )
        await callback.message.edit_text("\n".join(lines), reply_markup=self._back_menu(), parse_mode="HTML")
        await callback.answer()

    async def settings(self, callback: types.CallbackQuery):
        row = self._query_one("select nickname from public.mafia_players where id=:id", {"id": callback.from_user.id})
        current = (row or {}).get("nickname") or "تنظیم نشده"
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("✏️ تغییر نام مستعار", callback_data="up:nickname:set"),
            InlineKeyboardButton("🗑 حذف نام مستعار", callback_data="up:nickname:delete"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="up:menu"),
        )
        await callback.message.edit_text(f"⚙️ <b>تنظیمات</b>\n\nنام مستعار فعلی: <b>{html.escape(str(current))}</b>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def ask_nickname(self, callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(UserPanelStates.waiting_for_nickname)
        await callback.message.answer("✏️ نام مستعار جدید را ارسال کنید.\n\nبرای لغو: /cancel")
        await callback.answer()

    async def save_nickname(self, message: types.Message, state: FSMContext):
        value = (message.text or "").strip()
        if not value or len(value) > 32:
            await message.answer("⚠️ نام مستعار باید بین ۱ تا ۳۲ کاراکتر باشد.")
            return
        ok = self._execute(
            """insert into public.mafia_players (id, username, first_name, last_name, nickname, updated_at)
               values (:id,:username,:first_name,:last_name,:nickname,now())
               on conflict (id) do update set nickname=:nickname, username=coalesce(:username, public.mafia_players.username),
               first_name=coalesce(:first_name, public.mafia_players.first_name), last_name=coalesce(:last_name, public.mafia_players.last_name), updated_at=now()""",
            {"id": message.from_user.id, "username": message.from_user.username, "first_name": message.from_user.first_name, "last_name": message.from_user.last_name, "nickname": value},
        )
        await state.finish()
        if ok:
            await message.answer("✅ نام مستعار ذخیره شد.", reply_markup=self._menu())
        else:
            await message.answer("❌ ذخیره نام مستعار انجام نشد. اتصال دیتابیس را بررسی کنید.", reply_markup=self._menu())

    async def delete_nickname(self, callback: types.CallbackQuery):
        ok = self._execute("update public.mafia_players set nickname=null, updated_at=now() where id=:id", {"id": callback.from_user.id})
        await callback.answer("✅ نام مستعار حذف شد." if ok else "❌ حذف انجام نشد.", show_alert=not ok)
        await self.settings(callback)

    async def help(self, callback: types.CallbackQuery):
        body = (
            "❓ <b>راهنمای پنل کاربری</b>\n\n"
            "👤 پروفایل: اطلاعات حساب و نام نمایشی\n"
            "📊 آمار: سابقه حضور در بازی‌ها\n"
            "🏆 رتبه‌بندی: فعلاً بر اساس تعداد بازی\n"
            "📜 تاریخچه: آخرین بازی‌های ثبت‌شده\n"
            "⚙️ تنظیمات: مدیریت نام مستعار\n\n"
            "پنل خصوصی برای امکانات شخصی بازیکن است و مدیریت بازی همچنان از مسیر مدیریت بازی انجام می‌شود."
        )
        await callback.message.edit_text(body, reply_markup=self._back_menu(), parse_mode="HTML")
        await callback.answer()

    def _back_menu(self):
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"))
        return kb

    def register(self):
        dp = self.app.dp
        dp.register_message_handler(self.open_panel, commands=["panel", "پنل"], state="*")
        dp.register_message_handler(self.save_nickname, state=UserPanelStates.waiting_for_nickname)
        dp.register_callback_query_handler(self.open_panel_callback, lambda c: c.data == "up:menu")
        dp.register_callback_query_handler(self.profile, lambda c: c.data == "up:profile")
        dp.register_callback_query_handler(self.stats, lambda c: c.data == "up:stats")
        dp.register_callback_query_handler(self.leaderboard, lambda c: c.data == "up:leaderboard")
        dp.register_callback_query_handler(self.history, lambda c: c.data == "up:history")
        dp.register_callback_query_handler(self.settings, lambda c: c.data == "up:settings")
        dp.register_callback_query_handler(self.help, lambda c: c.data == "up:help")
        dp.register_callback_query_handler(self.ask_nickname, lambda c: c.data == "up:nickname:set")
        dp.register_callback_query_handler(self.delete_nickname, lambda c: c.data == "up:nickname:delete")

    async def open_panel_callback(self, callback: types.CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer("فقط در پیوی.", show_alert=True)
            return
        await callback.message.edit_text("🎭 <b>پنل کاربری Mafia Nights</b>\n\nیکی از گزینه‌های زیر را انتخاب کنید:", reply_markup=self._menu(), parse_mode="HTML")
        await callback.answer()


def install(app):
    panel = UserPanel(app)
    panel.register()
    return panel
