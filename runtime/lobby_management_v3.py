from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _front(dp, fn):
    hs = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if not isinstance(hs, list): return
    for i, h in enumerate(hs):
        if getattr(h, "callback", None) is fn:
            hs.insert(0, hs.pop(i)); return


def _rows(main):
    game = main.persistent_runtime.state.active_game(int(main.group_chat_id))
    return main.persistent_runtime.state.games.list_players(game["id"]) if game else []


def _lobby_text(main, rows):
    active = [r for r in rows if not r.get("is_substitute")]
    reserved = [r for r in rows if r.get("is_substitute")]
    max_seats = len((main.scenarios.get(main.selected_scenario) or {}).get("roles", []))
    def name(uid):
        return main.display_name(int(uid), str(uid))
    lines = ["🎮 <b>لابی مافیا</b>", "", f"📝 سناریو: <b>{main.selected_scenario}</b>", f"🎩 گرداننده: <b>{name(main.moderator_id) if main.moderator_id else '---'}</b>", f"👥 بازیکنان: <b>{len(active)}/{max_seats}</b>", "", "<b>لیست بازیکنان:</b>"]
    lines += [f"{r.get('seat') or '—'}. <a href=\"tg://user?id={int(r['player_id'])}\"><b>{name(r['player_id'])}</b></a>" for r in active]
    if not active: lines.append("— هنوز بازیکنی وارد نشده است.")
    if reserved:
        lines += ["", "<b>🎟 لیست رزرو:</b>"] + [f"{i}. <a href=\"tg://user?id={int(r['player_id'])}\"><b>{name(r['player_id'])}</b></a>" for i, r in enumerate(reserved, 1)]
    return "\n".join(lines)


def _lobby_kb(main, rows):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("✅ ورود به بازی", callback_data="v3_join"), InlineKeyboardButton("🚪 خروج از بازی", callback_data="v3_leave"))
    max_seats = len((main.scenarios.get(main.selected_scenario) or {}).get("roles", []))
    active = [r for r in rows if not r.get("is_substitute")]
    for seat in range(1, max_seats + 1):
        row = next((r for r in active if r.get("seat") == seat), None)
        kb.add(InlineKeyboardButton(f"🔴 {seat}: {main.display_name(row['player_id'], str(row['player_id']))}" if row else f"⬜ صندلی {seat}", callback_data=f"v3_seat_info_{seat}" if row else f"v3_seat_{seat}"))
    if len(active) >= max_seats:
        kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="v3_reserve"))
        if all(r.get("seat") is not None for r in active): kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="v3_distribute_roles"))
    kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="v3_manage"))
    return kb


def install(main):
    dp = main.dp

    async def manage_scenario(c: types.CallbackQuery):
        if not await _admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(main.scenarios.keys()): kb.add(InlineKeyboardButton(str(name), callback_data=f"v3_manage_scen_{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_manage")); await c.answer(); await c.message.edit_text("📝 سناریوی جدید را انتخاب کنید:", reply_markup=kb)

    async def set_scenario(c: types.CallbackQuery):
        if not await _admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try: name = list(main.scenarios.keys())[int(str(c.data).removeprefix("v3_manage_scen_"))]
        except Exception: await c.answer("⚠️ سناریو نامعتبر است.", show_alert=True); return
        rows = _rows(main); max_seats = len((main.scenarios.get(name) or {}).get("roles", [])); active = [r for r in rows if not r.get("is_substitute")]
        if len(active) > max_seats: await c.answer("⚠️ تعداد بازیکنان فعلی از ظرفیت این سناریو بیشتر است.", show_alert=True); return
        main.selected_scenario = name; main.MAX_SEATS = max_seats
        game = main.persistent_runtime.state.active_game(int(main.group_chat_id)); main.persistent_runtime.state.games.update_game(game["id"], scenario_id=name)
        await c.answer("✅ سناریو تغییر کرد"); rows = _rows(main); await c.message.edit_text(_lobby_text(main, rows), parse_mode="HTML", reply_markup=_lobby_kb(main, rows))

    async def manage_mod(c: types.CallbackQuery):
        if not await _admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        await main.update_group_admins(main.bot, main.group_chat_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for uid in getattr(main, "group_admins", []) or []: kb.add(InlineKeyboardButton(main.display_name(uid, str(uid)), callback_data=f"v3_manage_mod_{uid}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_manage")); await c.answer(); await c.message.edit_text("🎩 گرداننده جدید را انتخاب کنید:", reply_markup=kb)

    async def set_mod(c: types.CallbackQuery):
        if not await _admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try: uid = int(str(c.data).removeprefix("v3_manage_mod_"))
        except ValueError: await c.answer("⚠️ نامعتبر", show_alert=True); return
        main.moderator_id = uid; game = main.persistent_runtime.state.active_game(int(main.group_chat_id)); main.persistent_runtime.state.games.update_game(game["id"], moderator_id=uid)
        await c.answer("✅ گرداننده تغییر کرد"); rows = _rows(main); await c.message.edit_text(_lobby_text(main, rows), parse_mode="HTML", reply_markup=_lobby_kb(main, rows))

    async def _admin(main, c):
        if c.from_user.id == getattr(main, "moderator_id", None): return True
        try: return (await main.bot.get_chat_member(main.group_chat_id, c.from_user.id)).status in {"administrator", "creator"}
        except Exception: return False

    for fn, filt in [
        (manage_scenario, lambda c: c.data == "v3_manage_scenario"),
        (set_scenario, lambda c: str(c.data or "").startswith("v3_manage_scen_")),
        (manage_mod, lambda c: c.data == "v3_manage_mod"),
        (set_mod, lambda c: str(c.data or "").startswith("v3_manage_mod_")),
    ]:
        dp.register_callback_query_handler(fn, filt); _front(dp, fn)
