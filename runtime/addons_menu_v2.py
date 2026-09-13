"""Private add-ons/settings controller for MafiaNights.

The private UI owns the top-level navigation; this module owns only the
add-ons/settings screens and their controls.
"""
from __future__ import annotations

import copy

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from mafia_addons import DEFAULT_GROUP_SETTINGS


class AddonsMenuV2:
    def __init__(self, app):
        self.app = app
        self.dp = app.dp
        self.addons = getattr(app, "addons", None)

    def group_id(self):
        for obj in (self.addons, self.app):
            for attr in ("group_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_chat_id"):
                value = getattr(obj, attr, None)
                if value:
                    try:
                        return int(value)
                    except (TypeError, ValueError):
                        pass
        return None

    async def allowed(self, uid):
        if uid == getattr(self.app, "moderator_id", None):
            return True
        for attr in ("admins", "group_admins"):
            for item in getattr(self.app, attr, None) or []:
                candidate = getattr(getattr(item, "user", None), "id", item)
                if candidate == uid:
                    return True
        gid = self.group_id()
        if not gid:
            return False
        try:
            admins = await self.app.bot.get_chat_administrators(gid)
            admin_ids = {a.user.id for a in admins}
            self.app.admins = admin_ids
            return uid in admin_ids
        except Exception:
            return False

    def settings(self):
        if not self.addons:
            return copy.deepcopy(DEFAULT_GROUP_SETTINGS)
        gid = self.group_id()
        if gid:
            self.addons.settings = self.addons.get_group_settings(gid)
        return self.addons.settings

    def save(self, settings):
        gid = self.group_id()
        if self.addons and gid:
            self.addons.set_group_settings(gid, settings)
            self.addons.settings = settings

    async def menu(self, callback):
        if callback.message.chat.type != "private":
            raise CancelHandler()
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ فقط مدیران گروه یا گرداننده دسترسی دارند.", show_alert=True)
            raise CancelHandler()
        s = self.settings()
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("🔐 امنیت بازی", callback_data="adm2:add:security"),
            InlineKeyboardButton("⏭ مدیریت نکست", callback_data="adm2:add:next"),
            InlineKeyboardButton("▶️ شروع خودکار", callback_data="adm2:add:auto"),
            InlineKeyboardButton("🎨 نمایش و رنگ‌بندی", callback_data="adm2:add:visual"),
            InlineKeyboardButton("♻️ بازگردانی تنظیمات پیش‌فرض", callback_data="adm2:add:reset"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="addons:back"),
        )
        await callback.message.edit_text(
            "⚙️ <b>امکانات اضافه</b>\n\n"
            f"🛡 امنیت: {'فعال' if s.get('security', {}).get('control_speech', True) else 'غیرفعال'}\n"
            f"⏭ ضداسپم: {'فعال' if s.get('next', {}).get('anti_spam', True) else 'غیرفعال'}\n"
            f"▶️ شروع خودکار: {'فعال' if s.get('auto_start', {}).get('enabled', False) else 'غیرفعال'}",
            reply_markup=kb, parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def back_main(self, callback):
        if callback.message.chat.type != "private":
            raise CancelHandler()
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        from runtime.final_private_ui import start_keyboard
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def security(self, callback):
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        s = self.settings().get("security", {})
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(f"🗣 کنترل نوبت صحبت: {'فعال' if s.get('control_speech', True) else 'غیرفعال'}", callback_data="adm2:add:toggle:speech"),
            InlineKeyboardButton(f"🗑 حذف پیام خارج نوبت: {'فعال' if s.get('delete_out_of_turn', True) else 'غیرفعال'}", callback_data="adm2:add:toggle:delete"),
            InlineKeyboardButton("⬅️ امکانات اضافه", callback_data="addons_menu"),
        )
        await callback.message.edit_text("🔐 <b>امنیت بازی</b>", reply_markup=kb, parse_mode="HTML"); await callback.answer(); raise CancelHandler()

    async def next_menu(self, callback):
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        s = self.settings().get("next", {})
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(f"🛡 ضداسپم نکست: {'فعال' if s.get('anti_spam', True) else 'غیرفعال'}", callback_data="adm2:add:toggle:anti"),
            InlineKeyboardButton(f"👤 اجازه نکست به بازیکنان: {'فعال' if s.get('allow_players_next', True) else 'غیرفعال'}", callback_data="adm2:add:toggle:players"),
            InlineKeyboardButton(f"🎩 اجازه نکست به گرداننده: {'فعال' if s.get('allow_moderator_next', True) else 'غیرفعال'}", callback_data="adm2:add:toggle:moderator"),
            InlineKeyboardButton("⬅️ امکانات اضافه", callback_data="addons_menu"),
        )
        await callback.message.edit_text("⏭ <b>مدیریت نکست</b>", reply_markup=kb, parse_mode="HTML"); await callback.answer(); raise CancelHandler()

    async def auto(self, callback):
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        s = self.settings().get("auto_start", {})
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(f"▶️ شروع خودکار دور جدید: {'فعال' if s.get('enabled', False) else 'غیرفعال'}", callback_data="adm2:add:toggle:auto"),
            InlineKeyboardButton("⬅️ امکانات اضافه", callback_data="addons_menu"),
        )
        await callback.message.edit_text("▶️ <b>شروع خودکار</b>\n\nاین گزینه در صورت پشتیبانی جریان بازی، آغاز خودکار دور بعدی را کنترل می‌کند.", reply_markup=kb, parse_mode="HTML"); await callback.answer(); raise CancelHandler()

    async def visual(self, callback):
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        s = self.settings().get("color", {})
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(f"🎨 نمایش نوبت اصلی: {'فعال' if s.get('primary', True) else 'غیرفعال'}", callback_data="adm2:add:toggle:primary"),
            InlineKeyboardButton(f"🟥 نمایش نوبت چالش: {'فعال' if s.get('challenge', True) else 'غیرفعال'}", callback_data="adm2:add:toggle:challenge"),
            InlineKeyboardButton("⬅️ امکانات اضافه", callback_data="addons_menu"),
        )
        await callback.message.edit_text("🎨 <b>نمایش و رنگ‌بندی</b>", reply_markup=kb, parse_mode="HTML"); await callback.answer(); raise CancelHandler()

    async def toggle(self, callback):
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        s = self.settings()
        mapping = {"speech": ("security", "control_speech", True), "delete": ("security", "delete_out_of_turn", True), "anti": ("next", "anti_spam", True), "players": ("next", "allow_players_next", True), "moderator": ("next", "allow_moderator_next", True), "auto": ("auto_start", "enabled", False), "primary": ("color", "primary", True), "challenge": ("color", "challenge", True)}
        key = callback.data.rsplit(":", 1)[1]
        if key not in mapping:
            await callback.answer("تنظیم نامعتبر است.", show_alert=True); raise CancelHandler()
        section, option, default = mapping[key]
        s.setdefault(section, {})
        s[section][option] = not s[section].get(option, default)
        self.save(s)
        if key in {"speech", "delete"}: await self.security(callback)
        elif key in {"anti", "players", "moderator"}: await self.next_menu(callback)
        elif key == "auto": await self.auto(callback)
        else: await self.visual(callback)

    async def reset(self, callback):
        if not await self.allowed(callback.from_user.id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True); raise CancelHandler()
        self.save(copy.deepcopy(DEFAULT_GROUP_SETTINGS))
        await self.menu(callback)

    def install(self):
        d = self.dp
        d.register_callback_query_handler(self.menu, lambda c: c.data == "addons_menu", state="*")
        d.register_callback_query_handler(self.back_main, lambda c: c.data == "addons:back", state="*")
        d.register_callback_query_handler(self.security, lambda c: c.data == "adm2:add:security", state="*")
        d.register_callback_query_handler(self.next_menu, lambda c: c.data == "adm2:add:next", state="*")
        d.register_callback_query_handler(self.auto, lambda c: c.data == "adm2:add:auto", state="*")
        d.register_callback_query_handler(self.visual, lambda c: c.data == "adm2:add:visual", state="*")
        d.register_callback_query_handler(self.toggle, lambda c: c.data.startswith("adm2:add:toggle:"), state="*")
        d.register_callback_query_handler(self.reset, lambda c: c.data == "adm2:add:reset", state="*")
        handlers = getattr(d.callback_query_handlers, "handlers", [])
        names = {"menu", "back_main", "security", "next_menu", "auto", "visual", "toggle", "reset"}
        for i in range(len(handlers) - 1, -1, -1):
            if getattr(getattr(handlers[i], "handler", None), "__name__", "") in names:
                handlers.insert(0, handlers.pop(i))
        return self


def install(app):
    return AddonsMenuV2(app).install()
