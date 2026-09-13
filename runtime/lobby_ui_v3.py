from __future__ import annotations

import html
import logging
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _front(dp, fn):
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if not isinstance(handlers, list):
        return
    for i, h in enumerate(handlers):
        if getattr(h, "callback", None) is fn:
            handlers.insert(0, handlers.pop(i))
            return


def _name(main, uid, fallback=None):
    try:
        return main.display_name(int(uid), fallback) or fallback or str(uid)
    except Exception:
        return fallback or str(uid)


def _mention(main, uid, fallback=None):
    return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(_name(main, uid, fallback))}</b></a>'


def _game(main):
    try:
        return main.persistent_runtime.state.active_game(int(main.group_chat_id))
    except Exception:
        return None


def _rows(main):
    game = _game(main)
    if not game:
        return []
    try:
        return main.persistent_runtime.state.games.list_players(game["id"])
    except Exception:
        return []


def _sync(main):
    rows = _rows(main)
    main.player_slots.clear()
    main.players.clear()
    main.players_in_game.setdefault(main.group_chat_id, {}).clear()
    for r in rows:
        uid = int(r["player_id"])
        name = _name(main, uid, r.get("first_name") or r.get("username") or r.get("nickname"))
        main.players[uid] = name
        if not r.get("is_substitute") and r.get("seat") is not None:
            seat = int(r["seat"])
            main.player_slots[seat] = uid
            main.players_in_game.setdefault(main.group_chat_id, {})[seat] = {"id": uid, "name": name, "role": r.get("role")}


def _max_seats(main):
    try:
        return len(main.scenarios[main.selected_scenario]["roles"])
    except Exception:
        return int(getattr(main, "MAX_SEATS", 0) or 0)


def _scenario_keyboard(main, back="lobby_config"):
    kb = InlineKeyboardMarkup(row_width=1)
    for i, name in enumerate(main.scenarios.keys()):
        kb.add(InlineKeyboardButton(str(name), callback_data=f"v3_scenario_{i}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=back))
    return kb


def _moderator_keyboard(main, back="v3_scenario_menu"):
    kb = InlineKeyboardMarkup(row_width=1)
    admins = getattr(main, "group_admins", []) or []
    for uid in admins:
        kb.add(InlineKeyboardButton(_name(main, uid), callback_data=f"v3_moderator_{uid}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=back))
    return kb


def _config_keyboard(main):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(f"📝 سناریو: {main.selected_scenario or 'انتخاب نشده'}", callback_data="v3_scenario_menu"))
    kb.add(InlineKeyboardButton(f"🎩 گرداننده: {_name(main, main.moderator_id) if main.moderator_id else 'انتخاب نشده'}", callback_data="v3_moderator_menu"))
    if main.selected_scenario and main.moderator_id:
        kb.add(InlineKeyboardButton("🚀 ایجاد بازی", callback_data="v3_create_game"))
    return kb


def _lobby_keyboard(main, rows):
    kb = InlineKeyboardMarkup(row_width=2)
    active = [r for r in rows if not r.get("is_substitute")]
    reserved = [r for r in rows if r.get("is_substitute")]
    max_seats = _max_seats(main)
    uid = None

    kb.add(InlineKeyboardButton("✅ ورود به بازی", callback_data="v3_join"),
           InlineKeyboardButton("🚪 خروج از بازی", callback_data="v3_leave"))

    for seat in range(1, max_seats + 1):
        row = next((r for r in active if r.get("seat") == seat), None)
        if row:
            kb.add(InlineKeyboardButton(f"🔴 {seat}: {_name(main, row['player_id'])}", callback_data=f"v3_seat_info_{seat}"))
        else:
            kb.add(InlineKeyboardButton(f"⬜ صندلی {seat}", callback_data=f"v3_seat_{seat}"))

    if len(active) >= max_seats:
        kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="v3_reserve"))
        if active and all(r.get("seat") is not None for r in active):
            kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="v3_distribute_roles"))
    elif reserved:
        kb.add(InlineKeyboardButton("🎟 لیست رزرو", callback_data="v3_reserve_list"))

    kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="v3_manage"))
    return kb


