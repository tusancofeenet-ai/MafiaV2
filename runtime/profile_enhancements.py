from __future__ import annotations

import html
import re
from typing import Optional

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text

from player_repository import PlayerRepository


PERSIAN_NICK_RE = re.compile(r"^[آ-ی‌\u200c\s]+$")


class ProfileStates(StatesGroup):
    waiting_nickname = State()
    waiting_transfer_target = State()
    waiting_transfer_confirm = State()


class ProfileEnhancements:
    def __init__(self, app, user_panel=None):
        self.app = app
        self.user_panel = user_panel
        self.repo = PlayerRepository()
        self.pending_transfers: dict[int, int] = {}
        self.gender_cache: dict[int, str] = {}

    def _session(self):
        return self.repo.SessionLocal()

    def _profile(self, uid: int):
        with self._session() as s:
            row = s.execute(text("select id,username,first_name,last_name,nickname,gender from public.mafia_players where id=:id"), {"id": int(uid)}).mappings().first()
            return dict(row) if row else None

    @staticmethod
    def _normalize(value: str) -> str:
        return (value or "").strip().replace("ي", "ی").replace("ى", "ی").replace("ك", "ک")

    @classmethod
    def _valid_nickname(cls, value: str) -> bool:
        value = cls._normalize(value)
        return 1 <= len(value) <= 32 and bool(PERSIAN_NICK_RE.fullmatch(value)) and any("آ" <= c <= "ی" for c in value)

    @staticmethod
    def _gender_emoji(gender: Optional[str]) -> str:
        return "👩" if gender == "female" else "👨" if gender == "male" else ""

    def _invalidate(self, uid: int):
        try:
            from player_service import player_service
            player_service.invalidate(uid)
        except Exception:
            pass
        self.gender_cache.pop(int(uid), None)

    def _is_manager(self, actor: int, group_id: int) -> bool:
        admins = {int(x) for x in getattr(self.app, "admins", set()) or set()}
        admins.update(int(x) for x in getattr(self.app, "group_admins", []) or [])
        if int(actor) in admins:
            return True
        try:
            game = self.app.runtime.state.active_game(int(group_id))
            return bool(game and int(game.get("moderator_id") or 0) == int(actor))
        except Exception:
            return False

    async def profile(self, callback: types.CallbackQuery):
        uid = int(callback.from_user.id)
        row = self._profile(uid) or {"username": callback.from_user.username, "first_name": callback.from_user.first_name, "last_name": callback.from_user.last_name}
        with self._session() as s:
            games = int(s.execute(text("select count(*) from public.mafia_game_players where player_id=:id"), {"id": uid}).scalar() or 0)
        gender = row.get("gender")
        gtext = "دختر 👩" if gender == "female" else "پسر 👨" if gender == "male" else "تعیین نشده"
        nickname = row.get("nickname") or "تنظیم نشده"
        name = nickname if nickname != "تنظیم نشده" else " ".join(x for x in ((row.get("first_name") or "").strip(), (row.get("last_name") or "").strip()) if x) or row.get("username") or "❓"
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("⚧ جنسیت", callback_data="profile:gender"),
            InlineKeyboardButton("✏️ نام مستعار", callback_data="profile:nickname"),
            InlineKeyboardButton("🔁 انتقال حساب", callback_data="profile:transfer"),
            InlineKeyboardButton("⚙️ تنظیمات پروفایل", callback_data="profile:settings"),
            InlineKeyboardButton("⬅️ پنل اصلی", callback_data="up:menu"),
        )
        body = ("👤 <b>پروفایل من</b>\n\n" f"نام: <b>{html.escape(str(name))}</b>\n" f"نام مستعار: <b>{html.escape(str(nickname))}</b>\n" f"جنسیت: <b>{gtext}</b>\n" f"نام کاربری: @{html.escape(str(row.get('username'))) if row.get('username') else '—'}\n" f"شناسه عددی: <code>{uid}</code>\n" f"تعداد بازی: <b>{games}</b>")
        await callback.message.edit_text(body, reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def gender_menu(self, callback: types.CallbackQuery):
        kb = InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("👩 دختر", callback_data="profile:gender:female"),
            InlineKeyboardButton("👨 پسر", callback_data="profile:gender:male"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="up:profile"),
        )
        await callback.message.edit_text("⚧ <b>تعیین جنسیت</b>\n\nجنسیت را انتخاب کنید:", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def set_gender(self, callback: types.CallbackQuery):
        gender = callback.data.rsplit(":", 1)[-1]
        if gender not in {"male", "female"}:
            await callback.answer("❌ گزینه نامعتبر است.", show_alert=True); return
        with self._session() as s:
            result = s.execute(text("update public.mafia_players set gender=:gender,updated_at=now() where id=:id"), {"gender": gender, "id": int(callback.from_user.id)})
            s.commit()
        ok = result.rowcount > 0
        if ok: self._invalidate(callback.from_user.id)
        await callback.answer("✅ جنسیت ذخیره شد." if ok else "❌ ذخیره جنسیت انجام نشد.", show_alert=not ok)
        await self.profile(callback)

    async def nickname_prompt(self, callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(ProfileStates.waiting_nickname)
        await callback.message.answer("✏️ نام مستعار را ارسال کنید.\n\nفقط حروف فارسی و فاصله مجاز است؛ عدد، انگلیسی، علامت و اموجی مجاز نیست. حداکثر ۳۲ نویسه.\n\nبرای حذف: <code>حذف</code>", parse_mode="HTML")
        await callback.answer()

    async def save_nickname(self, message: types.Message, state: FSMContext):
        value = self._normalize(message.text)
        if value == "حذف":
            nickname = None
        elif self._valid_nickname(value):
            nickname = value
        else:
            await message.answer("❌ نام مستعار نامعتبر است. فقط حروف فارسی و فاصله مجاز است و حداکثر ۳۲ نویسه می‌تواند باشد."); return
        with self._session() as s:
            result = s.execute(text("update public.mafia_players set nickname=:nickname,updated_at=now() where id=:id"), {"nickname": nickname, "id": int(message.from_user.id)})
            s.commit()
        await state.finish()
        if result.rowcount > 0:
            self._invalidate(message.from_user.id); await message.answer("✅ نام مستعار ذخیره شد.", reply_markup=self.user_panel._menu())
        else:
            await message.answer("❌ ذخیره نام مستعار انجام نشد.", reply_markup=self.user_panel._menu())

    async def settings(self, callback: types.CallbackQuery):
        row = self._profile(callback.from_user.id) or {}
        g = "دختر 👩" if row.get("gender") == "female" else "پسر 👨" if row.get("gender") == "male" else "تعیین نشده"
        n = row.get("nickname") or "تنظیم نشده"
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(f"⚧ جنسیت: {g}", callback_data="profile:gender"),
            InlineKeyboardButton("✏️ تغییر نام مستعار", callback_data="profile:nickname"),
            InlineKeyboardButton("🔁 انتقال حساب من", callback_data="profile:transfer"),
            InlineKeyboardButton("⬅️ پروفایل", callback_data="up:profile"),
        )
        await callback.message.edit_text(f"⚙️ <b>تنظیمات پروفایل</b>\n\nجنسیت: <b>{g}</b>\nنام مستعار: <b>{html.escape(str(n))}</b>", reply_markup=kb, parse_mode="HTML")
        await callback.answer()

    async def transfer_prompt(self, callback: types.CallbackQuery, state: FSMContext):
        await state.set_state(ProfileStates.waiting_transfer_target)
        await callback.message.answer("🔁 <b>انتقال حساب</b>\n\nآیدی عددی تلگرام حساب مقصد را ارسال کنید.\nمثال: <code>123456789</code>", parse_mode="HTML")
        await callback.answer()

    async def transfer_target(self, message: types.Message, state: FSMContext):
        raw = (message.text or "").strip()
        if not raw.isdigit() or int(raw) <= 0 or int(raw) == int(message.from_user.id):
            await message.answer("❌ آیدی مقصد باید یک عدد مثبت و متفاوت از حساب فعلی باشد."); return
        self.pending_transfers[int(message.from_user.id)] = int(raw)
        await state.set_state(ProfileStates.waiting_transfer_confirm)
        kb = InlineKeyboardMarkup(row_width=2).add(InlineKeyboardButton("✅ تأیید", callback_data="profile:transfer:confirm"), InlineKeyboardButton("❌ لغو", callback_data="profile:transfer:cancel"))
        await message.answer(f"⚠️ انتقال اطلاعات حساب به <code>{int(raw)}</code> انجام شود؟\n\nسابقه بازی، نام مستعار و جنسیت منتقل می‌شود.", reply_markup=kb, parse_mode="HTML")

    def transfer_account(self, source: int, target: int, actor: int, group_id: Optional[int]):
        source, target, actor = int(source), int(target), int(actor)
        if source == target: return False, "❌ حساب مبدأ و مقصد یکسان است."
        if group_id is not None and not self._is_manager(actor, group_id): return False, "❌ فقط مدیر گروه می‌تواند انتقال حساب انجام دهد."
        try:
            with self._session() as s:
                source_row = s.execute(text("select * from public.mafia_players where id=:id for update"), {"id": source}).mappings().first()
                if not source_row: return False, "❌ حساب مبدأ پیدا نشد."
                if s.execute(text("select 1 from public.mafia_game_players where player_id=:id limit 1"), {"id": target}).first(): return False, "❌ حساب مقصد قبلاً سابقه بازی دارد؛ برای جلوگیری از ادغام اشتباه، مقصد باید حساب تازه باشد."
                if s.execute(text("select 1 from public.mafia_game_players gp join public.mafia_games g on g.id=gp.game_id where gp.player_id=:id and g.status in ('lobby','running','paused') limit 1"), {"id": source}).first(): return False, "❌ انتقال در زمان حضور در بازی فعال مجاز نیست."
                s.execute(text("insert into public.mafia_players(id,username,first_name,last_name,nickname,gender,created_at,updated_at) values (:target,:username,:first_name,:last_name,:nickname,:gender,now(),now()) on conflict (id) do update set username=coalesce(excluded.username,public.mafia_players.username),first_name=coalesce(excluded.first_name,public.mafia_players.first_name),last_name=coalesce(excluded.last_name,public.mafia_players.last_name),nickname=coalesce(excluded.nickname,public.mafia_players.nickname),gender=coalesce(excluded.gender,public.mafia_players.gender),updated_at=now()),", {"target": target, "username": source_row.get("username"), "first_name": source_row.get("first_name"), "last_name": source_row.get("last_name"), "nickname": source_row.get("nickname"), "gender": source_row.get("gender")})
                for table, column in (("mafia_game_players","player_id"),("mafia_game_turns","player_id"),("mafia_challenges","challenger_id"),("mafia_challenges","target_id"),("mafia_ratings","voter_id"),("mafia_ratings","target_id"),("mafia_ratings","user_id")):
                    s.execute(text(f"update public.{table} set {column}=:target where {column}=:source"), {"source": source, "target": target})
                s.execute(text("insert into public.mafia_account_transfers(source_user_id,target_user_id,actor_user_id,group_chat_id) values (:source,:target,:actor,:group_id)"), {"source": source, "target": target, "actor": actor, "group_id": group_id})
                s.execute(text("delete from public.mafia_players where id=:id"), {"id": source}); s.commit()
            self._invalidate(source); self._invalidate(target)
            return True, "✅ انتقال حساب انجام شد."
        except Exception:
            return False, "❌ انتقال حساب انجام نشد. داده مقصد یا ساختار سابقه بازی با انتقال سازگار نیست."

    async def transfer_confirm(self, callback: types.CallbackQuery, state: FSMContext):
        source = int(callback.from_user.id); target = int(self.pending_transfers.get(source) or 0)
        self.pending_transfers.pop(source, None); await state.finish()
        ok, msg = self.transfer_account(source, target, source, None)
        await callback.answer(msg, show_alert=True)
        if ok: await callback.message.edit_text("✅ انتقال حساب با موفقیت انجام شد.\n\nحساب مقصد اکنون هویت اصلی شما در Mafia Nights است.", parse_mode="HTML")

    async def transfer_cancel(self, callback: types.CallbackQuery, state: FSMContext):
        self.pending_transfers.pop(int(callback.from_user.id), None); await state.finish(); await self.profile(callback)

    async def admin_transfer_command(self, message: types.Message):
        if message.chat.type == "private": return
        parts = (message.text or "").split()
        if len(parts) != 4 or not parts[2].isdigit() or not parts[3].isdigit():
            await message.reply("❌ قالب صحیح: <code>انتقال حساب آیدی_مبدأ آیدی_مقصد</code>", parse_mode="HTML"); return
        actor, group = int(message.from_user.id), int(message.chat.id)
        if not self._is_manager(actor, group): await message.reply("❌ فقط مدیر گروه می‌تواند انتقال حساب انجام دهد."); return
        ok, msg = self.transfer_account(int(parts[2]), int(parts[3]), actor, group); await message.reply(msg)

    def register(self):
        try:
            handlers = self.app.dp.callback_query_handlers.handlers
            if self.user_panel:
                handlers[:] = [h for h in handlers if not (getattr(getattr(h.get("handler"), "__self__", None), "__class__", None) is self.user_panel.__class__ and getattr(getattr(h.get("handler"), "__func__", None), "__name__", "") == "profile")]
        except Exception: pass
        self.app.dp.register_callback_query_handler(self.profile, lambda c: c.data == "up:profile")
        if self.user_panel:
            old_menu = self.user_panel._menu
            self.user_panel._menu = lambda: old_menu().add(InlineKeyboardButton("⚙️ تنظیمات پروفایل", callback_data="profile:settings"))
        dp = self.app.dp
        dp.register_callback_query_handler(self.gender_menu, lambda c: c.data == "profile:gender")
        dp.register_callback_query_handler(self.set_gender, lambda c: c.data in {"profile:gender:male","profile:gender:female"})
        dp.register_callback_query_handler(self.settings, lambda c: c.data == "profile:settings")
        dp.register_callback_query_handler(self.nickname_prompt, lambda c: c.data == "profile:nickname")
        dp.register_callback_query_handler(self.transfer_prompt, lambda c: c.data == "profile:transfer")
        dp.register_callback_query_handler(self.transfer_confirm, lambda c: c.data == "profile:transfer:confirm")
        dp.register_callback_query_handler(self.transfer_cancel, lambda c: c.data == "profile:transfer:cancel")
        dp.register_message_handler(self.save_nickname, state=ProfileStates.waiting_nickname)
        dp.register_message_handler(self.transfer_target, state=ProfileStates.waiting_transfer_target)
        dp.register_message_handler(self.admin_transfer_command, lambda m: (m.text or "").startswith("انتقال حساب"), content_types=types.ContentTypes.TEXT)


def install(app, user_panel=None):
    enhancement = ProfileEnhancements(app, user_panel)
    try:
        from player_service import player_service
        original = player_service.display_name
        def display_name_with_gender(user_id, fallback="❓"):
            uid = int(user_id); name = original(uid, fallback)
            if uid not in enhancement.gender_cache:
                row = enhancement._profile(uid); enhancement.gender_cache[uid] = (row or {}).get("gender") or ""
            emoji = enhancement._gender_emoji(enhancement.gender_cache.get(uid))
            return f"{emoji} {name}".strip() if emoji else name
        player_service.display_name = display_name_with_gender
    except Exception: pass
    enhancement.register()
    return enhancement
