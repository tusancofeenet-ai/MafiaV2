"""Last-mile private navigation guard.

The legacy/final UI modules reorder their own handlers during startup. This tiny
layer is installed after them and owns the navigation callbacks whose behavior
must never fall through to a legacy handler (especially Back buttons).
"""
from __future__ import annotations

import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def install(app):
    dp = app.dp
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        return False

    def private(c):
        return bool(c.message and c.message.chat.type == "private")

    async def allowed(c):
        if not private(c):
            raise CancelHandler()
        uid = int(c.from_user.id)
        if uid == int(getattr(app, "moderator_id", 0) or 0):
            return True
        cached = set()
        for key in ("admins", "group_admins"):
            value = getattr(app, key, None) or []
            try:
                cached.update(int(x) for x in value)
            except (TypeError, ValueError):
                pass
        if uid in cached:
            return True
        gid = getattr(app, "ALLOWED_GROUP_ID", None)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(int(gid))
                if uid in {int(x.user.id) for x in admins}:
                    return True
            except Exception:
                logging.exception("private authority reorder: admin lookup failed")
        await c.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    async def back_to_start(c):
        if not private(c):
            raise CancelHandler()
        from runtime.final_private_ui import start_keyboard
        try:
            await c.message.edit_text(
                "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
                reply_markup=start_keyboard(), parse_mode="HTML",
            )
        except Exception as exc:
            if exc.__class__.__name__ != "MessageNotModified":
                raise
        await c.answer()
        raise CancelHandler()

    async def back_to_management(c):
        await allowed(c)
        from runtime.final_private_ui import management_keyboard, management_report
        try:
            await c.message.edit_text(
                management_report(app), reply_markup=management_keyboard(), parse_mode="HTML"
            )
        except Exception as exc:
            if exc.__class__.__name__ != "MessageNotModified":
                raise
        await c.answer()
        raise CancelHandler()

    async def addons_back(c):
        # Pure navigation: do not perform an unrelated Telegram admin lookup.
        await back_to_start(c)

    registrations = [
        (back_to_management, lambda c: c.data == "finalgm:back"),
        (back_to_start, lambda c: c.data in {"back_manage_game", "back_main", "final:start", "private:start"}),
        (addons_back, lambda c: c.data == "addons:back"),
    ]
    owned = []
    for fn, filt in registrations:
        dp.register_callback_query_handler(fn, filt, state="*")
        owned.append(fn)

    def handler_fn(item):
        return getattr(item, "handler", None) or getattr(item, "callback", None)

    # Always move this layer to the absolute front. This is deliberately done
    # on every install call because final_private_ui also reorders itself.
    for i in range(len(registry) - 1, -1, -1):
        if handler_fn(registry[i]) in owned:
            registry.insert(0, registry.pop(i))

    # Avoid accumulating duplicate registrations on repeated startup calls.
    # The flag is informational; the first installation remains at the front.
    app._private_authority_reorder_installed = True
    logging.info("Private navigation reorder authority promoted")
    return True
