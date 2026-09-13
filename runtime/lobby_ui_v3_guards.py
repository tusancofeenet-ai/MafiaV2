from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _front(dp, fn):
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if not isinstance(handlers, list):
        return
    for i, handler in enumerate(handlers):
        if getattr(handler, "callback", None) is fn:
            handlers.insert(0, handlers.pop(i))
            return


def install(main):
    dp = main.dp

    async def scenario_menu(c: types.CallbackQuery):
        kb = InlineKeyboardMarkup(row_width=1)
        for i, name in enumerate(main.scenarios.keys()):
            kb.add(InlineKeyboardButton(str(name), callback_data=f"v3_scenario_{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="back_main"))
        await c.answer()
        await c.message.edit_text("📝 <b>انتخاب سناریو</b>", parse_mode="HTML", reply_markup=kb)

    async def moderator_menu(c: types.CallbackQuery):
        await c.answer()
        await main.update_group_admins(main.bot, main.group_chat_id)
        kb = InlineKeyboardMarkup(row_width=1)
        for uid in getattr(main, "group_admins", []) or []:
            kb.add(InlineKeyboardButton(main.display_name(uid, str(uid)), callback_data=f"v3_moderator_{uid}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_scenario_menu"))
        await c.message.edit_text("🎩 <b>انتخاب گرداننده</b>", parse_mode="HTML", reply_markup=kb)

    async def remove_menu(c: types.CallbackQuery):
        if c.from_user.id != getattr(main, "moderator_id", None):
            try:
                member = await main.bot.get_chat_member(main.group_chat_id, c.from_user.id)
                if member.status not in {"administrator", "creator"}:
                    await c.answer("⛔ فقط مدیران گروه یا گرداننده.", show_alert=True)
                    return
            except Exception:
                await c.answer("⛔ دسترسی ندارید.", show_alert=True)
                return
        kb = InlineKeyboardMarkup(row_width=1)
        game = main.persistent_runtime.state.active_game(int(main.group_chat_id))
        if game:
            for r in main.persistent_runtime.state.games.list_players(game["id"]):
                if not r.get("is_substitute"):
                    kb.add(InlineKeyboardButton(main.display_name(r["player_id"], str(r["player_id"])), callback_data=f"v3_remove_{r['player_id']}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_manage"))
        await c.answer()
        await c.message.edit_text("🗑 بازیکن را انتخاب کنید:", reply_markup=kb)

    dp.register_callback_query_handler(scenario_menu, lambda c: c.data == "v3_scenario_menu")
    dp.register_callback_query_handler(moderator_menu, lambda c: c.data == "v3_moderator_menu")
    dp.register_callback_query_handler(remove_menu, lambda c: c.data == "v3_remove_player")
    _front(dp, scenario_menu)
    _front(dp, moderator_menu)
    _front(dp, remove_menu)
