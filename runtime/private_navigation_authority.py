"""Single import-time private navigation authority for the webhook runtime.

This module is intentionally the last private-router layer installed by
player_runtime_entry.  It owns top-level navigation and scenario CRUD, while
final_private_ui owns the detailed game-management actions behind finalgm:*.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.handler import CancelHandler
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class EditScenario(StatesGroup):
    waiting_for_roles = State()
    waiting_for_min_players = State()


def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", [])
    if getattr(app, "_private_navigation_authority_installed", False):
        return False

    def handler_fn(item):
        return getattr(item, "handler", None) or getattr(item, "callback", None)

    def private(item):
        return bool(getattr(item, "message", None) and item.message.chat.type == "private")

    async def allowed(c):
        if not private(c):
            raise CancelHandler()
        uid = int(c.from_user.id)
        if uid == int(getattr(app, "moderator_id", 0) or 0):
            return True
        cached = set()
        for obj in (app, getattr(app, "addons", None)):
            for key in ("admins", "group_admins"):
                for x in getattr(obj, key, None) or []:
                    try:
                        cached.add(int(getattr(getattr(x, "user", None), "id", x)))
                    except (TypeError, ValueError):
                        pass
        if uid in cached:
            return True
        # Never use a mutable runtime group_chat_id here: private requests can
        # arrive on workers that have not seen the game group yet.
        gid = getattr(app, "ALLOWED_GROUP_ID", None)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(int(gid))
                ids = {int(a.user.id) for a in admins}
                app.admins = ids
                app.group_admins = list(ids)
                if uid in ids:
                    return True
            except Exception:
                logging.warning("private navigation: configured-group admin lookup failed", exc_info=True)
        await c.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    def start_kb():
        from runtime.final_private_ui import start_keyboard
        return start_keyboard()

    def scenario_kb():
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("➕ افزودن سناریو", callback_data="private_scenario:add"),
            InlineKeyboardButton("➖ حذف سناریو", callback_data="private_scenario:remove"),
            InlineKeyboardButton("✏️ ویرایش سناریو", callback_data="private_scenario:edit"),
            InlineKeyboardButton("📋 لیست سناریوها", callback_data="private_scenario:list"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="private:start"),
        )
        return kb

    async def edit_here(message, text, kb):
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception as exc:
            if exc.__class__.__name__ != "MessageNotModified":
                raise

    async def go_start(c):
        if not private(c):
            raise CancelHandler()
        await edit_here(c.message, "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", start_kb())
        await c.answer()
        raise CancelHandler()

    async def manage_game(c):
        await allowed(c)
        from runtime.final_private_ui import management_keyboard, management_report
        await edit_here(c.message, management_report(app), management_keyboard())
        await c.answer()
        raise CancelHandler()

    async def manage_game_back(c):
        await allowed(c)
        # final_private_ui historically reused finalgm:back for both the root
        # management screen and its submenus. Resolve it from the current
        # message so both old keyboards remain functional: root -> main,
        # submenu -> management root.
        current = (getattr(c.message, "text", None) or "").strip()
        if current.startswith("🛠 <b>مدیریت بازی</b>"):
            await edit_here(c.message, "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", start_kb())
        else:
            from runtime.final_private_ui import management_keyboard, management_report
            await edit_here(c.message, management_report(app), management_keyboard())
        await c.answer()
        raise CancelHandler()

    async def scenarios(c):
        await allowed(c)
        await edit_here(c.message, "⚙️ <b>مدیریت سناریو</b>\n\nیک گزینه را انتخاب کنید:", scenario_kb())
        await c.answer()
        raise CancelHandler()

    async def scenario_list(c):
        await allowed(c)
        scenarios = getattr(app, "scenarios", {}) or {}
        lines = ["📋 <b>لیست سناریوها</b>", ""]
        if scenarios:
            lines += [f"{i}. {html.escape(str(name))}" for i, name in enumerate(scenarios, 1)]
        else:
            lines.append("هیچ سناریویی ثبت نشده است.")
        await edit_here(c.message, "\n".join(lines), scenario_kb())
        await c.answer()
        raise CancelHandler()

    async def scenario_add(c):
        await allowed(c)
        fn = getattr(app, "add_scenario_start", None)
        if not fn:
            await c.answer("⚠️ افزودن سناریو در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        state = await dp.current_state(user=c.from_user.id, chat=c.message.chat.id)
        await fn(c, state)
        await c.answer()
        raise CancelHandler()

    async def scenario_remove(c):
        await allowed(c)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            await edit_here(c.message, "⚠️ هیچ سناریویی ثبت نشده است.", scenario_kb())
            await c.answer(); raise CancelHandler()
        if len(scenarios) == 1:
            await c.answer("⚠️ حداقل یک سناریو باید باقی بماند.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(scenarios):
            kb.add(InlineKeyboardButton(str(name), callback_data=f"private_scenario:delete:{i}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="final:scenarios"))
        await edit_here(c.message, "سناریوی موردنظر را برای حذف انتخاب کنید:", kb)
        await c.answer(); raise CancelHandler()

    async def scenario_delete(c):
        await allowed(c)
        scenarios = getattr(app, "scenarios", {}) or {}
        try:
            idx = int(str(c.data).rsplit(":", 1)[1])
            name = list(scenarios)[idx]
        except Exception:
            await c.answer("⚠️ سناریو نامعتبر است.", show_alert=True); raise CancelHandler()
        if len(scenarios) <= 1:
            await c.answer("⚠️ حداقل یک سناریو باید باقی بماند.", show_alert=True); raise CancelHandler()
        if getattr(app, "lobby_active", False) or getattr(app, "game_running", False):
            await c.answer("⛔ هنگام فعال بودن بازی/لابی حذف سناریو مجاز نیست.", show_alert=True); raise CancelHandler()
        scenarios.pop(name, None)
        saver = getattr(app, "save_scenarios", None)
        if saver:
            saver()
        if getattr(app, "selected_scenario", None) == name:
            app.selected_scenario = None
        await edit_here(c.message, f"✅ سناریو «{html.escape(str(name))}» حذف شد.", scenario_kb())
        await c.answer(); raise CancelHandler()

    async def scenario_edit(c):
        await allowed(c)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            await c.answer("⚠️ هیچ سناریویی برای ویرایش وجود ندارد.", show_alert=True); raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(scenarios):
            kb.add(InlineKeyboardButton(str(name), callback_data=f"private_scenario:edit:{i}"))
        kb.add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="final:scenarios"))
        await edit_here(c.message, "سناریوی موردنظر را برای ویرایش انتخاب کنید:", kb)
        await c.answer(); raise CancelHandler()

    async def scenario_edit_pick(c):
        await allowed(c)
        scenarios = getattr(app, "scenarios", {}) or {}
        try:
            idx = int(str(c.data).rsplit(":", 1)[1])
            name = list(scenarios)[idx]
            value = scenarios[name] if isinstance(scenarios[name], dict) else {}
            roles = value.get("roles") or []
        except Exception:
            await c.answer("⚠️ سناریوی نامعتبر.", show_alert=True); raise CancelHandler()
        state = await dp.current_state(user=c.from_user.id, chat=c.message.chat.id)
        await state.update_data(edit_scenario_name=name)
        await state.set_state(EditScenario.waiting_for_roles)
        await c.message.answer(
            f"✏️ ویرایش «{html.escape(str(name))}»\n\n"
            "نقش‌های جدید را با کاما جدا کنید.\n"
            f"نقش‌های فعلی: {html.escape(', '.join(map(str, roles)))}"
        )
        await c.answer(); raise CancelHandler()

    async def edit_roles(message, state):
        roles = [x.strip() for x in (message.text or "").split(",") if x.strip()]
        if not roles:
            await message.answer("⚠️ حداقل یک نقش وارد کنید."); return
        await state.update_data(edit_roles=roles)
        await message.answer("🔢 حداقل تعداد بازیکنان را وارد کنید:")
        await state.set_state(EditScenario.waiting_for_min_players)

    async def edit_min(message, state):
        raw = (message.text or "").strip()
        if not raw.isdigit() or int(raw) < 1:
            await message.answer("⚠️ یک عدد معتبر بزرگ‌تر از صفر وارد کنید."); return
        data = await state.get_data(); name = data.get("edit_scenario_name"); roles = data.get("edit_roles") or []
        scenarios = getattr(app, "scenarios", {}) or {}
        if name not in scenarios:
            await message.answer("⚠️ سناریوی موردنظر دیگر وجود ندارد."); await state.finish(); return
        minimum = int(raw)
        current = scenarios.get(name) if isinstance(scenarios.get(name), dict) else {}
        scenarios[name] = {**current, "roles": roles, "min_players": minimum, "max_players": len(roles)}
        saver = getattr(app, "save_scenarios", None)
        ok = True if not saver else bool(saver())
        suffix = "" if ok else "\n⚠️ ذخیره دائمی ناموفق بود؛ تغییر در این worker اعمال شد."
        await message.answer(
            f"✅ سناریو «{html.escape(str(name))}» ویرایش شد.\n\n"
            f"👥 نقش‌ها: {html.escape(', '.join(roles))}\n"
            f"🔢 بازیکنان: {minimum} تا {len(roles)}{suffix}"
        )
        await state.finish()

    async def addons_back(c):
        await go_start(c)

    async def dispatch_final(c):
        if not private(c):
            raise CancelHandler()
        from runtime import final_private_ui
        await final_private_ui.install(app)
        own = [h for h in list(cq) if handler_fn(h) in OWN]
        try:
            for h in own:
                if h in cq: cq.remove(h)
            await dp.callback_query_handlers.notify(c)
        finally:
            for h in own:
                if h not in cq: cq.insert(0, h)
        raise CancelHandler()

    OWN = {scenarios, go_start, manage_game, manage_game_back, addons_back, scenario_list,
           scenario_add, scenario_remove, scenario_delete, scenario_edit, scenario_edit_pick,
           dispatch_final}

    regs = [
        (go_start, lambda c: c.data in {"private:start", "final:start"}),
        (manage_game, lambda c: c.data == "manage_game"),
        (manage_game_back, lambda c: c.data == "finalgm:back"),
        (scenarios, lambda c: c.data in {"final:scenarios", "private:scenarios", "manage_scenarios", "change_scenario"}),
        (scenario_list, lambda c: c.data == "private_scenario:list"),
        (scenario_add, lambda c: c.data in {"private_scenario:add", "final:scenario:add"}),
        (scenario_remove, lambda c: c.data in {"private_scenario:remove", "final:scenario:remove"}),
        (scenario_delete, lambda c: str(c.data or "").startswith(("private_scenario:delete:", "final:scenario:delete:"))),
        (scenario_edit, lambda c: c.data == "private_scenario:edit"),
        (scenario_edit_pick, lambda c: str(c.data or "").startswith("private_scenario:edit:")),
        (addons_back, lambda c: c.data == "addons:back"),
        (dispatch_final, lambda c: str(c.data or "").startswith("finalgm:") and c.data != "finalgm:back"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")

    dp.register_message_handler(edit_roles, state=EditScenario.waiting_for_roles)
    dp.register_message_handler(edit_min, state=EditScenario.waiting_for_min_players)

    async def group_start(message):
        if message.chat.type not in ("group", "supergroup"):
            return
        app.group_chat_id = int(message.chat.id)
        try:
            kb = app.main_menu_keyboard()
        except Exception:
            kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game"))
        await message.answer("🎭 <b>Mafia Nights</b>\n\nبرای شروع بازی از دکمه زیر استفاده کنید:", reply_markup=kb, parse_mode="HTML")
        raise CancelHandler()

    dp.register_message_handler(group_start, commands=["start"], state="*")

    # Promote only this authority. Do not run another private reordering layer
    # after this function; that was the source of several route reversions.
    for i in range(len(cq) - 1, -1, -1):
        if handler_fn(cq[i]) in OWN:
            cq.insert(0, cq.pop(i))
    for i in range(len(mh) - 1, -1, -1):
        if handler_fn(mh[i]) is group_start:
            mh.insert(0, mh.pop(i))

    app._private_navigation_authority_installed = True
    logging.info("PRIVATE NAVIGATION AUTHORITY: installed callbacks=%d messages=%d", len(cq), len(mh))
    return True
