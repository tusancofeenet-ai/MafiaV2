from __future__ import annotations

import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    """Route legacy lobby callback_data into the authoritative v6 flow.

    Old group messages can survive deployments. Their callback_data must not
    be allowed to enter main1's legacy lobby handlers, otherwise users can see
    the old scenario/moderator menu again. These handlers are intentionally
    registered last and moved to the front of aiogram's callback handler list.
    """
    dp, bot = main.dp, main.bot

    def front(fn):
        handlers = getattr(dp.callback_query_handlers, "handlers", [])
        for i, h in enumerate(handlers):
            if getattr(h, "callback", None) is fn:
                handlers.insert(0, handlers.pop(i))
                return

    def scenario_keyboard():
        kb = InlineKeyboardMarkup(row_width=1)
        for i, (name, cfg) in enumerate(main.scenarios.items()):
            cfg = cfg or {}
            roles = cfg.get("roles") or []
            kb.add(InlineKeyboardButton(
                f"📝 {name} ({cfg.get('min_players', 1)}-{len(roles)})",
                callback_data=f"lv6_s:{i}",
            ))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lv6_home"))
        return kb

    async def admins_keyboard(back="lv6_back_s"):
        kb = InlineKeyboardMarkup(row_width=1)
        try:
            admins = await bot.get_chat_administrators(main.group_chat_id)
        except Exception:
            admins = []
        for admin in admins:
            kb.add(InlineKeyboardButton(
                admin.user.full_name,
                callback_data=f"lv6_m:{admin.user.id}",
            ))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به سناریو", callback_data=back))
        return kb

    def mention(uid):
        if not uid:
            return "---"
        try:
            name = main.display_name(uid, main.players.get(uid)) or str(uid)
        except Exception:
            name = main.players.get(uid) or str(uid)
        return f'<a href="tg://user?id={uid}"><b>{html.escape(str(name))}</b></a>'

    async def edit(message, text, kb):
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return True
        except Exception as exc:
            logging.warning("legacy lobby bridge edit failed: %s", exc)
            return False

    def lobby_text():
        cfg = main.scenarios.get(main.selected_scenario) or {}
        capacity = len(cfg.get("roles") or [])
        active = [u for u in main.players if u not in main.waiting_list]
        waiting = [u for u in main.waiting_list if u in main.players]
        lines = [
            "🎮 <b>لابی Mafia Nights</b>", "",
            f"📝 سناریو: <b>{html.escape(str(main.selected_scenario or '---'))}</b>",
            f"🎩 گرداننده: {mention(main.moderator_id) if main.moderator_id else '---'}",
            f"👥 بازیکنان: <b>{len(active)}/{capacity}</b>", "",
            "📋 <b>بازیکنان داخل بازی</b>",
        ]
        if active:
            for uid in sorted(active, key=lambda x: next((s for s, p in main.player_slots.items() if p == x), 999)):
                seat = next((s for s, p in main.player_slots.items() if p == uid), None)
                lines.append(f"{seat:02d}. {mention(uid)}" if seat else f"▫️ {mention(uid)} — بدون صندلی")
        else:
            lines.append("— هنوز بازیکنی وارد نشده است.")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            lines += [f"{i}. {mention(uid)}" for i, uid in enumerate(waiting, 1)]
        return "\n".join(lines)

    def lobby_keyboard():
        cfg = main.scenarios.get(main.selected_scenario) or {}
        capacity = len(cfg.get("roles") or [])
        active = [u for u in main.players if u not in main.waiting_list]
        full = capacity > 0 and len(active) >= capacity and all(
            any(p == uid and seat is not None for seat, p in main.player_slots.items())
            for uid in active
        )
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton("🎮 ورود / خروج از بازی", callback_data="lv6_toggle"))
        kb.add(InlineKeyboardButton("💺 انتخاب صندلی", callback_data="lv6_seat_menu"))
        if full:
            kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="lv6_reserve"))
            kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="lv6_manage"))
        return kb

    async def legacy_new(callback):
        main.group_chat_id = callback.message.chat.id
        if main.game_running or main.round_active:
            await callback.answer("⚠️ بازی در حال اجراست.", show_alert=True)
            return
        main.lobby_active = True
        main.selected_scenario = None
        main.moderator_id = None
        main.MAX_SEATS = 0
        main.players.clear()
        main.player_slots.clear()
        main.waiting_list.clear()
        if hasattr(main, "_lv6_ready_players"):
            main._lv6_ready_players.clear()
        main._lv6_setup = True
        main._lv6_change_scenario = False
        await edit(callback.message, "📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.", scenario_keyboard())
        await callback.answer("✅")

    async def legacy_choose_scenario(callback):
        # Old button from an already-sent message.
        main.group_chat_id = callback.message.chat.id
        main.lobby_active = True
        await edit(callback.message, "📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.", scenario_keyboard())
        await callback.answer("✅")

    async def legacy_scenario(callback):
        name = str(callback.data).replace("scenario_", "", 1)
        if name not in main.scenarios:
            await callback.answer("سناریو نامعتبر است.", show_alert=True)
            return
        main.group_chat_id = callback.message.chat.id
        main.selected_scenario = name
        main.MAX_SEATS = len((main.scenarios[name] or {}).get("roles") or [])
        main.lobby_active = True
        main._lv6_setup = True
        main._lv6_change_scenario = False
        await edit(
            callback.message,
            f"📝 سناریو: <b>{html.escape(name)}</b>\n\n🎩 <b>انتخاب گرداننده</b>",
            await admins_keyboard(),
        )
        await callback.answer("✅ سناریو انتخاب شد")

    async def legacy_choose_moderator(callback):
        main.group_chat_id = callback.message.chat.id
        if not main.lobby_active:
            main.lobby_active = True
        await edit(callback.message, "🎩 <b>انتخاب گرداننده</b>", await admins_keyboard())
        await callback.answer("✅")

    async def legacy_moderator(callback):
        try:
            uid = int(str(callback.data).replace("moderator_", "", 1))
        except Exception:
            await callback.answer("گرداننده نامعتبر است.", show_alert=True)
            return
        try:
            admin_ids = {a.user.id for a in await bot.get_chat_administrators(callback.message.chat.id)}
        except Exception:
            admin_ids = set()
        if uid not in admin_ids:
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        main.group_chat_id = callback.message.chat.id
        main.moderator_id = uid
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        main._lv6_setup = False
        main._lv6_change_scenario = False
        main.players.clear()
        main.player_slots.clear()
        main.waiting_list.clear()
        if hasattr(main, "_lv6_ready_players"):
            main._lv6_ready_players.clear()
        await edit(callback.message, lobby_text(), lobby_keyboard())
        main.lobby_message_id = callback.message.message_id
        await callback.answer("✅ لابی ایجاد شد")

    handlers = [
        (legacy_new, lambda c: c.data == "new_game"),
        (legacy_choose_scenario, lambda c: c.data == "choose_scenario"),
        (legacy_scenario, lambda c: str(c.data).startswith("scenario_")),
        (legacy_choose_moderator, lambda c: c.data == "choose_moderator"),
        (legacy_moderator, lambda c: str(c.data).startswith("moderator_")),
    ]
    for fn, flt in handlers:
        dp.register_callback_query_handler(fn, flt)
        front(fn)
