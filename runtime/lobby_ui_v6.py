from __future__ import annotations

import html
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup



def install(main):
    """Canonical MafiaNights lobby UI backed by the persistent lobby runtime.

    The migration keeps PostgreSQL/state as the authority while restoring the
    original seat-grid lobby interaction: scenario -> moderator -> seat grid ->
    reserve -> role distribution. Legacy globals are mirrored only for old game
    mechanics which still consume main1.player_slots/players.
    """
    dp, bot = main.dp, main.bot
    original_menu = main.main_menu_keyboard
    main._lv6_change_scenario = False
    main._lv6_ready_players = set()

    def front(fn):
        handlers = getattr(dp.callback_query_handlers, "handlers", [])
        for i, item in enumerate(handlers):
            if getattr(item, "callback", None) is fn:
                handlers.insert(0, handlers.pop(i))
                return

    def runtime():
        return getattr(main, "runtime", None)

    def gid(message=None):
        if message is not None and getattr(message, "chat", None):
            return int(message.chat.id)
        value = getattr(main, "group_chat_id", None) or getattr(main, "ALLOWED_GROUP_ID", None)
        return int(value) if value else None

    def snapshot(group_id):
        rt = runtime()
        if rt is not None:
            try:
                return rt.lobby_snapshot(int(group_id))
            except Exception:
                logging.exception("persistent lobby snapshot failed for %s", group_id)
        return {"game": None, "players": [], "seats": {}, "waiting": []}

    def sync_legacy(group_id):
        """Mirror persisted lobby state into legacy globals without making them authoritative."""
        snap = snapshot(group_id)
        game = snap.get("game") or {}
        players = snap.get("players") or []
        main.group_chat_id = int(group_id)
        main.selected_scenario = game.get("scenario_id") or getattr(main, "selected_scenario", None)
        main.moderator_id = game.get("moderator_id") or getattr(main, "moderator_id", None)
        cfg = main.scenarios.get(main.selected_scenario) or {}
        main.MAX_SEATS = len(cfg.get("roles") or [])
        try:
            main.players.clear()
            main.player_slots.clear()
            main.waiting_list.clear()
            for row in players:
                uid = int(row["player_id"])
                name = row.get("nickname") or row.get("first_name") or row.get("username") or str(uid)
                main.players[uid] = name
                seat = row.get("seat")
                if seat is not None and str(row.get("status") or "active") not in {"removed", "dead"}:
                    main.player_slots[int(seat)] = uid
                elif str(row.get("status") or "") == "waiting" or seat is None:
                    if uid not in main.waiting_list:
                        main.waiting_list.append(uid)
        except Exception:
            logging.exception("legacy lobby mirror failed")
        return snap

    def mention(uid, fallback=None):
        try:
            name = main.display_name(int(uid), fallback or main.players.get(uid))
        except Exception:
            name = fallback or main.players.get(uid) or str(uid)
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(str(name))}</b></a>'

    async def is_admin(uid, group_id=None):
        group_id = group_id or gid()
        if not group_id:
            return False
        try:
            return int(uid) in {int(a.user.id) for a in await bot.get_chat_administrators(group_id)}
        except Exception:
            return False

    async def edit(message, text, kb=None):
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return True
        except Exception as exc:
            logging.warning("lobby edit failed: %s", exc)
            return False

    def menu():
        try:
            src = original_menu()
        except Exception:
            src = InlineKeyboardMarkup()
        out = InlineKeyboardMarkup(row_width=2)
        for row in getattr(src, "inline_keyboard", []):
            nr = []
            for button in row:
                text = str(getattr(button, "text", ""))
                if "لیست جدید" in text:
                    continue
                if "بازی جدید" in text:
                    nr.append(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv6_new"))
                else:
                    nr.append(button)
            if nr:
                out.row(*nr)
        if not any(getattr(b, "callback_data", "") == "lv6_new" for row in out.inline_keyboard for b in row):
            out.add(InlineKeyboardButton("🎮 بازی جدید", callback_data="lv6_new"))
        return out

    def scenario_kb(changing=False):
        kb = InlineKeyboardMarkup(row_width=1)
        for i, (name, cfg) in enumerate(main.scenarios.items()):
            cfg = cfg or {}
            roles = cfg.get("roles") or []
            kb.add(InlineKeyboardButton(
                f"📝 {name} ({cfg.get('min_players', 1)}-{len(roles)})",
                callback_data=f"lv6_s:{i}",
            ))
        kb.add(InlineKeyboardButton(
            "⬅️ بازگشت به لابی" if changing else "⬅️ بازگشت",
            callback_data="lv6_back_lobby" if changing else "lv6_home",
        ))
        return kb

    async def moderator_kb(group_id):
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in await bot.get_chat_administrators(group_id):
            kb.add(InlineKeyboardButton(
                admin.user.full_name,
                callback_data=f"lv6_m:{int(admin.user.id)}",
            ))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به سناریو", callback_data="lv6_back_s"))
        return kb

    def lobby_text(group_id):
        snap = sync_legacy(group_id)
        game = snap.get("game") or {}
        scenario = game.get("scenario_id") or "---"
        cfg = main.scenarios.get(scenario) or {}
        capacity = len(cfg.get("roles") or [])
        active = [r for r in snap.get("players", []) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}]
        waiting = [r for r in snap.get("players", []) if r.get("seat") is None and str(r.get("status") or "waiting") == "waiting"]
        moderator_id = game.get("moderator_id")
        lines = [
            "༄",
            "    <b>Mafia Nights</b>",
            "",
            f"📝 <b>سناریو:</b> {html.escape(str(scenario))}",
            f"🎩 <b>گرداننده:</b> {mention(moderator_id) if moderator_id else '---'}",
            f"👥 <b>بازیکنان:</b> {len(active)}/{capacity}",
            "",
            "◤◢◣◥◤◢◣◥◤◢◣◥",
            "        <b>لیست بازیکنان</b>",
            "◤◢◣◥◤◢◣◥◤◢◣◥",
            "",
        ]
        if active:
            for row in sorted(active, key=lambda x: int(x.get("seat") or 999)):
                seat = int(row["seat"])
                uid = int(row["player_id"])
                lines.append(f"{seat:02d} {mention(uid, row.get('first_name') or row.get('username'))}")
        else:
            lines.append("— هنوز بازیکنی وارد نشده است.")
        if waiting:
            lines += ["", "🎟 <b>لیست رزرو</b>"]
            for index, row in enumerate(waiting, 1):
                lines.append(f"{index}. {mention(int(row['player_id']), row.get('first_name'))}")
        lines += ["", "◤◢◣◥◤◢◣◥◤◢◣◥", "༄"]
        return "\n".join(lines)

    def lobby_kb(group_id):
        snap = snapshot(group_id)
        game = snap.get("game") or {}
        scenario = game.get("scenario_id") or main.selected_scenario
        capacity = len((main.scenarios.get(scenario) or {}).get("roles") or [])
        occupied = {int(r["seat"]): r for r in snap.get("players", []) if r.get("seat") is not None and str(r.get("status") or "active") not in {"removed", "dead"}}
        waiting = [r for r in snap.get("players", []) if r.get("seat") is None and str(r.get("status") or "waiting") == "waiting"]
        kb = InlineKeyboardMarkup(row_width=3)
        for seat in range(1, capacity + 1):
            row = occupied.get(seat)
            if row:
                name = row.get("nickname") or row.get("first_name") or row.get("username") or "👤"
                label = f"{seat:02d} {str(name)[:12]}"
            else:
                label = f"{seat:02d} ⬜"
            kb.insert(InlineKeyboardButton(label, callback_data=f"lv6_seat:{seat}"))
        kb.row(
            InlineKeyboardButton("✅ ورود", callback_data="lv6_toggle"),
            InlineKeyboardButton("❌ خروج", callback_data="lv6_toggle"),
        )
        if len(occupied) >= capacity > 0:
            kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو", callback_data="lv6_reserve"))
            kb.add(InlineKeyboardButton("🎭 پخش نقش", callback_data="distribute_roles"))
        kb.add(InlineKeyboardButton("⚙️ مدیریت بازی", callback_data="lv6_manage"))
        return kb

    async def render(message):
        group_id = gid(message)
        await edit(message, lobby_text(group_id), lobby_kb(group_id))
        main.lobby_message_id = message.message_id

    async def new(callback):
        group_id = gid(callback.message)
        if getattr(main, "game_running", False) or getattr(main, "round_active", False):
            await callback.answer("⚠️ بازی در حال اجراست.", show_alert=True)
            return
        rt = runtime()
        if rt is not None:
            rt.lobby.ensure(group_id)
        main.group_chat_id = group_id
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        main._lv6_setup = True
        main._lv6_change_scenario = False
        await edit(callback.message, "📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.", scenario_kb(False))
        await callback.answer()

    async def scenario(callback):
        group_id = gid(callback.message)
        try:
            index = int(callback.data.split(":", 1)[1])
            selected = list(main.scenarios)[index]
        except Exception:
            await callback.answer("سناریو نامعتبر است.", show_alert=True)
            return
        rt = runtime()
        if rt is not None:
            game = rt.state.active_game(group_id) or rt.lobby.ensure(group_id)
            if main._lv6_change_scenario:
                for row in list(rt.lobby_snapshot(group_id).get("players", [])):
                    rt.lobby.leave(group_id, int(row["player_id"]))
            rt.lobby.set_scenario(group_id, selected)
        main.selected_scenario = selected
        main.MAX_SEATS = len((main.scenarios[selected] or {}).get("roles") or [])
        if main._lv6_change_scenario and main.moderator_id:
            main._lv6_change_scenario = False
            main._lv6_setup = False
            main.lobby_active = True
            await render(callback.message)
            await callback.answer("✅ سناریو تغییر کرد و لابی به‌روزرسانی شد")
            return
        await edit(callback.message, f"📝 <b>سناریو: {html.escape(selected)}</b>\n\n🎩 <b>انتخاب گرداننده</b>", await moderator_kb(group_id))
        await callback.answer("✅ سناریو انتخاب شد")

    async def moderator(callback):
        group_id = gid(callback.message)
        uid = int(callback.data.split(":", 1)[1])
        if not await is_admin(uid, group_id):
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            return
        rt = runtime()
        if rt is not None:
            rt.lobby.set_moderator(group_id, uid)
        main.moderator_id = uid
        main.group_chat_id = group_id
        main.lobby_active = True
        main.game_running = False
        main.round_active = False
        main._lv6_setup = False
        main._lv6_change_scenario = False
        sync_legacy(group_id)
        await render(callback.message)
        await callback.answer("✅ لابی اصلی ایجاد شد")

    async def home(callback):
        main._lv6_setup = False
        main.lobby_active = False
        await edit(callback.message, "🎮 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید.", menu())
        await callback.answer()

    async def back_s(callback):
        main._lv6_change_scenario = False
        await edit(callback.message, "📝 <b>انتخاب سناریو</b>", scenario_kb(False))
        await callback.answer()

    async def toggle(callback):
        group_id = gid(callback.message)
        uid = int(callback.from_user.id)
        rt = runtime()
        if rt is None:
            await callback.answer("⚠️ persistence runtime در دسترس نیست.", show_alert=True)
            return
        snap = rt.lobby_snapshot(group_id)
        rows = {int(r["player_id"]): r for r in snap.get("players", [])}
        current = rows.get(uid)
        if current and current.get("seat") is not None:
            seat = int(current["seat"])
            rt.lobby.leave(group_id, uid)
            promoted = rt.lobby.promote_waiting(group_id, seat)
            await render(callback.message)
            await callback.answer("🚪 از بازی خارج شدید" if not promoted else "🚪 خارج شدید؛ بازیکن رزرو جایگزین شد")
            return
        if current and current.get("seat") is None:
            await callback.answer("🎟 شما در لیست رزرو هستید؛ برای لغو رزرو از دکمه رزرو استفاده کنید.", show_alert=True)
            return
        scenario = (snap.get("game") or {}).get("scenario_id") or main.selected_scenario
        capacity = len((main.scenarios.get(scenario) or {}).get("roles") or [])
        occupied = [r for r in snap.get("players", []) if r.get("seat") is not None]
        if len(occupied) >= capacity:
            await callback.answer("🎟 ظرفیت اصلی پر است؛ رزرو را انتخاب کنید.", show_alert=True)
            return
        seat = next((n for n in range(1, capacity + 1) if n not in {int(r["seat"]) for r in occupied}), None)
        rt.lobby.join(group_id, uid, seat)
        await render(callback.message)
        await callback.answer(f"✅ شما وارد بازی شدید؛ صندلی {seat} ثبت شد")

    async def seat(callback):
        group_id = gid(callback.message)
        uid = int(callback.from_user.id)
        seat_number = int(callback.data.split(":", 1)[1])
        rt = runtime()
        if rt is None:
            await callback.answer("⚠️ persistence runtime در دسترس نیست.", show_alert=True)
            return
        snap = rt.lobby_snapshot(group_id)
        rows = {int(r["player_id"]): r for r in snap.get("players", [])}
        current = rows.get(uid)
        if not current:
            await callback.answer("❌ ابتدا وارد بازی شوید.", show_alert=True)
            return
        occupied = {int(r["seat"]): int(r["player_id"]) for r in snap.get("players", []) if r.get("seat") is not None}
        if seat_number in occupied and occupied[seat_number] != uid:
            await callback.answer("❌ این صندلی قبلاً رزرو شده است.", show_alert=True)
            return
        rt.lobby.assign_seat(group_id, uid, seat_number)
        await render(callback.message)
        await callback.answer(f"✅ صندلی {seat_number} برای شما ثبت شد")

    async def reserve(callback):
        group_id = gid(callback.message)
        uid = int(callback.from_user.id)
        rt = runtime()
        if rt is None:
            await callback.answer("⚠️ persistence runtime در دسترس نیست.", show_alert=True)
            return
        snap = rt.lobby_snapshot(group_id)
        game = snap.get("game") or {}
        scenario = game.get("scenario_id") or main.selected_scenario
        capacity = len((main.scenarios.get(scenario) or {}).get("roles") or [])
        occupied = [r for r in snap.get("players", []) if r.get("seat") is not None]
        current = next((r for r in snap.get("players", []) if int(r["player_id"]) == uid), None)
        if len(occupied) < capacity:
            await callback.answer("رزرو پس از تکمیل بازیکنان و صندلی‌ها فعال است.", show_alert=True)
            return
        if current and current.get("seat") is None:
            rt.lobby.leave(group_id, uid)
            await render(callback.message)
            await callback.answer("❌ رزرو شما لغو شد")
            return
        if current:
            await callback.answer("شما در لیست اصلی هستید.", show_alert=True)
            return
        rt.lobby.join(group_id, uid, None, is_substitute=True)
        await render(callback.message)
        await callback.answer("🎟 به لیست رزرو اضافه شدید")

    async def manage(callback):
        if not await is_admin(callback.from_user.id, gid(callback.message)):
            await callback.answer("⛔ فقط مدیران.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for text, data in [
            ("🚫 لغو بازی", "lv6_cancel"), ("📝 تغییر سناریو", "lv6_change_s"),
            ("🎩 تغییر گرداننده", "lv6_change_m"), ("⚔️ وضعیت چالش", "lv6_challenge"),
            ("🗑 حذف بازیکن", "lv6_remove"), ("📢 حاضری / تگ لیست", "lv6_ready"),
            ("⬅️ بازگشت به لابی", "lv6_back_lobby")]:
            kb.add(InlineKeyboardButton(text, callback_data=data))
        await edit(callback.message, "⚙️ <b>مدیریت بازی</b>", kb)
        await callback.answer()

    async def cancel(callback):
        group_id = gid(callback.message)
        if callback.from_user.id != main.moderator_id and not await is_admin(callback.from_user.id, group_id):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        rt = runtime()
        if rt is not None:
            game = rt.state.active_game(group_id)
            if game:
                rt.state.games.update_game(game["id"], status="finished")
        main.players.clear(); main.player_slots.clear(); main.waiting_list.clear()
        main.lobby_active = False; main.game_running = False; main.round_active = False
        main.selected_scenario = None; main.moderator_id = None; main.MAX_SEATS = 0
        await edit(callback.message, "🚫 <b>بازی لغو شد.</b>", menu())
        await callback.answer()

    async def back_lobby(callback):
        main._lv6_change_scenario = False
        main._lv6_setup = False
        main.lobby_active = True
        await render(callback.message)
        await callback.answer()

    async def change_s(callback):
        if not await is_admin(callback.from_user.id, gid(callback.message)):
            await callback.answer("⛔ فقط مدیران.", show_alert=True)
            return
        main._lv6_change_scenario = True
        await edit(callback.message, "📝 <b>تغییر سناریو</b>\n\nسناریوی جدید را انتخاب کنید.", scenario_kb(True))
        await callback.answer()

    async def change_m(callback):
        if not await is_admin(callback.from_user.id, gid(callback.message)):
            await callback.answer("⛔ فقط مدیران.", show_alert=True)
            return
        main._lv6_change_scenario = False
        await edit(callback.message, "🎩 <b>تغییر گرداننده</b>", await moderator_kb(gid(callback.message)))
        await callback.answer()

    async def challenge(callback):
        if not await is_admin(callback.from_user.id, gid(callback.message)) and callback.from_user.id != main.moderator_id:
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        status = "روشن" if getattr(main, "challenge_active", True) else "خاموش"
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(f"🔄 تغییر وضعیت (فعلاً {status})", callback_data="lv6_challenge_toggle"),
            InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"),
        )
        await edit(callback.message, f"⚔️ <b>وضعیت چالش</b>\n\nوضعیت فعلی: <b>{status}</b>", kb)
        await callback.answer()

    async def challenge_toggle(callback):
        if callback.from_user.id != main.moderator_id and not await is_admin(callback.from_user.id, gid(callback.message)):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        main.challenge_active = not getattr(main, "challenge_active", True)
        await challenge(callback)

    async def remove_menu(callback):
        if not await is_admin(callback.from_user.id, gid(callback.message)):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        snap = snapshot(gid(callback.message))
        rows = [r for r in snap.get("players", []) if r.get("seat") is not None]
        kb = InlineKeyboardMarkup(row_width=1)
        for row in sorted(rows, key=lambda x: int(x["seat"])):
            uid = int(row["player_id"]); seat = int(row["seat"])
            kb.add(InlineKeyboardButton(f"🗑 {seat:02d}. {html.escape(str(main.display_name(uid, row.get('first_name'))))}", callback_data=f"lv6_remove:{uid}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"))
        await edit(callback.message, "🗑 <b>انتخاب بازیکن برای حذف</b>", kb); await callback.answer()

    async def remove_player(callback):
        if not await is_admin(callback.from_user.id, gid(callback.message)):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        group_id = gid(callback.message); uid = int(callback.data.split(":", 1)[1]); rt = runtime()
        if rt is not None:
            rt.lobby.leave(group_id, uid)
        await render(callback.message)
        await callback.answer("✅ بازیکن حذف شد")

    def ready_text(group_id):
        rows = [r for r in snapshot(group_id).get("players", []) if r.get("seat") is not None]
        lines = ["📢 <b>حاضری بازیکنان</b>", ""]
        for row in sorted(rows, key=lambda x: int(x["seat"])):
            uid = int(row["player_id"]); seat = int(row["seat"])
            mark = "✅" if uid in main._lv6_ready_players else "⬜"
            lines.append(f"{mark} {seat:02d}. {mention(uid, row.get('first_name'))}")
        return "\n".join(lines) if rows else "📢 <b>حاضری بازیکنان</b>\n\n— بازیکنی نیست."

    async def ready_menu(callback):
        if not await is_admin(callback.from_user.id, gid(callback.message)):
            await callback.answer("⛔ فقط مدیران.", show_alert=True); return
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🙋‍♂️ آماده‌ام", callback_data="lv6_ready_click"),
            InlineKeyboardButton("⬅️ بازگشت به مدیریت", callback_data="lv6_manage"),
        )
        await edit(callback.message, ready_text(gid(callback.message)), kb); await callback.answer()

    async def ready_click(callback):
        uid = int(callback.from_user.id); group_id = gid(callback.message)
        rows = snapshot(group_id).get("players", [])
        if not any(int(r["player_id"]) == uid and r.get("seat") is not None for r in rows):
            await callback.answer("⛔ فقط بازیکنان داخل بازی می‌توانند حاضری بزنند.", show_alert=True); return
        main._lv6_ready_players.add(uid)
        await ready_menu(callback)
        await callback.answer("✅ حاضری شما ثبت شد")

    async def distribute(callback):
        group_id = gid(callback.message)
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند نقش‌ها را پخش کند.", show_alert=True); return
        sync_legacy(group_id)
        if not main.selected_scenario or not main.player_slots:
            await callback.answer("❌ سناریو یا صندلی‌ها مشخص نشده‌اند.", show_alert=True); return
        try:
            mapping = await main.distribute_roles()
            main.last_role_map = mapping or getattr(main, "last_role_map", {})
        except Exception as exc:
            logging.exception("role distribution failed: %s", exc)
            await callback.answer("❌ خطا در پخش نقش‌ها.", show_alert=True); return
        lines = []
        for seat, uid in sorted(main.player_slots.items()):
            name = main.display_name(uid, main.players.get(uid, "❓"))
            role = main.last_role_map.get(uid, "❓")
            lines.append(f"{seat:02d}. <a href='tg://user?id={uid}'><b>{html.escape(str(name))}</b></a> — {html.escape(str(role))}")
        try:
            await bot.send_message(main.moderator_id,
                "༄\n    <b>Mafia Nights</b>\n\n"
                f"📆 Date : {html.escape(str(main.get_jalali_today()))}\n"
                f"🗓 Scenario : {html.escape(str(main.selected_scenario))}\n"
                f"👮‍♂ God : {html.escape(str(main.display_name(main.moderator_id, main.players.get(main.moderator_id, '---'))))}\n\n"
                "~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n        <b>لیست بازیکنان و نقش‌ها</b>\n~ ~ ~ ~ ~ ~ ~ ~ ~ ~\n\n"
                + "\n".join(lines), parse_mode="HTML")
        except Exception:
            logging.exception("failed to send complete moderator role list")
        main.game_running = True; main.lobby_active = False; main.round_active = False; main._lv6_setup = False
        public_lines = "\n".join(f"{seat:02d}. <a href='tg://user?id={uid}'>{html.escape(str(main.display_name(uid, main.players.get(uid, '❓'))))}</a>" for seat, uid in sorted(main.player_slots.items()))
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("👑 انتخاب سر صحبت", callback_data="choose_head"),
            InlineKeyboardButton("⚔ وضعیت چالش", callback_data="lv6_challenge"),
            InlineKeyboardButton("▶ شروع دور", callback_data="start_round"),
        )
        await edit(callback.message, "🎭 <b>نقش‌ها پخش شد!</b>\n\n👥 <b>لیست بازیکنان:</b>\n" + public_lines + "\n\nℹ️ نقش‌ها در پیوی ارسال شدند.", kb)
        await callback.answer("✅ نقش‌ها پخش شد")

    async def start_round(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True); return
        sync_legacy(gid(callback.message))
        if not main.turn_order:
            main.turn_order = sorted(main.player_slots.keys()) if main.player_slots else []
        if not main.turn_order:
            await callback.answer("⚠️ ترتیب نوبت‌ها مشخص نشده.", show_alert=True); return
        main.current_turn_index = 0
        try: await callback.message.delete()
        except Exception: pass
        await main.start_turn(main.turn_order[0]); await callback.answer("✅ دور شروع شد")

    async def start_turn_from_day(callback):
        if callback.from_user.id != main.moderator_id:
            await callback.answer("❌ فقط گرداننده می‌تواند دور را شروع کند.", show_alert=True); return
        sync_legacy(gid(callback.message))
        if not main.turn_order:
            await callback.answer("⚠️ ابتدا سر صحبت را انتخاب کنید.", show_alert=True); return
        main.current_turn_index = 0
        try: await callback.message.delete()
        except Exception: pass
        await main.start_turn(main.turn_order[0]); await callback.answer("✅ دور شروع شد")

    async def tag_list(message):
        if message.chat.type not in ("group", "supergroup") or not message.text or message.text.strip() != "تگ لیست":
            return
        group_id = gid(message); snap = sync_legacy(group_id)
        rows = [r for r in snap.get("players", []) if r.get("seat") is not None]
        if not rows:
            await message.reply("👥 هیچ بازیکنی در بازی نیست."); return
        tags = [mention(int(r["player_id"]), r.get("first_name")) for r in sorted(rows, key=lambda x: int(x["seat"]))]
        await message.reply("📢 <b>تگ بازیکنان حاضر:</b>\n" + " ".join(tags), parse_mode="HTML")

    def noop_roles_list(*args, **kwargs):
        return None

    main.show_roles_list = noop_roles_list

    handlers = [
        (new, lambda c: c.data == "lv6_new"),
        (scenario, lambda c: str(c.data).startswith("lv6_s:")),
        (moderator, lambda c: str(c.data).startswith("lv6_m:")),
        (home, lambda c: c.data == "lv6_home"),
        (back_s, lambda c: c.data == "lv6_back_s"),
        (toggle, lambda c: c.data == "lv6_toggle"),
        (seat, lambda c: str(c.data).startswith("lv6_seat:")),
        (reserve, lambda c: c.data == "lv6_reserve"),
        (manage, lambda c: c.data == "lv6_manage"),
        (cancel, lambda c: c.data == "lv6_cancel"),
        (back_lobby, lambda c: c.data == "lv6_back_lobby"),
        (change_s, lambda c: c.data == "lv6_change_s"),
        (change_m, lambda c: c.data == "lv6_change_m"),
        (challenge, lambda c: c.data == "lv6_challenge"),
        (challenge_toggle, lambda c: c.data == "lv6_challenge_toggle"),
        (remove_menu, lambda c: c.data == "lv6_remove"),
        (remove_player, lambda c: str(c.data).startswith("lv6_remove:")),
        (ready_menu, lambda c: c.data == "lv6_ready"),
        (ready_click, lambda c: c.data == "lv6_ready_click"),
        (distribute, lambda c: c.data == "distribute_roles"),
        (start_round, lambda c: c.data == "start_round"),
        (start_turn_from_day, lambda c: c.data == "start_turn"),
    ]
    for fn, flt in handlers:
        dp.register_callback_query_handler(fn, flt)
        front(fn)

    dp.register_message_handler(tag_list, lambda m: bool(m.text) and m.text.strip() == "تگ لیست")
    try:
        handlers = dp.message_handlers.handlers
        for i, item in enumerate(handlers):
            if getattr(item, "callback", None) is tag_list:
                handlers.insert(0, handlers.pop(i)); break
    except Exception:
        pass

    main.main_menu_keyboard = menu
    logging.info("✅ canonical persistent lobby UI installed")
