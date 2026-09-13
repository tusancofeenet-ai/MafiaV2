from __future__ import annotations

import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    dp, bot = main.dp, main.bot
    original_main_menu_keyboard = main.main_menu_keyboard

    def front(fn):
        handlers = getattr(dp.callback_query_handlers, "handlers", [])
        for i, h in enumerate(handlers):
            if getattr(h, "callback", None) is fn:
                handlers.insert(0, handlers.pop(i))
                return

    def active_game():
        try:
            return main.persistent_runtime.state.active_game(int(main.group_chat_id))
        except Exception:
            return None

    def snapshot():
        game = active_game()
        if not game:
            return {"players": [], "seats": {}, "waiting": []}
        try:
            return main.persistent_runtime.state.lobby.snapshot(game["id"])
        except Exception:
            return {"players": [], "seats": {}, "waiting": []}

    def name(uid, fallback=None):
        try:
            return main.display_name(int(uid), fallback) or fallback or str(uid)
        except Exception:
            return fallback or str(uid)

    def mention(uid, fallback=None):
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(name(uid, fallback))}</b></a>'

    async def edit(message, text, markup=None):
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
        except Exception as exc:
            logging.warning("lobby message edit failed: %s", exc)
        return message.message_id

    def scenario_kb():
        kb = InlineKeyboardMarkup(row_width=1)
        for i, (scenario, cfg) in enumerate(main.scenarios.items()):
            cfg = cfg or {}
            roles = cfg.get("roles") or []
            minimum = int(cfg.get("min_players") or 1)
            kb.add(InlineKeyboardButton(f"📝 {scenario} ({minimum}-{len(roles)})", callback_data=f"lv5_scenario:{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lv5_back_main"))
        return kb

    async def moderator_kb():
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in await bot.get_chat_administrators(main.group_chat_id):
            kb.add(InlineKeyboardButton(name(admin.user.id, admin.user.full_name), callback_data=f"lv5_moderator:{admin.user.id}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به سناریو", callback_data="lv5_back_scenario"))
        return kb

    def main_menu():
        # Reuse the original menu so راهنما and every legitimate existing item remain.
        # Only لیست جدید is removed and بازی جدید is redirected to the unified flow.
        try:
            original = original_main_menu_keyboard()
        except Exception:
            original = InlineKeyboardMarkup()
        out = InlineKeyboardMarkup(row_width=2)
        found_new = False
        for row in getattr(original, "inline_keyboard", []):
            new_row = []
            for button in row:
                text = str(getattr(button, "text", ""))
                if "لیست جدید" in text:
                    continue
                if "بازی جدید" in text:
                    new_row.append(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv5_new_game"))
                    found_new = True
                else:
                    new_row.append(button)
            if new_row:
                out.row(*new_row)
        if not found_new:
            out.add(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv5_new_game"))
        return out

    def lobby_text():
        game = active_game() or {}
        scenario = main.selected_scenario or game.get("scenario_id") or "---"
        moderator = main.moderator_id or game.get("moderator_id")
        rows = snapshot().get("players", [])
        players = [r for r in rows if not r.get("is_substitute")]
        reserve = [r for r in rows if r.get("is_substitute")]
        max_seats = int(main.MAX_SEATS or len((main.scenarios.get(scenario) or {}).get("roles", [])))
        lines = ["🎮 <b>لابی Mafia Nights</b>", "", f"📝 سناریو: <b>{html.escape(str(scenario))}</b>", f"🎩 گرداننده: {mention(moderator) if moderator else '---'}", f"👥 بازیکنان: <b>{len(players)}/{max_seats}</b>", "", "📋 <b>بازیکنان داخل بازی</b>"]
        if players:
            for row in sorted(players, key=lambda r: (r.get("seat") is None, r.get("seat") or 999)):
                seat = row.get("seat")
                label = mention(row["player_id"], row.get("first_name") or row.get("username"))
                lines.append(f"{seat:02d}. {label}" if seat is not None else f"▫️ {label} — بدون صندلی")
        else:
            lines.append("— هنوز بازیکنی وارد نشده است.")
        if reserve:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for i, row in enumerate(reserve, 1):
                lines.append(f"{i}. {mention(row['player_id'], row.get('first_name') or row.get('username'))}")
        return "\n".join(lines)

    def lobby_kb():
        rows = snapshot().get("players", [])
        players = [r for r in rows if not r.get("is_substitute")]
        max_seats = int(main.MAX_SEATS or 0)
        full = max_seats > 0 and len(players) >= max_seats and all(r.get("seat") is not None for r in players)
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton("🎮 ورود / خروج از بازی", callback_data="lv5_toggle_player"))
        kb.add(InlineKeyboardButton("💺 انتخاب صندلی", callback_data="lv5_choose_seat"))
        if full:
            kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="lv5_toggle_reserve"))
            kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="lv5_manage"))
        return kb

    async def render_lobby(message):
        await edit(message, lobby_text(), lobby_kb())
        main.lobby_message_id = message.message_id

    async def new_game(c):
        if c.message.chat.type not in ("group", "supergroup"):
            await c.answer("این گزینه باید داخل گروه اجرا شود.", show_alert=True)
            return
        if active_game():
            await c.answer("⚠️ یک بازی فعال وجود دارد؛ ابتدا آن را لغو کنید.", show_alert=True)
            return
        main.group_chat_id = c.message.chat.id
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        main.selected_scenario = None
        main.moderator_id = None
        main.MAX_SEATS = 0
        main.players.clear()
        main.player_slots.clear()
        main.waiting_list.clear()
        main._lv5_setup = True
        await edit(c.message, "📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.", scenario_kb())
        await c.answer()

    async def scenario(c):
        try:
            index = int(c.data.split(":", 1)[1])
            selected = list(main.scenarios.keys())[index]
            cfg = main.scenarios[selected] or {}
        except Exception:
            await c.answer("⚠️ سناریو نامعتبر است.", show_alert=True)
            return
        main.selected_scenario = selected
        main.MAX_SEATS = len(cfg.get("roles") or [])
        await edit(c.message, f"📝 سناریو: <b>{html.escape(selected)}</b>\n\n🎩 <b>انتخاب گرداننده</b>", await moderator_kb())
        await c.answer("✅ سناریو انتخاب شد")

    async def moderator(c):
        try:
            uid = int(c.data.split(":", 1)[1])
        except Exception:
            await c.answer("⚠️ گرداننده نامعتبر است.", show_alert=True)
            return
        admins = {m.user.id for m in await bot.get_chat_administrators(main.group_chat_id)}
        if uid not in admins:
            await c.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        main.moderator_id = uid
        try:
            main.addons.register(moderator_id=uid, group_id=main.group_chat_id)
        except Exception:
            pass
        try:
            main.persistent_runtime.lobby.ensure(main.group_chat_id, uid, main.selected_scenario)
            main.persistent_runtime.lobby.set_scenario(main.group_chat_id, main.selected_scenario)
            main.persistent_runtime.lobby.set_moderator(main.group_chat_id, uid)
        except Exception:
            logging.exception("lobby creation failed after moderator selection")
            await c.answer("❌ ایجاد لابی انجام نشد.", show_alert=True)
            return
        main._lv5_setup = False
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        await render_lobby(c.message)
        await c.answer("✅ لابی ایجاد شد")

    async def back_main(c):
        main._lv5_setup = False
        main.lobby_active = False
        await edit(c.message, "🎮 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید.", main_menu())
        await c.answer()

    async def back_scenario(c):
        main._lv5_setup = True
        await edit(c.message, "📝 <b>انتخاب سناریو</b>", scenario_kb())
        await c.answer()

    async def toggle_player(c):
        uid = c.from_user.id
        game = active_game()
        if not game or main.game_running or main.round_active:
            await c.answer("⚠️ لابی فعال نیست.", show_alert=True)
            return
        rows = snapshot().get("players", [])
        active = [r for r in rows if not r.get("is_substitute")]
        current = next((r for r in active if int(r["player_id"]) == uid), None)
        if current:
            seat = current.get("seat")
            main.persistent_runtime.leave(main.group_chat_id, uid)
            main.players.pop(uid, None)
            if seat is not None:
                main.player_slots.pop(seat, None)
            await render_lobby(c.message)
            await c.answer("🚪 از بازی خارج شدید")
            return
        if any(int(r["player_id"]) == uid and r.get("is_substitute") for r in rows):
            await c.answer("🎟 شما در رزرو هستید؛ از دکمه رزرو برای لغو رزرو استفاده کنید.", show_alert=True)
            return
        if len(active) >= int(main.MAX_SEATS or 0):
            await c.answer("🎟 ظرفیت اصلی پر است؛ رزرو را انتخاب کنید.", show_alert=True)
            return
        main.persistent_runtime.join(main.group_chat_id, uid, None, main.moderator_id, main.selected_scenario, substitute=False)
        main.players[uid] = name(uid, c.from_user.full_name)
        await render_lobby(c.message)
        await c.answer("✅ وارد بازی شدید")

    async def choose_seat(c):
        uid = c.from_user.id
        rows = snapshot().get("players", [])
        if not any(int(r["player_id"]) == uid and not r.get("is_substitute") for r in rows):
            await c.answer("ابتدا وارد بازی شوید.", show_alert=True)
            return
        occupied = {r.get("seat"): int(r["player_id"]) for r in rows if not r.get("is_substitute") and r.get("seat") is not None}
        kb = InlineKeyboardMarkup(row_width=3)
        for seat in range(1, int(main.MAX_SEATS or 0) + 1):
            owner = occupied.get(seat)
            kb.insert(InlineKeyboardButton(f"{seat:02d} " + ("✅" if owner == uid else ("🔒" if owner else "⬜")), callback_data=f"lv5_seat:{seat}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="lv5_back_lobby"))
        await edit(c.message, "💺 <b>انتخاب صندلی</b>\n\nیک صندلی آزاد انتخاب کنید.", kb)
        await c.answer()

    async def seat(c):
        uid = c.from_user.id
        try:
            seat_no = int(c.data.split(":", 1)[1])
        except Exception:
            await c.answer("صندلی نامعتبر است.", show_alert=True)
            return
        rows = snapshot().get("players", [])
        if not any(int(r["player_id"]) == uid and not r.get("is_substitute") for r in rows):
            await c.answer("ابتدا وارد بازی شوید.", show_alert=True)
            return
        if any(r.get("seat") == seat_no and int(r["player_id"]) != uid for r in rows if not r.get("is_substitute")):
            await c.answer("این صندلی قبلاً گرفته شده است.", show_alert=True)
            return
        try:
            main.persistent_runtime.lobby.assign_seat(main.group_chat_id, uid, seat_no)
        except Exception:
            await c.answer("❌ انتخاب صندلی انجام نشد.", show_alert=True)
            return
        await render_lobby(c.message)
        await c.answer(f"✅ صندلی {seat_no} انتخاب شد")

    async def reserve(c):
        uid = c.from_user.id
        rows = snapshot().get("players", [])
        players = [r for r in rows if not r.get("is_substitute")]
        max_seats = int(main.MAX_SEATS or 0)
        if len(players) < max_seats or not all(r.get("seat") is not None for r in players):
            await c.answer("رزرو فقط پس از تکمیل لیست و صندلی‌ها فعال است.", show_alert=True)
            return
        existing = next((r for r in rows if int(r["player_id"]) == uid and r.get("is_substitute")), None)
        game = active_game()
        if existing:
            main.persistent_runtime.state.games.remove_player(game["id"], uid)
            await render_lobby(c.message)
            await c.answer("❌ رزرو لغو شد")
            return
        if any(int(r["player_id"]) == uid for r in players):
            await c.answer("شما در لیست اصلی هستید.", show_alert=True)
            return
        main.persistent_runtime.join(main.group_chat_id, uid, None, main.moderator_id, main.selected_scenario, substitute=True)
        await render_lobby(c.message)
        await c.answer("🎟 به لیست رزرو اضافه شدید")

    async def back_lobby(c):
        await render_lobby(c.message)
        await c.answer()

    async def manage(c):
        admins = {m.user.id for m in await bot.get_chat_administrators(main.group_chat_id)}
        if c.from_user.id not in admins:
            await c.answer("⛔ این بخش فقط مخصوص مدیران گروه است.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🚫 لغو بازی", callback_data="lv5_cancel"))
        kb.add(InlineKeyboardButton("📝 تغییر سناریو", callback_data="lv5_change_scenario"))
        kb.add(InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="lv5_change_moderator"))
        kb.add(InlineKeyboardButton(f"⚔️ چالش: {'فعال' if getattr(main, 'challenge_active', True) else 'غیرفعال'}", callback_data="lv5_toggle_challenge"))
        kb.add(InlineKeyboardButton("🗑 حذف بازیکن", callback_data="lv5_remove_menu"))
        kb.add(InlineKeyboardButton("📢 حاضری", callback_data="lv5_ready"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="lv5_back_lobby"))
        await edit(c.message, "⚙️ <b>مدیریت بازی</b>", kb)
        await c.answer()

    async def cancel(c):
        admins = {m.user.id for m in await bot.get_chat_administrators(main.group_chat_id)}
        if c.from_user.id != main.moderator_id and c.from_user.id not in admins:
            await c.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        game = active_game()
        if game:
            for row in list(main.persistent_runtime.state.games.list_players(game["id"])):
                main.persistent_runtime.state.games.remove_player(game["id"], row["player_id"])
            main.persistent_runtime.state.games.update_game(game["id"], status="cancelled", state={})
        main.players.clear(); main.player_slots.clear(); main.waiting_list.clear()
        main.lobby_active = False; main.game_running = False; main.round_active = False
        main.selected_scenario = None; main.moderator_id = None; main.MAX_SEATS = 0
        await edit(c.message, "🚫 <b>بازی لغو شد.</b>\n\nهمه داده‌های بازی پاک شد.", main_menu())
        await c.answer("بازی لغو شد")

    async def change_scenario(c):
        main._lv5_setup = True
        await edit(c.message, "📝 <b>تغییر سناریو</b>", scenario_kb())
        await c.answer()

    async def change_moderator(c):
        main._lv5_setup = False
        await edit(c.message, "🎩 <b>تغییر گرداننده</b>", await moderator_kb())
        await c.answer()

    async def toggle_challenge(c):
        main.challenge_active = not getattr(main, "challenge_active", True)
        await manage(c)

    handlers = [
        (new_game, lambda c: c.data == "lv5_new_game"),
        (scenario, lambda c: str(c.data or "").startswith("lv5_scenario:")),
        (moderator, lambda c: str(c.data or "").startswith("lv5_moderator:")),
        (back_main, lambda c: c.data == "lv5_back_main"),
        (back_scenario, lambda c: c.data == "lv5_back_scenario"),
        (toggle_player, lambda c: c.data == "lv5_toggle_player"),
        (choose_seat, lambda c: c.data == "lv5_choose_seat"),
        (seat, lambda c: str(c.data or "").startswith("lv5_seat:")),
        (reserve, lambda c: c.data == "lv5_toggle_reserve"),
        (back_lobby, lambda c: c.data == "lv5_back_lobby"),
        (manage, lambda c: c.data == "lv5_manage"),
        (cancel, lambda c: c.data == "lv5_cancel"),
        (change_scenario, lambda c: c.data == "lv5_change_scenario"),
        (change_moderator, lambda c: c.data == "lv5_change_moderator"),
        (toggle_challenge, lambda c: c.data == "lv5_toggle_challenge"),
    ]
    for fn, flt in handlers:
        dp.register_callback_query_handler(fn, flt)
        front(fn)

    main.main_menu_keyboard = main_menu
    logging.info("Single authoritative lobby UI v5 installed")