def _lobby_text(main, rows):
    active = [r for r in rows if not r.get("is_substitute")]
    reserved = [r for r in rows if r.get("is_substitute")]
    max_seats = _max_seats(main)
    lines = [
        "🎮 <b>لابی مافیا</b>",
        "",
        f"📝 سناریو: <b>{html.escape(str(main.selected_scenario or '---'))}</b>",
        f"🎩 گرداننده: {_mention(main, main.moderator_id) if main.moderator_id else '---'}",
        f"👥 بازیکنان: <b>{len(active)}/{max_seats}</b>",
        "",
        "<b>لیست بازیکنان:</b>",
    ]
    if active:
        for r in active:
            seat = r.get("seat")
            seat_text = str(seat) if seat is not None else "—"
            lines.append(f"{seat_text}. {_mention(main, r['player_id'])}")
    else:
        lines.append("— هنوز بازیکنی وارد نشده است.")
    if reserved:
        lines += ["", "<b>🎟 لیست رزرو:</b>"]
        for i, r in enumerate(reserved, 1):
            lines.append(f"{i}. {_mention(main, r['player_id'])}")
    if len(active) == max_seats and all(r.get("seat") is not None for r in active):
        lines += ["", "✅ ظرفیت و صندلی‌ها کامل است؛ پخش نقش فعال شد."]
    return "\n".join(lines)


async def _edit(c, text, markup):
    try:
        await c.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        try:
            await c.message.edit_reply_markup(reply_markup=markup)
        except Exception:
            pass


async def _is_admin(main, c):
    if c.from_user.id == getattr(main, "moderator_id", None):
        return True
    try:
        m = await main.bot.get_chat_member(main.group_chat_id, c.from_user.id)
        return m.status in {"administrator", "creator"}
    except Exception:
        return False


