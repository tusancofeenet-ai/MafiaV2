"""Complete scenario administration for MafiaNights.

Scenario data is kept backward-compatible: roles remain a list of role names,
while the new per-role side/challenge rules live in the scenario ``config``
JSONB. Existing scenarios therefore continue to load unchanged.
"""
from __future__ import annotations

import html
import json
from typing import Any

from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from repositories.scenario_repository import ScenarioRepository


class ScenarioForm(StatesGroup):
    name = State()
    description = State()
    min_players = State()
    max_players = State()
    roles = State()
    role_sides = State()
    challenge_mode = State()
    challenge_limit = State()
    settings = State()


class ScenarioManagementV2:
    def __init__(self, app: Any):
        self.app = app
        self.repo = ScenarioRepository()
        self.sessions: dict[int, dict[str, Any]] = {}

    async def _admin(self, obj: Any) -> bool:
        gid = int(obj.message.chat.id if getattr(obj, "message", None) else obj.chat.id)
        uid = int(obj.from_user.id)
        try:
            member = await self.app.bot.get_chat_member(gid, uid)
            return member.status in {"creator", "administrator"}
        except Exception:
            return False

    def _buttons(self, rows):
        kb = InlineKeyboardMarkup(row_width=1)
        for text, data in rows:
            kb.add(InlineKeyboardButton(text, callback_data=data))
        return kb

    def _summary(self, row: dict[str, Any]) -> str:
        cfg = row.get("config") or {}
        if isinstance(cfg, str):
            try: cfg = json.loads(cfg)
            except Exception: cfg = {}
        roles = row.get("roles") or []
        role_cfg = cfg.get("roles") or {}
        sides = cfg.get("sides") or {}
        mode = cfg.get("challenge_mode", "limited")
        limit = cfg.get("challenge_limit", 1)
        settings = cfg.get("settings") or {}
        lines = [
            f"📝 <b>{html.escape(str(row.get('name') or 'بدون نام'))}</b>",
            f"📖 توضیح: {html.escape(str(row.get('description') or '—'))}",
            f"👥 بازیکنان: <b>{row.get('min_players') or '—'} تا {row.get('max_players') or '—'}</b>",
            f"⚔️ چالش: <b>{'آزاد' if mode == 'free' else 'محدود'}</b>" + (f" | سقف: {limit}" if mode != "free" else ""),
            "",
            "🎭 <b>ترکیب نقش‌ها</b>",
        ]
        for role in roles:
            r = str(role)
            rc = role_cfg.get(r) or {}
            side = rc.get("side") or sides.get(r) or "نامشخص"
            rmode = rc.get("challenge", mode)
            lines.append(f"• {html.escape(r)} — ساید: {html.escape(str(side))} — چالش: {html.escape(str(rmode))}")
        if settings:
            lines += ["", "⚙️ <b>تنظیمات</b>"]
            for k, v in settings.items():
                lines.append(f"• {html.escape(str(k))}: {html.escape(str(v))}")
        return "\n".join(lines)

    async def menu(self, callback: types.CallbackQuery):
        if not await self._admin(callback):
            await callback.answer("⛔ فقط مدیران گروه.", show_alert=True); return
        rows = self.repo.list_active()
        kb = self._buttons([("➕ افزودن سناریو", "sm2:add"), ("✏️ ویرایش سناریو", "sm2:edit")])
        for row in rows:
            kb.add(InlineKeyboardButton(f"📜 {row['name']}", callback_data=f"sm2:view:{row['id']}"))
        kb.add(InlineKeyboardButton("🗑 حذف سناریو", callback_data="sm2:delete"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="fp:panel"))
        await callback.message.edit_text("📚 <b>مدیریت سناریوها</b>\n\nسناریو را برای مشاهده یا ویرایش انتخاب کنید.", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def view(self, callback: types.CallbackQuery):
        if not await self._admin(callback): return
        row = self.repo.get_by_id(int(callback.data.rsplit(":", 1)[1]))
        if not row:
            await callback.answer("سناریو پیدا نشد.", show_alert=True); return
        kb = self._buttons([
            ("✏️ ویرایش", f"sm2:edit:{row['id']}"),
            ("🗑 حذف", f"sm2:delete:{row['id']}"),
            ("⬅️ بازگشت", "sm2:menu"),
        ])
        await callback.message.edit_text(self._summary(row), parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    async def start_add(self, callback: types.CallbackQuery, state: FSMContext):
        if not await self._admin(callback): return
        self.sessions[int(callback.from_user.id)] = {"mode": "add"}
        await callback.message.answer("📝 نام سناریو را وارد کنید:")
        await ScenarioForm.name.set(); await callback.answer()

    async def start_edit(self, callback: types.CallbackQuery, state: FSMContext):
        if not await self._admin(callback): return
        sid = int(callback.data.rsplit(":", 1)[1]) if callback.data.count(":") == 2 else None
        if sid is None:
            rows = self.repo.list_active()
            kb = self._buttons([(f"✏️ {r['name']}", f"sm2:edit:{r['id']}") for r in rows] + [("⬅️ بازگشت", "sm2:menu")])
            await callback.message.edit_text("سناریوی موردنظر را انتخاب کنید:", reply_markup=kb); await callback.answer(); return
        row = self.repo.get_by_id(sid)
        if not row: await callback.answer("سناریو پیدا نشد.", show_alert=True); return
        cfg = row.get("config") or {}
        if isinstance(cfg, str):
            try: cfg = json.loads(cfg)
            except Exception: cfg = {}
        data = dict(row); data["config"] = cfg
        self.sessions[int(callback.from_user.id)] = {"mode": "edit", "id": sid, "data": data}
        await callback.message.answer(f"✏️ ویرایش «{html.escape(str(row['name']))}»\n\nنام جدید را وارد کنید (برای حفظ نام فعلی: -):", parse_mode="HTML")
        await ScenarioForm.name.set(); await callback.answer()

    async def name(self, message: types.Message, state: FSMContext):
        s = self.sessions.setdefault(int(message.from_user.id), {"mode": "add"})
        data = s.setdefault("data", {})
        value = (message.text or "").strip()
        if s.get("mode") == "edit" and value == "-": value = str(data.get("name") or "")
        if not value: await message.answer("⚠️ نام معتبر نیست."); return
        data["name"] = value
        await message.answer("📖 توضیح سناریو را وارد کنید (برای بدون توضیح: -):")
        await ScenarioForm.description.set()

    async def description(self, message: types.Message, state: FSMContext):
        s = self.sessions[int(message.from_user.id)]; s["data"]["description"] = None if (message.text or "").strip() == "-" else (message.text or "").strip()
        await message.answer("👥 حداقل تعداد بازیکنان:"); await ScenarioForm.min_players.set()

    async def min_players(self, message: types.Message, state: FSMContext):
        if not (message.text or "").strip().isdigit(): await message.answer("⚠️ عدد وارد کنید."); return
        self.sessions[int(message.from_user.id)]["data"]["min_players"] = int(message.text)
        await message.answer("👥 حداکثر تعداد بازیکنان:"); await ScenarioForm.max_players.set()

    async def max_players(self, message: types.Message, state: FSMContext):
        if not (message.text or "").strip().isdigit(): await message.answer("⚠️ عدد وارد کنید."); return
        s = self.sessions[int(message.from_user.id)]; s["data"]["max_players"] = int(message.text)
        await message.answer("🎭 نقش‌ها را وارد کنید؛ هر نقش در یک خط.\nمثال:\nمافیا\nدکتر\nکارآگاه")
        await ScenarioForm.roles.set()

    async def roles(self, message: types.Message, state: FSMContext):
        roles = [x.strip() for x in (message.text or "").splitlines() if x.strip()]
        if not roles: await message.answer("⚠️ حداقل یک نقش لازم است."); return
        s = self.sessions[int(message.from_user.id)]; s["data"]["roles"] = roles
        await message.answer("⚖️ ساید هر نقش را در قالب زیر وارد کنید، هر خط یک نقش:\nمافیا=مافیا\nدکتر=شهروند\nکارآگاه=شهروند")
        await ScenarioForm.role_sides.set()

    async def role_sides(self, message: types.Message, state: FSMContext):
        s = self.sessions[int(message.from_user.id)]; roles = s["data"]["roles"]
        mapping = {}
        for line in (message.text or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1); mapping[k.strip()] = v.strip()
        missing = [r for r in roles if r not in mapping]
        if missing: await message.answer("⚠️ ساید این نقش‌ها مشخص نشده: " + "، ".join(missing)); return
        s["data"]["sides"] = mapping
        kb = self._buttons([("🔒 محدود", "sm2:challenge:limited"), ("♾ آزاد", "sm2:challenge:free")])
        await message.answer("⚔️ حالت چالش سناریو را انتخاب کنید:", reply_markup=kb)
        await ScenarioForm.challenge_mode.set()

    async def challenge_mode(self, callback: types.CallbackQuery, state: FSMContext):
        if not await self._admin(callback): return
        s = self.sessions[int(callback.from_user.id)]; s["data"]["challenge_mode"] = callback.data.rsplit(":", 1)[1]
        if s["data"]["challenge_mode"] == "limited":
            await callback.message.answer("🔢 حداکثر تعداد چالش دریافتی در هر بازی را وارد کنید:")
            await ScenarioForm.challenge_limit.set()
        else:
            s["data"]["challenge_limit"] = None
            await callback.message.answer("⚙️ تنظیمات اضافی را JSON وارد کنید؛ اگر ندارید «-» بزنید.\nمثال: {\"allow_player_next\":true,\"allow_moderator_next\":true}")
            await ScenarioForm.settings.set()
        await callback.answer()

    async def challenge_limit(self, message: types.Message, state: FSMContext):
        if not (message.text or "").strip().isdigit(): await message.answer("⚠️ عدد وارد کنید."); return
        self.sessions[int(message.from_user.id)]["data"]["challenge_limit"] = int(message.text)
        await message.answer("⚙️ تنظیمات اضافی را JSON وارد کنید؛ اگر ندارید «-» بزنید.")
        await ScenarioForm.settings.set()

    async def settings(self, message: types.Message, state: FSMContext):
        s = self.sessions.pop(int(message.from_user.id)); data = s["data"]
        raw = (message.text or "").strip()
        if raw == "-": settings = {}
        else:
            try: settings = json.loads(raw); assert isinstance(settings, dict)
            except Exception: await message.answer("⚠️ JSON نامعتبر است. دوباره ارسال کنید."); self.sessions[int(message.from_user.id)] = s; return
        role_cfg = {r: {"side": data["sides"][r], "challenge": data["challenge_mode"]} for r in data["roles"]}
        cfg = {"roles": role_cfg, "sides": data["sides"], "challenge_mode": data["challenge_mode"], "challenge_limit": data.get("challenge_limit"), "settings": settings}
        try:
            sid = self.repo.upsert(data["name"], data.get("description"), data["min_players"], data["max_players"], data["roles"], cfg, True)
            await state.finish()
            row = self.repo.get_by_id(sid)
            await message.answer("✅ سناریو ذخیره شد.\n\n" + self._summary(row), parse_mode="HTML")
        except Exception as exc:
            self.sessions[int(message.from_user.id)] = s
            await message.answer(f"❌ ذخیره سناریو انجام نشد: {html.escape(str(exc))}")

    async def delete_menu(self, callback: types.CallbackQuery):
        if not await self._admin(callback): return
        rows = self.repo.list_active()
        kb = self._buttons([(f"🗑 {r['name']}", f"sm2:delete:{r['id']}") for r in rows] + [("⬅️ بازگشت", "sm2:menu")])
        await callback.message.edit_text("سناریوی موردنظر را برای حذف انتخاب کنید:", reply_markup=kb); await callback.answer()

    async def delete(self, callback: types.CallbackQuery):
        if not await self._admin(callback): return
        sid = int(callback.data.rsplit(":", 1)[1]); row = self.repo.get_by_id(sid)
        if not row: await callback.answer("سناریو پیدا نشد.", show_alert=True); return
        kb = self._buttons([("⚠️ بله، حذف شود", f"sm2:delete_confirm:{sid}"), ("❌ انصراف", f"sm2:view:{sid}")])
        await callback.message.edit_text(f"آیا سناریوی «{html.escape(str(row['name']))}» حذف شود؟", parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def delete_confirm(self, callback: types.CallbackQuery):
        if not await self._admin(callback): return
        sid = int(callback.data.rsplit(":", 1)[1]); row = self.repo.get_by_id(sid)
        if not row: await callback.answer("سناریو پیدا نشد.", show_alert=True); return
        self.repo.upsert(row["name"], row.get("description"), row.get("min_players"), row.get("max_players"), row.get("roles") or [], row.get("config") or {}, False)
        await callback.message.edit_text(f"✅ سناریوی «{html.escape(str(row['name']))}» غیرفعال شد.")
        await callback.answer()

    def register(self, dp):
        dp.register_callback_query_handler(self.menu, lambda c: c.data == "fp:scenarios")
        dp.register_callback_query_handler(self.menu, lambda c: c.data == "sm2:menu")
        dp.register_callback_query_handler(self.start_add, lambda c: c.data == "sm2:add")
        dp.register_callback_query_handler(self.start_edit, lambda c: c.data.startswith("sm2:edit"))
        dp.register_callback_query_handler(self.view, lambda c: c.data.startswith("sm2:view:"))
        dp.register_callback_query_handler(self.delete_menu, lambda c: c.data == "sm2:delete")
        dp.register_callback_query_handler(self.delete_confirm, lambda c: c.data.startswith("sm2:delete_confirm:"))
        dp.register_callback_query_handler(self.delete, lambda c: c.data.startswith("sm2:delete:"))
        dp.register_callback_query_handler(self.challenge_mode, lambda c: c.data.startswith("sm2:challenge:"), state=ScenarioForm.challenge_mode)
        dp.register_message_handler(self.name, state=ScenarioForm.name)
        dp.register_message_handler(self.description, state=ScenarioForm.description)
        dp.register_message_handler(self.min_players, state=ScenarioForm.min_players)
        dp.register_message_handler(self.max_players, state=ScenarioForm.max_players)
        dp.register_message_handler(self.roles, state=ScenarioForm.roles)
        dp.register_message_handler(self.role_sides, state=ScenarioForm.role_sides)
        dp.register_message_handler(self.challenge_limit, state=ScenarioForm.challenge_limit)
        dp.register_message_handler(self.settings, state=ScenarioForm.settings)
