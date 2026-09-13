"""Return the private user dashboard to the canonical private main menu."""
from __future__ import annotations

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

BACK_CALLBACK = "userpanel:back"


def _private_main_kb():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"))
    kb.add(InlineKeyboardButton("⚙ مدیریت سناریو", callback_data="manage_scenarios"))
    kb.add(InlineKeyboardButton("⚙ امکانات اضافه", callback_data="addons_menu"))
    kb.add(InlineKeyboardButton("👤 پروفایل", callback_data="up:menu"))
    kb.add(InlineKeyboardButton("📚 راهنما", callback_data="help"))
    return kb


def install(app, panel):
    original_menu = panel._menu

    def menu_with_back():
        kb = original_menu()
        kb.add(InlineKeyboardButton("⬅️ بازگشت به منوی اصلی", callback_data=BACK_CALLBACK))
        return kb

    panel._menu = menu_with_back

    async def back_to_main(callback: types.CallbackQuery):
        if callback.message.chat.type != "private":
            await callback.answer("فقط در پیوی.", show_alert=True)
            return

        await callback.message.edit_text("📋 منوی ربات:", reply_markup=_private_main_kb())
        await callback.answer()

    app.dp.register_callback_query_handler(back_to_main, lambda c: c.data == BACK_CALLBACK)
    return back_to_main