def install(main):
    dp = main.dp
    bot = main.bot

    # Correct the old helper: the number of seats is the number of roles, not
    # the number of keys in the scenario dictionary.
    def set_max_seats(scenario_name):
        main.MAX_SEATS = len((main.scenarios.get(scenario_name) or {}).get("roles", []))
    main.set_max_seats_from_scenario = set_max_seats

    async def new_game(c: types.CallbackQuery):
        await c.answer()
        main.group_chat_id = c.message.chat.id
        active = _game(main)
        if active:
            await c.answer("⚠️ ابتدا بازی فعال را لغو کنید.", show_alert=True); return
        main.selected_scenario = None
        main.moderator_id = None
        main.MAX_SEATS = 0
        await _edit(c, "🎮 <b>بازی جدید</b>\n\nمرحله ۱ از ۳: سناریو را انتخاب کنید.", _scenario_keyboard(main, "back_main"))

    async def scenario_menu(c: types.CallbackQuery):
        await c.answer(); await _edit(c, "📝 <b>انتخاب سناریو</b>", _scenario_keyboard(main, "back_main"))

    async def scenario(c: types.CallbackQuery):
        try:
            i = int(str(c.data).removeprefix("v3_scenario_")); name = list(main.scenarios.keys())[i]
        except Exception:
            await c.answer("⚠️ سناریو نامعتبر است.", show_alert=True); return
        main.selected_scenario = name; set_max_seats(name)
        await c.answer("✅ سناریو انتخاب شد")
        await _edit(c, f"📝 سناریو: <b>{html.escape(name)}</b>\n\nمرحله ۲ از ۳: گرداننده را انتخاب کنید.", _moderator_keyboard(main))

    async def moderator_menu(c: types.CallbackQuery):
        await c.answer()
        if not main.selected_scenario:
            await c.answer("⚠️ ابتدا سناریو را انتخاب کنید.", show_alert=True); return
        await main.update_group_admins(bot, main.group_chat_id)
        await _edit(c, "🎩 <b>انتخاب گرداننده</b>", _moderator_keyboard(main))

    async def moderator(c: types.CallbackQuery):
        try: uid = int(str(c.data).removeprefix("v3_moderator_"))
        except ValueError: await c.answer("⚠️ گرداننده نامعتبر است.", show_alert=True); return
        main.moderator_id = uid
        await c.answer("✅ گرداننده انتخاب شد")
        await _edit(c, "⚙️ <b>تنظیمات بازی کامل شد</b>\n\nسناریو و گرداننده انتخاب شده‌اند.\nبرای ورود به لابی «ایجاد بازی» را بزنید.", _config_keyboard(main))

    async def create_game(c: types.CallbackQuery):
        if not main.selected_scenario or not main.moderator_id:
            await c.answer("⚠️ سناریو و گرداننده را انتخاب کنید.", show_alert=True); return
        if _game(main):
            await c.answer("⚠️ بازی فعال دیگری وجود دارد.", show_alert=True); return
        try:
            main.persistent_runtime.state.ensure_lobby(main.group_chat_id, main.moderator_id, main.selected_scenario)
            main.lobby_active = True; main.game_running = False; main.round_active = False
            _sync(main); rows = _rows(main)
            main.lobby_message_id = c.message.message_id; main.game_message_id = c.message.message_id
            await c.answer("✅ لابی ایجاد شد")
            await _edit(c, _lobby_text(main, rows), _lobby_keyboard(main, rows))
        except Exception:
            logging.exception("v3 lobby creation failed"); await c.answer("❌ ایجاد لابی ناموفق بود.", show_alert=True)

    async def join(c: types.CallbackQuery):
        game = _game(main)
        if not game: await c.answer("⚠️ لابی فعال نیست.", show_alert=True); return
        rows = _rows(main); uid = c.from_user.id
        active = [r for r in rows if not r.get("is_substitute")]
        if any(int(r["player_id"]) == uid for r in rows):
            await c.answer("ℹ️ شما از قبل در یکی از لیست‌ها هستید.", show_alert=True); return
        if len(active) >= _max_seats(main):
            await c.answer("🎟 ظرفیت اصلی پر است؛ از رزرو استفاده کنید.", show_alert=True); return
        try:
            main.persistent_runtime.join(main.group_chat_id, uid, None, main.moderator_id, main.selected_scenario, is_substitute=False)
            await c.answer("✅ وارد بازی شدید")
            _sync(main); rows = _rows(main); await _edit(c, _lobby_text(main, rows), _lobby_keyboard(main, rows))
        except Exception as e: await c.answer(str(e), show_alert=True)

    async def leave(c: types.CallbackQuery):
        game = _game(main)
        if not game: await c.answer("⚠️ لابی فعال نیست.", show_alert=True); return
        uid = c.from_user.id; rows = _rows(main)
        row = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not row: await c.answer("ℹ️ شما در بازی نیستید.", show_alert=True); return
        was_main = not row.get("is_substitute"); seat = row.get("seat")
        main.persistent_runtime.state.games.remove_player(game["id"], uid)
        promoted = None
        if was_main and seat is not None:
            promoted = main.persistent_runtime.state.games.promote_waiting_player(game["id"], seat)
        await c.answer("✅ از بازی خارج شدید")
        if promoted:
            await bot.send_message(main.group_chat_id, f"🔄 {_mention(main, promoted['player_id'])} از لیست رزرو وارد بازی شد.")
        _sync(main); rows = _rows(main); await _edit(c, _lobby_text(main, rows), _lobby_keyboard(main, rows))

    async def reserve(c: types.CallbackQuery):
        game = _game(main)
        if not game: await c.answer("⚠️ لابی فعال نیست.", show_alert=True); return
        uid = c.from_user.id; rows = _rows(main)
        row = next((r for r in rows if int(r["player_id"]) == uid), None)
        if row and row.get("is_substitute"):
            main.persistent_runtime.state.games.remove_player(game["id"], uid)
            await c.answer("❌ رزرو شما لغو شد")
        elif row:
            await c.answer("ℹ️ شما داخل بازی هستید.", show_alert=True); return
        else:
            active = [r for r in rows if not r.get("is_substitute")]
            if len(active) < _max_seats(main): await c.answer("⚠️ هنوز ظرفیت اصلی پر نشده است.", show_alert=True); return
            main.persistent_runtime.join(main.group_chat_id, uid, None, main.moderator_id, main.selected_scenario, is_substitute=True)
            await c.answer("🎟 به لیست رزرو اضافه شدید")
        _sync(main); rows = _rows(main); await _edit(c, _lobby_text(main, rows), _lobby_keyboard(main, rows))

    async def seat(c: types.CallbackQuery):
        try: seat_no = int(str(c.data).removeprefix("v3_seat_"))
        except ValueError: await c.answer("⚠️ صندلی نامعتبر است.", show_alert=True); return
        game = _game(main); uid = c.from_user.id; rows = _rows(main)
        player = next((r for r in rows if int(r["player_id"]) == uid and not r.get("is_substitute")), None)
        occupied = next((r for r in rows if r.get("seat") == seat_no and not r.get("is_substitute")), None)
        if not player: await c.answer("⚠️ ابتدا وارد بازی شوید.", show_alert=True); return
        if occupied and int(occupied["player_id"]) != uid: await c.answer("❌ این صندلی گرفته شده است.", show_alert=True); return
        try:
            main.persistent_runtime.state.games.set_player_seat(game["id"], uid, seat_no)
            await c.answer(f"💺 صندلی {seat_no} ثبت شد"); _sync(main); rows = _rows(main); await _edit(c, _lobby_text(main, rows), _lobby_keyboard(main, rows))
        except Exception as e: await c.answer(str(e), show_alert=True)

    async def reserve_list(c: types.CallbackQuery):
        rows = [r for r in _rows(main) if r.get("is_substitute")]
        text = "🎟 <b>لیست رزرو</b>\n\n" + ("\n".join(f"{i}. {_mention(main, r['player_id'])}" for i, r in enumerate(rows, 1)) if rows else "لیست رزرو خالی است.")
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data="v3_lobby_back"))
        await c.answer(); await _edit(c, text, kb)

    async def manage(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ فقط مدیران گروه یا گرداننده.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=2)
        kb.add(InlineKeyboardButton("🚫 لغو بازی", callback_data="cancel_game"), InlineKeyboardButton("📝 تغییر سناریو", callback_data="v3_manage_scenario"))
        kb.add(InlineKeyboardButton("🎩 تغییر گرداننده", callback_data="v3_manage_mod"), InlineKeyboardButton(f"⚔️ چالش: {'فعال' if main.challenge_active else 'غیرفعال'}", callback_data="v3_toggle_challenge"))
        kb.add(InlineKeyboardButton("🗑 حذف بازیکن", callback_data="v3_remove_player"), InlineKeyboardButton("📣 حاضری", callback_data="v3_attendance"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_lobby_back"))
        await c.answer(); await _edit(c, "⚙️ <b>مدیریت بازی</b>", kb)

    async def toggle_challenge(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        main.challenge_active = not main.challenge_active; await c.answer("✅ تنظیم شد"); await manage(c)

    async def remove_player(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1)
        for r in _rows(main):
            if not r.get("is_substitute"): kb.add(InlineKeyboardButton(_name(main, r["player_id"]), callback_data=f"v3_remove_{r['player_id']}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_manage")); await c.answer(); await _edit(c, "🗑 بازیکن را انتخاب کنید:", kb)

    async def remove(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        try: uid = int(str(c.data).removeprefix("v3_remove_"))
        except ValueError: await c.answer("⚠️ نامعتبر", show_alert=True); return
        game = _game(main); rows = _rows(main); row = next((r for r in rows if int(r["player_id"]) == uid), None)
        if not row: await c.answer("بازیکن پیدا نشد.", show_alert=True); return
        seat = row.get("seat"); main.persistent_runtime.state.games.remove_player(game["id"], uid)
        if seat is not None: main.persistent_runtime.state.games.promote_waiting_player(game["id"], seat)
        await c.answer("✅ حذف شد"); _sync(main); rows = _rows(main); await _edit(c, _lobby_text(main, rows), _lobby_keyboard(main, rows))

    async def attendance(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        game = _game(main); ready = set((game or {}).get("state", {}).get("ready", [])); rows = [r for r in _rows(main) if not r.get("is_substitute")]
        text = "📣 <b>حاضری بازیکنان</b>\n\n" + "\n".join(("✅" if int(r["player_id"]) in ready else "⬜") + " " + _mention(main, r["player_id"]) for r in rows)
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🙋 آماده‌ام", callback_data="v3_ready"), InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_manage"))
        await c.answer(); await _edit(c, text, kb)

    async def ready(c: types.CallbackQuery):
        game = _game(main); uid = c.from_user.id; rows = _rows(main)
        if not any(int(r["player_id"]) == uid and not r.get("is_substitute") for r in rows): await c.answer("⛔ فقط بازیکنان داخل بازی.", show_alert=True); return
        state = dict(game.get("state") or {}); ready_ids = set(state.get("ready", [])); ready_ids.add(uid); state["ready"] = list(ready_ids)
        main.persistent_runtime.state.games.update_game(game["id"], state=state); await c.answer("✅ حاضری ثبت شد"); await attendance(c)

    async def distribute(c: types.CallbackQuery):
        if c.from_user.id != main.moderator_id: await c.answer("❌ فقط گرداننده.", show_alert=True); return
        _sync(main); rows = _rows(main); active = [r for r in rows if not r.get("is_substitute")]
        if len(active) != _max_seats(main) or not all(r.get("seat") is not None for r in active): await c.answer("⚠️ ظرفیت و صندلی‌ها باید کامل باشد.", show_alert=True); return
        try:
            mapping = await main.distribute_roles(); main.last_role_map = mapping
            game = _game(main); state = dict(game.get("state") or {}); state["roles"] = {str(k): v for k, v in mapping.items()}
            main.persistent_runtime.state.games.update_game(game["id"], status="running", state=state, started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
            main.game_running = True; main.round_active = False
            players_list = "\n".join(f"{int(r['seat']):02d}. {_mention(main, r['player_id'])}" for r in sorted(active, key=lambda x: x['seat']))
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("👑 انتخاب سردست", callback_data="choose_head"))
            kb.add(InlineKeyboardButton("⚔️ وضعیت چالش", callback_data="v3_challenge_status"))
            kb.add(InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"))
            text = "🎭 <b>نقش‌ها پخش شد!</b>\n\n" + players_list + "\n\n🔐 نقش هر بازیکن در پیوی ارسال شد."
            await c.answer("✅ نقش‌ها پخش شد")
            await _edit(c, text, kb)
        except Exception:
            logging.exception("role distribution failed"); await c.answer("❌ خطا در پخش نقش‌ها.", show_alert=True)

    async def challenge_status(c: types.CallbackQuery):
        if not await _is_admin(main, c): await c.answer("⛔ دسترسی ندارید.", show_alert=True); return
        status = "فعال" if main.challenge_active else "غیرفعال"
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("🔄 تغییر وضعیت", callback_data="v3_toggle_challenge"), InlineKeyboardButton("⬅️ بازگشت", callback_data="v3_start_back"))
        await c.answer(); await _edit(c, f"⚔️ <b>وضعیت چالش</b>\n\nوضعیت فعلی: <b>{status}</b>", kb)

    async def start_back(c):
        kb = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("👑 انتخاب سردست", callback_data="choose_head"), InlineKeyboardButton("⚔️ وضعیت چالش", callback_data="v3_challenge_status"), InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"))
        await c.answer(); await _edit(c, "🎭 <b>منوی شروع بازی</b>", kb)

    async def lobby_back(c):
        _sync(main); rows = _rows(main); await c.answer(); await _edit(c, _lobby_text(main, rows), _lobby_keyboard(main, rows))

    regs = [
        (new_game, lambda c: c.data == "new_game"),
        (scenario_menu, lambda c: c.data == "v3_scenario_menu"),
        (scenario, lambda c: str(c.data or "").startswith("v3_scenario_")),
        (moderator_menu, lambda c: c.data == "v3_moderator_menu"),
        (moderator, lambda c: str(c.data or "").startswith("v3_moderator_")),
        (create_game, lambda c: c.data == "v3_create_game"),
        (join, lambda c: c.data == "v3_join"),
        (leave, lambda c: c.data == "v3_leave"),
        (reserve, lambda c: c.data == "v3_reserve"),
        (seat, lambda c: str(c.data or "").startswith("v3_seat_") and not str(c.data).startswith("v3_seat_info_")),
        (lambda c: c.answer("💺 این صندلی گرفته شده است.", show_alert=True), lambda c: str(c.data or "").startswith("v3_seat_info_")),
        (reserve_list, lambda c: c.data == "v3_reserve_list"),
        (manage, lambda c: c.data == "v3_manage"),
        (toggle_challenge, lambda c: c.data == "v3_toggle_challenge"),
        (remove_player, lambda c: c.data == "v3_remove_player"),
        (remove, lambda c: str(c.data or "").startswith("v3_remove_")),
        (attendance, lambda c: c.data == "v3_attendance"),
        (ready, lambda c: c.data == "v3_ready"),
        (distribute, lambda c: c.data == "v3_distribute_roles"),
        (challenge_status, lambda c: c.data == "v3_challenge_status"),
        (start_back, lambda c: c.data == "v3_start_back"),
        (lobby_back, lambda c: c.data == "v3_lobby_back"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt); _front(dp, fn)

    logging.info("✅ Mafia lobby UI v3 installed")
