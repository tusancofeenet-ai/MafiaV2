from __future__ import annotations

import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _registry(main):
    return getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", [])


def _capture_render(registry):
    for item in registry:
        cb = getattr(item, "callback", None)
        if getattr(cb, "__name__", "") == "scenario":
            for cell in getattr(cb, "__closure__", None) or ():
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if callable(value) and getattr(value, "__name__", "") == "render":
                    return value
    return None


def _remove_names(main, names):
    reg = _registry(main)
    reg[:] = [item for item in reg if getattr(getattr(item, "callback", None), "__name__", "") not in names]


def _find_scenarios(main, predicate):
    return [(i, str(name), cfg or {}) for i, (name, cfg) in enumerate((main.scenarios or {}).items()) if predicate(str(name), cfg or {})]


def install(main):
    if getattr(main, "_lobby_ui_v8_installed", False):
        return False
    main._lobby_ui_v8_installed = True
    registry = _registry(main)
    render = _capture_render(registry)
    _remove_names(main, {"new", "scenario", "moderator", "change_s"})

    def catalog_keyboard():
        kb = InlineKeyboardMarkup(row_width=3)
        popular = [
            ("👑 پدرخوانده", "father"),
            ("🎭 کلاسیک", "classic"),
            ("🎩 دن", "don"),
            ("🎲 قمارباز", "gambler"),
            ("☢️ زودیاک", "zodiac"),
        ]
        for text, key in popular:
            kb.insert(InlineKeyboardButton(text, callback_data=f"lv8_cat:{key}"))
        kb.add(InlineKeyboardButton("📚 سایر سناریوها", callback_data="lv8_cat:other"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lv6_home"))
        return kb

    def category_rows(key):
        if key == "father":
            return _find_scenarios(main, lambda n, c: n.startswith("پدرخوانده-"))
        if key == "classic":
            return _find_scenarios(main, lambda n, c: n.startswith("کلاسیک "))
        if key == "don":
            return _find_scenarios(main, lambda n, c: "دن مافیا" in [str(x) for x in (c.get("roles") or [])] or n == "کاپو")
        if key == "gambler":
            return _find_scenarios(main, lambda n, c: n in {"قمار باز", "قمارباز"})
        if key == "zodiac":
            return _find_scenarios(main, lambda n, c: n == "زودیاک")
        grouped = {i for group in ("father", "classic", "don", "gambler", "zodiac") for i, _, _ in category_rows(group)}
        return _find_scenarios(main, lambda n, c: n not in {"پدرخوانده-جک", "پدرخوانده-شرلوک", "پدرخوانده-نوسترا", "کلاسیک 12", "کلاسیک 13", "قمار باز", "قمارباز", "زودیاک", "کاپو"})

    def scenario_keyboard(key):
        rows = category_rows(key)
        kb = InlineKeyboardMarkup(row_width=3)
        for index, name, cfg in rows:
            roles = len(cfg.get("roles") or [])
            label = name
            if key == "father":
                label = name.replace("پدرخوانده-", "")
            elif key == "classic":
                label = name.replace("کلاسیک ", "") + " نفره"
            elif key == "don" and name == "کاپو":
                label = "کاپو"
            kb.insert(InlineKeyboardButton(f"{label} ({roles})", callback_data=f"lv8_s:{index}"))
        kb.row(InlineKeyboardButton("⬅️ سناریوهای محبوب", callback_data="lv8_catalog"))
        return kb

    async def show_catalog(callback):
        await callback.message.edit_text(
            "📝 <b>انتخاب سناریو</b>\n\n⭐ سناریوهای محبوب را انتخاب کنید:",
            parse_mode="HTML", reply_markup=catalog_keyboard(),
        )
        await callback.answer()

    async def new(callback):
        group_id = int(callback.message.chat.id)
        if getattr(main, "game_running", False) or getattr(main, "round_active", False):
            await callback.answer("⚠️ بازی در حال اجراست.", show_alert=True)
            return
        try:
            if getattr(main, "runtime", None) is not None:
                main.runtime.lobby.ensure(group_id)
        except Exception:
            logging.exception("lobby ensure failed")
        main.group_chat_id = group_id
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        main._lv6_setup = True
        main._lv6_change_scenario = False
        await show_catalog(callback)

    async def change_s(callback):
        group_id = int(callback.message.chat.id)
        try:
            admins = {int(a.user.id) for a in await main.bot.get_chat_administrators(group_id)}
        except Exception:
            admins = set()
        if int(callback.from_user.id) not in admins:
            await callback.answer("⛔ فقط مدیران.", show_alert=True)
            return
        main._lv6_change_scenario = True
        await show_catalog(callback)

    async def category(callback):
        key = str(callback.data).split(":", 1)[1]
        rows = category_rows(key)
        if not rows:
            await callback.answer("⚠️ سناریویی در این دسته وجود ندارد.", show_alert=True)
            return
        titles = {"father": "👑 <b>پدرخوانده</b>", "classic": "🎭 <b>کلاسیک</b>", "don": "🎩 <b>دن</b>", "gambler": "🎲 <b>قمارباز</b>", "zodiac": "☢️ <b>زودیاک</b>", "other": "📚 <b>سایر سناریوها</b>"}
        await callback.message.edit_text(
            f"{titles.get(key, '📝 <b>سناریوها</b>')}\n\nنسخه موردنظر را انتخاب کنید:",
            parse_mode="HTML", reply_markup=scenario_keyboard(key),
        )
        await callback.answer()

    async def scenario(callback):
        try:
            index = int(str(callback.data).split(":", 1)[1])
            selected = list(main.scenarios)[index]
        except Exception:
            await callback.answer("❌ سناریو نامعتبر است.", show_alert=True)
            return
        group_id = int(callback.message.chat.id)
        try:
            rt = getattr(main, "runtime", None)
            if rt is not None:
                rt.lobby.set_scenario(group_id, selected)
        except Exception:
            logging.exception("scenario persistence failed")
            await callback.answer("❌ ذخیره سناریو انجام نشد.", show_alert=True)
            return
        main.selected_scenario = selected
        main.MAX_SEATS = len((main.scenarios.get(selected) or {}).get("roles") or [])
        if getattr(main, "_lv6_change_scenario", False) and getattr(main, "moderator_id", None):
            main._lv6_change_scenario = False
            main._lv6_setup = False
            main.lobby_active = True
            if render:
                await render(callback.message)
            else:
                await callback.message.edit_text(f"✅ سناریو «{html.escape(selected)}» تغییر کرد.", parse_mode="HTML")
            await callback.answer("✅ سناریو تغییر کرد")
            return
        main._lv6_change_scenario = False
        admins = await main.bot.get_chat_administrators(group_id)
        kb = InlineKeyboardMarkup(row_width=3)
        for admin in admins:
            kb.insert(InlineKeyboardButton(admin.user.full_name[:24], callback_data=f"lv8_m:{int(admin.user.id)}"))
        kb.row(InlineKeyboardButton("⬅️ بازگشت به سناریوها", callback_data="lv8_catalog"))
        await callback.message.edit_text(
            f"📝 <b>{html.escape(selected)}</b>\n\n🎩 <b>انتخاب گرداننده</b>",
            parse_mode="HTML", reply_markup=kb,
        )
        await callback.answer("✅ سناریو انتخاب شد")

    async def moderator(callback):
        group_id = int(callback.message.chat.id)
        uid = int(str(callback.data).split(":", 1)[1])
        try:
            admins = {int(a.user.id) for a in await main.bot.get_chat_administrators(group_id)}
        except Exception:
            admins = set()
        if uid not in admins:
            await callback.answer("❌ گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        rt = getattr(main, "runtime", None)
        if rt is not None:
            rt.lobby.set_moderator(group_id, uid)
        main.moderator_id = uid
        main.group_chat_id = group_id
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        main._lv6_setup = False
        main._lv6_change_scenario = False
        if render:
            await render(callback.message)
        else:
            await callback.message.edit_text("✅ لابی آماده شد.")
        await callback.answer("✅ لابی اصلی ایجاد شد")

    async def manage(callback):
        group_id = int(callback.message.chat.id)
        try:
            admins = {int(a.user.id) for a in await main.bot.get_chat_administrators(group_id)}
        except Exception:
            admins = set()
        if int(callback.from_user.id) not in admins:
            await callback.answer("⛔ فقط مدیران.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=3)
        for text, data in [
            ("📝 سناریو", "lv6_change_s"), ("🎩 گرداننده", "lv6_change_m"), ("⚔️ چالش", "lv6_challenge"),
            ("🗑 حذف بازیکن", "lv6_remove"), ("📢 حاضری", "lv6_ready"), ("🚫 لغو بازی", "lv6_cancel"),
        ]:
            kb.insert(InlineKeyboardButton(text, callback_data=data))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="lv6_back_lobby"))
        await callback.message.edit_text("⚙️ <b>مدیریت بازی</b>", parse_mode="HTML", reply_markup=kb)
        await callback.answer()

    # Remove old handlers that own the same callback_data.
    _remove_names(main, {"new", "scenario", "moderator", "change_s", "manage"})

    handlers = [
        (new, lambda c: c.data == "lv6_new"),
        (show_catalog, lambda c: c.data == "lv8_catalog"),
        (category, lambda c: str(c.data).startswith("lv8_cat:")),
        (scenario, lambda c: str(c.data).startswith("lv8_s:")),
        (moderator, lambda c: str(c.data).startswith("lv8_m:")),
        (change_s, lambda c: c.data == "lv6_change_s"),
        (manage, lambda c: c.data == "lv6_manage"),
    ]
    for fn, flt in handlers:
        main.dp.register_callback_query_handler(fn, flt, state="*")
        reg = _registry(main)
        for i, item in enumerate(reg):
            if getattr(item, "callback", None) is fn:
                reg.insert(0, reg.pop(i))
                break
    logging.info("LOBBY_UI_V8 active: grouped scenarios and compact management menus")
    return True
