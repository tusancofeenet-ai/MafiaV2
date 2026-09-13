from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    async def is_admin(callback):
        gid = int(callback.message.chat.id)
        try:
            return int(callback.from_user.id) in {int(a.user.id) for a in await main.bot.get_chat_administrators(gid)}
        except Exception:
            return False

    async def challenge(callback):
        if not await is_admin(callback) and int(callback.from_user.id) != int(getattr(main, "moderator_id", 0) or 0):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        gid = int(callback.message.chat.id)
        game = None
        try:
            game = main.runtime.state.active_game(gid)
        except Exception:
            pass
        enabled = bool(getattr(main, "challenge_active", True))
        show = bool((game or {}).get("state", {}).get("challenge_settings", {}).get("show_player_status", True))
        kb = InlineKeyboardMarkup(row_width=2)
        kb.row(
            InlineKeyboardButton("🟢 چالش: روشن" if enabled else "🔴 چالش: خاموش", callback_data="lv6_challenge_toggle"),
            InlineKeyboardButton("🤏 وضعیت: روشن" if show else "🚫 وضعیت: خاموش", callback_data="lv6_challenge_visibility"),
        )
        kb.row(InlineKeyboardButton("⬅️ مدیریت", callback_data="lv6_manage"), InlineKeyboardButton("🔄 بروزرسانی", callback_data="lv6_challenge"))
        await callback.message.edit_text(
            f"⚔️ <b>وضعیت چالش</b>\n\nچالش: <b>{'فعال' if enabled else 'غیرفعال'}</b>\nنمایش 🤏 کنار نام: <b>{'فعال' if show else 'غیرفعال'}</b>",
            parse_mode="HTML", reply_markup=kb,
        )
        await callback.answer()

    async def challenge_toggle(callback):
        if not await is_admin(callback) and int(callback.from_user.id) != int(getattr(main, "moderator_id", 0) or 0):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        main.challenge_active = not bool(getattr(main, "challenge_active", True))
        await challenge(callback)

    async def visibility(callback):
        if not await is_admin(callback) and int(callback.from_user.id) != int(getattr(main, "moderator_id", 0) or 0):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        gid = int(callback.message.chat.id)
        game = main.runtime.state.active_game(gid)
        if not game:
            await callback.answer("⛔ بازی فعال نیست.", show_alert=True)
            return
        state = dict(game.get("state") or {})
        settings = dict(state.get("challenge_settings") or {})
        settings["show_player_status"] = not bool(settings.get("show_player_status", True))
        state["challenge_settings"] = settings
        main.runtime.state.games.update_game(game["id"], state=state)
        await challenge(callback)

    for data, fn in (("lv6_challenge", challenge), ("lv6_challenge_toggle", challenge_toggle), ("lv6_challenge_visibility", visibility)):
        main.dp.register_callback_query_handler(fn, lambda c, d=data: c.data == d, state="*")
        reg = getattr(main.dp.callback_query_handlers, "handlers", [])
        for i, item in enumerate(reg):
            if getattr(item, "callback", None) is fn:
                reg.insert(0, reg.pop(i))
                break
    return True
