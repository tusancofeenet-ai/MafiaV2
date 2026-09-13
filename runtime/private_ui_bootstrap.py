"""Import-time bootstrap for the private UI on webhook runtimes.

Vercel imports ``player_runtime_entry`` for each webhook invocation and does not
run aiogram's polling startup hook first. This module therefore installs the
private entry points immediately. Detailed game-management handlers are lazily
materialized on first click, while scenario CRUD and navigation are handled
here synchronously so legacy handlers cannot steal the callback.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _private(callback):
    return bool(callback.message and callback.message.chat.type == "private")


def _handler(item):
    return getattr(item, "callback", None) or getattr(item, "handler", None)


def _group_id(app):
    for obj in (app, getattr(app, "addons", None)):
        for key in ("ALLOWED_GROUP_ID", "GROUP_ID", "group_chat_id", "group_id"):
            value = getattr(obj, key, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _moderator_id(app):
    for obj in (app, getattr(app, "addons", None)):
        value = getattr(obj, "moderator_id", None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _keyboard_start():
    from runtime.final_private_ui import start_keyboard
    return start_keyboard()


def _management_keyboard():
    from runtime.final_private_ui import management_keyboard
    return management_keyboard()


def _scenario_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ افزودن سناریو", callback_data="private_scenario:add"),
        InlineKeyboardButton("➖ حذف سناریو", callback_data="private_scenario:remove"),
        InlineKeyboardButton("✏️ ویرایش سناریو", callback_data="private_scenario:edit"),
        InlineKeyboardButton("📋 لیست سناریوها", callback_data="private_scenario:list"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="private:start"),
    )
    return kb


def install(app):
    if getattr(app, "_private_ui_bootstrap_installed", False):
        return False
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("private UI bootstrap: callback registry unavailable")
        return False

    async def allowed(callback):
        if not _private(callback):
            raise CancelHandler()
        uid = int(callback.from_user.id)
        if _moderator_id(app) == uid:
            return True
        gid = _group_id(app)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(gid)
                if uid in {int(a.user.id) for a in admins}:
                    return True
            except Exception:
                logging.exception("private UI bootstrap: group admin lookup failed for %s", gid)
        await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    async def start(callback):
        if not _private(callback):
            raise CancelHandler()
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=_keyboard_start(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def management(callback):
        await allowed(callback)
        from runtime.final_private_ui import management_report
        await callback.message.edit_text(
            management_report(app), reply_markup=_management_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def scenarios(callback):
        await allowed(callback)
        await callback.message.edit_text(
            "⚙️ <b>مدیریت سناریو</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=_scenario_keyboard(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_list(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            text = "📋 <b>لیست سناریوها</b>\n\nهیچ سناریویی ثبت نشده است."
        else:
            lines = ["📋 <b>لیست سناریوها</b>", ""]
            for i, name in enumerate(scenarios.keys(), 1):
                lines.append(f"{i}. {html.escape(str(name))}")
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=_scenario_keyboard(), parse_mode="HTML")
        await callback.answer()
        raise CancelHandler()

    async def scenario_add(callback):
        await allowed(callback)
        fn = getattr(app, "add_scenario_start", None)
        if not fn:
            await callback.answer("⚠️ افزودن سناریو در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        state = await app.dp.current_state(user=callback.from_user.id, chat=callback.message.chat.id)
        await fn(callback, state)
        raise CancelHandler()

    async def scenario_remove(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            await callback.message.edit_text(
                "⚠️ هیچ سناریویی ثبت نشده است.", reply_markup=_scenario_keyboard()
            )
            await callback.answer()
            raise CancelHandler()
        if len(scenarios) == 1:
            await callback.answer("⚠️ حداقل یک سناریو باید باقی بماند.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(scenarios.keys()):
            kb.add(InlineKeyboardButton(str(name), callback_data=f"private_scenario:delete:{i}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="private:scenarios"))
        await callback.message.edit_text("سناریوی موردنظر را برای حذف انتخاب کنید:", reply_markup=kb)
        await callback.answer()
        raise CancelHandler()

    async def scenario_delete(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        try:
            index = int(str(callback.data).rsplit(":", 1)[1])
            name = list(scenarios.keys())[index]
        except Exception:
            await callback.answer("⚠️ سناریو نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if len(scenarios) <= 1:
            await callback.answer("⚠️ حداقل یک سناریو باید باقی بماند.", show_alert=True)
            raise CancelHandler()
        if getattr(app, "lobby_active", False) or getattr(app, "game_running", False):
            await callback.answer("⛔ هنگام فعال بودن بازی/لابی حذف سناریو مجاز نیست.", show_alert=True)
            raise CancelHandler()
        scenarios.pop(name, None)
        saver = getattr(app, "save_scenarios", None)
        if saver:
            saver()
        if getattr(app, "selected_scenario", None) == name:
            app.selected_scenario = None
        await callback.message.edit_text(
            f"✅ سناریو «{html.escape(str(name))}» حذف شد.",
            reply_markup=_scenario_keyboard(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_edit(callback):
        await allowed(callback)
        fn = getattr(app, "edit_scenario_start", None) or getattr(app, "edit_scenario", None)
        if fn:
            state = await app.dp.current_state(user=callback.from_user.id, chat=callback.message.chat.id)
            await fn(callback, state)
        else:
            await callback.answer("⚠️ ویرایش سناریو در runtime فعال نیست.", show_alert=True)
        raise CancelHandler()

    async def addons_back(callback):
        if not _private(callback):
            raise CancelHandler()
        await allowed(callback)
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=_keyboard_start(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def lazy_final_private_ui(callback):
        """Install final_private_ui during webhook handling and run its exact handler."""
        if not _private(callback):
            raise CancelHandler()
        from runtime import final_private_ui
        if not getattr(app, "_final_private_ui_installed", False):
            await final_private_ui.install(app)

        current_registry = getattr(
            getattr(app.dp, "callback_query_handlers", None), "handlers", []
        )
        for item in list(current_registry):
            fn = _handler(item)
            if fn is None or fn is lazy_final_private_ui:
                continue
            if getattr(fn, "__module__", "") != "runtime.final_private_ui":
                continue
            try:
                result = await item.check_filters(callback)
            except TypeError:
                result = await item.check_filters(callback=callback)
            if isinstance(result, tuple):
                matched, data = result
            else:
                matched, data = bool(result), {}
            if matched:
                await fn(callback, **(data or {}))
                raise CancelHandler()

        await callback.answer("⚠️ این گزینه در نسخه فعلی ثبت نشده است.", show_alert=True)
        raise CancelHandler()

    regs = [
        (start, lambda c: c.data in {"private:start", "final:start"}),
        (management, lambda c: c.data == "manage_game"),
        (scenarios, lambda c: c.data in {"private:scenarios", "final:scenarios", "manage_scenarios", "change_scenario"}),
        (scenario_list, lambda c: c.data == "private_scenario:list"),
        (scenario_add, lambda c: c.data == "private_scenario:add"),
        (scenario_remove, lambda c: c.data == "private_scenario:remove"),
        (scenario_delete, lambda c: str(c.data or "").startswith("private_scenario:delete:")),
        (scenario_edit, lambda c: c.data == "private_scenario:edit"),
        (addons_back, lambda c: c.data == "addons:back"),
        (lazy_final_private_ui, lambda c: str(c.data or "").startswith("finalgm:")),
    ]
    for fn, filt in regs:
        app.dp.register_callback_query_handler(fn, filt, state="*")

    # aiogram 2.x exposes HandlerObj.callback; some compatibility layers expose
    # HandlerObj.handler. Support both when moving bootstrap handlers to front.
    owned = [h for h in list(registry) if getattr(_handler(h), "__module__", "") == __name__]
    others = [h for h in list(registry) if h not in owned]
    registry[:] = owned + others
    app._private_ui_bootstrap_installed = True
    logging.info("Private UI bootstrap installed before async startup: handlers=%d", len(registry))
    return True
