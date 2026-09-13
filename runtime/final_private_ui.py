"""Single private UI authority for Mafia Nights.

Only this module owns the private admin game-management callbacks. Group/lobby
callbacks are deliberately not rendered here.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _private(callback):
    return bool(callback.message and callback.message.chat.type == "private")


def _group_id(app):
    for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None


def _display(app, uid):
    if not uid:
        return "—"
    try:
        value = app.display_name(uid, (getattr(app, "players", {}) or {}).get(uid))
        if value and str(value) not in {"?", "❓", "None", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    value = (getattr(app, "players", {}) or {}).get(uid)
    if isinstance(value, dict):
        value = value.get("nickname") or value.get("full_name") or value.get("first_name")
    return str(value or f"بازیکن {uid}")


def _is_running(app):
    return bool(
        getattr(app, "game_running", False)
        or getattr(app, "round_active", False)
        or getattr(app, "_stable_day_active", False)
        or getattr(app, "_stable_round_started", False)
    )


def _ensure_sets(app):
    if not isinstance(getattr(app, "_gm_muted_next_round", None), set):
        current = getattr(app, "_gm_muted_next_round", set()) or set()
        app._gm_muted_next_round = set(current)
    if not isinstance(getattr(app, "_gm_extra_next_round", None), set):
        current = getattr(app, "_gm_extra_next_round", set()) or set()
        app._gm_extra_next_round = set(current)


def _sync_next_settings(app):
    """Keep the final game-flow globals and add-ons settings in sync."""
    players_enabled = bool(getattr(app, "next_by_players_enabled", True))
    moderator_enabled = bool(getattr(app, "next_by_moderator_enabled", True))
    addons = getattr(app, "addons", None)
    if addons is not None:
        try:
            settings = addons.settings
            settings.setdefault("next", {})
            settings["next"]["allow_players_next"] = players_enabled
            settings["next"]["allow_moderator_next"] = moderator_enabled
            gid = _group_id(app)
            if gid:
                addons.set_group_settings(gid, settings)
                addons.settings = settings
        except Exception:
            logging.exception("private UI: failed to persist next settings")

    # If the persistent state authority is active, capture the compatibility
    # globals into the current game state as well.
    try:
        authority = (getattr(app, "_persistent_state_authority", None) or {}).get("authority")
        gid = _group_id(app)
        if authority is not None and gid:
            authority.capture_compatibility_mutations(gid)
    except Exception:
        logging.exception("private UI: failed to persist compatibility settings")


def _next_keyboard(app):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton(
            f"🎩 نکست برای گرداننده: {'فعال' if getattr(app, 'next_by_moderator_enabled', True) else 'غیرفعال'}",
            callback_data="finalgm:next:moderator",
        ),
        InlineKeyboardButton(
            f"👥 نکست برای بازیکنان: {'فعال' if getattr(app, 'next_by_players_enabled', True) else 'غیرفعال'}",
            callback_data="finalgm:next:players",
        ),
        InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"),
    )
    return kb


def start_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"),
        InlineKeyboardButton("⚙️ مدیریت سناریو", callback_data="final:scenarios"),
        InlineKeyboardButton("⚙️ امکانات اضافه", callback_data="addons_menu"),
        InlineKeyboardButton("👤 پروفایل", callback_data="up:menu"),
        InlineKeyboardButton("📚 راهنما", callback_data="final:help"),
    )
    return kb


def management_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    for text, data in (
        ("👥 لیست بازیکنان", "finalgm:players"),
        ("📤 ارسال دوباره نقشها", "finalgm:roles"),
        ("🗑 حذف بازیکن", "finalgm:remove"),
        ("🎂 تولد بازیکن", "finalgm:birthday"),
        ("🎩 تغییر گرداننده", "finalgm:moderator"),
        ("🔄 جایگزین بازیکن", "finalgm:replace"),
        ("🔇 سکوت", "finalgm:mute"),
        ("➕ ترن اضافی", "finalgm:extra"),
        ("⏭ مدیریت نکست", "finalgm:next"),
        ("🚫 لغو بازی", "finalgm:cancel"),
        ("⬅️ بازگشت", "finalgm:back"),
    ):
        kb.add(InlineKeyboardButton(text, callback_data=data))
    return kb


def management_report(app):
    running = _is_running(app)
    status = "🟢 در حال اجرای بازی" if running else (
        "🟡 لابی فعال" if getattr(app, "lobby_active", False) else "⚪ آماده"
    )
    return (
        "🛠 <b>مدیریت بازی</b>\n\n"
        f"📌 وضعیت: <b>{status}</b>\n"
        f"📝 سناریو: <b>{html.escape(str(getattr(app, 'selected_scenario', None) or '—'))}</b>\n"
        f"👥 بازیکنان: <b>{len(getattr(app, 'players', {}) or {})}</b>\n"
        f"💺 صندلی‌ها: <b>{len(getattr(app, 'player_slots', {}) or {})}</b>\n"
        f"🎩 گرداننده: <b>{html.escape(_display(app, getattr(app, 'moderator_id', None)))}</b>"
    )


def scenario_keyboard():
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ افزودن سناریو", callback_data="final:scenario:add"),
        InlineKeyboardButton("➖ حذف سناریو", callback_data="final:scenario:remove"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="final:start"),
    )
    return kb


async def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", None)
    if cq is None or getattr(app, "_final_private_ui_installed", False):
        return False

    async def allowed(callback):
        if not _private(callback):
            raise CancelHandler()
        uid = callback.from_user.id
        if uid == getattr(app, "moderator_id", None):
            return True
        gid = _group_id(app)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(gid)
                if uid in {a.user.id for a in admins}:
                    return True
            except Exception:
                logging.exception("private UI: failed to resolve group administrators")
        await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    async def render_start(callback, answer=None):
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(), parse_mode="HTML",
        )
        if answer:
            await callback.answer(answer)
        else:
            await callback.answer()

    async def start_message(message):
        if message.chat.type != "private":
            return
        await message.answer(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(), parse_mode="HTML",
        )
        raise CancelHandler()

    async def start_callback(callback):
        if not _private(callback):
            raise CancelHandler()
        await render_start(callback)
        raise CancelHandler()

    async def open_management(callback):
        await allowed(callback)
        await callback.message.edit_text(
            management_report(app), reply_markup=management_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def open_scenarios(callback):
        await allowed(callback)
        await callback.message.edit_text(
            "⚙️ <b>مدیریت سناریو</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=scenario_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def scenario_add(callback):
        await allowed(callback)
        fn = getattr(app, "add_scenario_start", None)
        if not fn:
            await callback.answer("⚠️ افزودن سناریو در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        await fn(callback, await app.dp.current_state(user=callback.from_user.id, chat=callback.message.chat.id))
        raise CancelHandler()

    async def scenario_remove(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        if not scenarios:
            await callback.message.edit_text("⚠️ هیچ سناریویی ثبت نشده است.", reply_markup=scenario_keyboard())
            await callback.answer()
            raise CancelHandler()
        if len(scenarios) == 1:
            await callback.message.edit_text(
                "⚠️ حداقل یک سناریو باید باقی بماند.", reply_markup=scenario_keyboard()
            )
            await callback.answer()
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for index, name in enumerate(scenarios):
            kb.add(InlineKeyboardButton(
                f"❌ {name}", callback_data=f"final:scenario:delete:{index}"
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت سناریو", callback_data="final:scenarios"))
        await callback.message.edit_text("سناریوی موردنظر برای حذف را انتخاب کنید:", reply_markup=kb)
        await callback.answer()
        raise CancelHandler()

    async def scenario_delete(callback):
        await allowed(callback)
        scenarios = getattr(app, "scenarios", {}) or {}
        try:
            index = int(str(callback.data).rsplit(":", 1)[1])
            names = list(scenarios.keys())
            name = names[index]
        except Exception:
            await callback.answer("⚠️ سناریو نامعتبر است.", show_alert=True)
            raise CancelHandler()
        if len(scenarios) <= 1:
            await callback.answer("⚠️ حداقل یک سناریو باید باقی بماند.", show_alert=True)
            raise CancelHandler()
        if _is_running(app) or getattr(app, "lobby_active", False):
            await callback.answer("⛔ هنگام فعال بودن بازی/لابی حذف سناریو مجاز نیست.", show_alert=True)
            raise CancelHandler()
        scenarios.pop(name, None)
        saver = getattr(app, "save_scenarios", None)
        if saver:
            saver()
        if getattr(app, "selected_scenario", None) == name:
            app.selected_scenario = None
        await callback.message.edit_text(
            f"✅ سناریو «{html.escape(name)}» حذف شد.",
            reply_markup=scenario_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def list_players(callback):
        await allowed(callback)
        slots = getattr(app, "player_slots", {}) or {}
        if not slots:
            text = "👥 <b>لیست بازیکنان</b>\n\nبازیکنی ثبت نشده است."
        else:
            lines = ["👥 <b>لیست بازیکنان</b>", ""]
            for seat, uid in sorted(slots.items()):
                lines.append(f"{int(seat):02d}. <a href='tg://user?id={uid}'>{html.escape(_display(app, uid))}</a>")
            text = "\n".join(lines)
        await callback.message.edit_text(
            text, reply_markup=InlineKeyboardMarkup().add(
                InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back")
            ), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def remove_menu(callback):
        await allowed(callback)
        slots = getattr(app, "player_slots", {}) or {}
        if not slots:
            await callback.answer("⚠️ بازیکنی برای حذف وجود ندارد.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted(slots.items()):
            kb.add(InlineKeyboardButton(
                f"🗑 {int(seat)}. {_display(app, uid)}",
                callback_data=f"finalgm:remove:{int(seat)}",
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await callback.message.edit_text("🗑 بازیکن موردنظر برای حذف را انتخاب کنید:", reply_markup=kb)
        await callback.answer()
        raise CancelHandler()

    async def remove_player(callback):
        await allowed(callback)
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("⚠️ صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        slots = getattr(app, "player_slots", {}) or {}
        uid = slots.get(seat)
        if uid is None:
            await callback.answer("⚠️ بازیکن پیدا نشد.", show_alert=True)
            raise CancelHandler()
        gid = _group_id(app)
        app.removed_players = getattr(app, "removed_players", {}) or {}
        group_removed = app.removed_players.setdefault(gid, {})
        name = _display(app, uid)
        role = (getattr(app, "last_role_map", {}) or {}).get(uid)
        group_removed[seat] = {"id": uid, "name": name}
        if role:
            group_removed[seat]["role"] = role
        slots.pop(seat, None)
        try:
            app.players.pop(uid, None)
        except Exception:
            pass
        try:
            app.last_role_map.pop(uid, None)
        except Exception:
            pass
        try:
            authority = (getattr(app, "_persistent_state_authority", None) or {}).get("authority")
            if authority and gid:
                authority.capture_compatibility_mutations(gid)
        except Exception:
            logging.exception("private UI: removed player persistence failed")
        await callback.answer(f"✅ {name} حذف شد.")
        await remove_menu(callback)

    async def birthday_menu(callback):
        await allowed(callback)
        gid = _group_id(app)
        removed_all = getattr(app, "removed_players", {}) or {}
        removed = removed_all.get(gid, {}) or {}
        if not removed:
            await callback.answer("🚫 لیست بازیکنان حذف‌شده خالی است.", show_alert=True)
            raise CancelHandler()
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, info in sorted(removed.items(), key=lambda x: int(x[0])):
            name = info.get("name") or f"بازیکن {info.get('id', '')}"
            kb.add(InlineKeyboardButton(
                f"🎂 {int(seat)}. {name}", callback_data=f"finalgm:birthday:{int(seat)}"
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await callback.message.edit_text(
            "🎂 <b>تولد بازیکن</b>\n\nبازیکن حذف‌شده را برای بازگرداندن انتخاب کنید:",
            reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def birthday_restore(callback):
        await allowed(callback)
        gid = _group_id(app)
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("⚠️ صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        removed_all = getattr(app, "removed_players", {}) or {}
        removed = removed_all.get(gid, {}) or {}
        info = removed.get(seat)
        if info is None:
            await callback.answer("⚠️ بازیکن حذف‌شده پیدا نشد.", show_alert=True)
            raise CancelHandler()
        slots = getattr(app, "player_slots", {}) or {}
        if seat in slots:
            await callback.answer("⚠️ صندلی قبلی در حال حاضر اشغال است.", show_alert=True)
            raise CancelHandler()
        uid = int(info.get("id"))
        # Prevent the same user occupying another seat simultaneously.
        if uid in slots.values():
            await callback.answer("⚠️ این بازیکن در بازی حضور دارد.", show_alert=True)
            raise CancelHandler()
        slots[seat] = uid
        if not isinstance(getattr(app, "players", None), dict):
            app.players = {}
        app.players[uid] = info.get("name") or f"بازیکن {uid}"
        removed.pop(seat, None)
        try:
            role = info.get("role")
            if role:
                app.last_role_map = getattr(app, "last_role_map", {}) or {}
                app.last_role_map[uid] = role
        except Exception:
            pass
        try:
            authority = (getattr(app, "_persistent_state_authority", None) or {}).get("authority")
            if authority and gid:
                authority.capture_compatibility_mutations(gid)
        except Exception:
            logging.exception("private UI: restored player persistence failed")
        await callback.answer("✅ بازیکن با شماره قبلی بازگردانده شد.")
        await callback.message.edit_text(
            f"🎂 <b>بازیکن بازگردانده شد</b>\n\n"
            f"{html.escape(str(info.get('name') or uid))} دوباره با صندلی <b>{seat}</b> وارد بازی شد.",
            reply_markup=management_keyboard(), parse_mode="HTML"
        )
        raise CancelHandler()

    async def next_menu(callback):
        await allowed(callback)
        await callback.message.edit_text(
            "⏭ <b>مدیریت نکست</b>\n\n"
            "با انتخاب هر گزینه، وضعیت آن بین فعال و غیرفعال تغییر می‌کند.",
            reply_markup=_next_keyboard(app), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def next_toggle(callback, target):
        await allowed(callback)
        if target == "moderator":
            app.next_by_moderator_enabled = not bool(getattr(app, "next_by_moderator_enabled", True))
            text = "🎩 نکست برای گرداننده"
        else:
            app.next_by_players_enabled = not bool(getattr(app, "next_by_players_enabled", True))
            text = "👥 نکست برای بازیکنان"
        _sync_next_settings(app)
        await callback.answer(f"{text}: {'فعال' if (app.next_by_moderator_enabled if target == 'moderator' else app.next_by_players_enabled) else 'غیرفعال'}")
        await callback.message.edit_text(
            "⏭ <b>مدیریت نکست</b>\n\n"
            "با انتخاب هر گزینه، وضعیت آن بین فعال و غیرفعال تغییر می‌کند.",
            reply_markup=_next_keyboard(app), parse_mode="HTML"
        )
        raise CancelHandler()

    async def moderator_menu(callback):
        await allowed(callback)
        gid = _group_id(app)
        if not gid:
            await callback.answer("⚠️ گروه بازی تنظیم نشده است.", show_alert=True)
            raise CancelHandler()
        try:
            admins = await app.bot.get_chat_administrators(gid)
        except Exception:
            admins = []
        kb = InlineKeyboardMarkup(row_width=1)
        for admin in admins:
            kb.add(InlineKeyboardButton(
                admin.user.full_name or str(admin.user.id),
                callback_data=f"finalgm:moderator:{admin.user.id}",
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        await callback.message.edit_text(
            "🎩 <b>تغییر گرداننده</b>\n\nگرداننده جدید را انتخاب کنید:",
            reply_markup=kb, parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def moderator_set(callback):
        await allowed(callback)
        try:
            uid = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("گرداننده نامعتبر است.", show_alert=True)
            raise CancelHandler()
        gid = _group_id(app)
        try:
            admins = {a.user.id for a in await app.bot.get_chat_administrators(gid)} if gid else set()
        except Exception:
            admins = set()
        if uid not in admins:
            await callback.answer("گرداننده باید مدیر گروه باشد.", show_alert=True)
            raise CancelHandler()
        old = getattr(app, "moderator_id", None)
        app.moderator_id = uid
        if gid:
            try:
                await app.bot.send_message(
                    gid,
                    "🎩 <b>تغییر گرداننده</b>\n"
                    f"قبلی: {html.escape(_display(app, old))}\n"
                    f"جدید: {html.escape(_display(app, uid))}", parse_mode="HTML",
                )
            except Exception:
                logging.exception("private moderator announcement failed")
        await callback.message.edit_text(
            management_report(app), reply_markup=management_keyboard(), parse_mode="HTML"
        )
        await callback.answer("✅ گرداننده تغییر کرد")
        raise CancelHandler()

    async def player_menu(callback, mode):
        await allowed(callback)
        if not _is_running(app):
            await callback.answer("⚠️ بازی در حال اجرا نیست.", show_alert=True)
            raise CancelHandler()
        _ensure_sets(app)
        selected = app._gm_muted_next_round if mode == "mute" else app._gm_extra_next_round
        kb = InlineKeyboardMarkup(row_width=1)
        for seat, uid in sorted((getattr(app, "player_slots", {}) or {}).items()):
            seat = int(seat)
            active = seat in selected
            icon = ("🔊" if active else "🔇") if mode == "mute" else ("➖" if active else "➕")
            kb.add(InlineKeyboardButton(
                f"{icon} {seat}. {_display(app, uid)}",
                callback_data=f"finalgm:{mode}:{seat}",
            ))
        kb.add(InlineKeyboardButton("⬅️ مدیریت بازی", callback_data="finalgm:back"))
        title = "🔇 <b>سکوت</b>" if mode == "mute" else "➕ <b>ترن اضافی</b>"
        await callback.message.edit_text(
            f"{title}\n\n🔇/➕ روی بازیکن بزنید تا برای <b>روز بعد</b> ثبت یا لغو شود.",
            reply_markup=kb, parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def player_toggle(callback, mode):
        await allowed(callback)
        _ensure_sets(app)
        try:
            seat = int(str(callback.data).rsplit(":", 1)[1])
        except Exception:
            await callback.answer("⚠️ صندلی نامعتبر است.", show_alert=True)
            raise CancelHandler()
        slots = getattr(app, "player_slots", {}) or {}
        if seat not in slots:
            await callback.answer("⚠️ بازیکن یافت نشد.", show_alert=True)
            raise CancelHandler()
        selected = app._gm_muted_next_round if mode == "mute" else app._gm_extra_next_round
        if seat in selected:
            selected.remove(seat)
            answer = "🔊 سکوت روز بعد لغو شد." if mode == "mute" else "➖ ترن اضافی لغو شد."
        else:
            selected.add(seat)
            answer = "🔇 سکوت برای روز بعد ثبت شد." if mode == "mute" else "➕ ترن اضافی ثبت شد."
        await callback.answer(answer)
        await player_menu(callback, mode)

    async def back(callback):
        await allowed(callback)
        await callback.message.edit_text(
            management_report(app), reply_markup=management_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def cancel_game(callback):
        await allowed(callback)
        fn = getattr(app, "cancel_game_handler", None)
        if fn:
            try:
                await fn(callback)
            except Exception:
                logging.exception("private cancel game failed")
                await callback.answer("❌ لغو بازی ناموفق بود.", show_alert=True)
        else:
            await callback.answer("⚠️ لغو بازی در نسخه فعلی در دسترس نیست.", show_alert=True)
        raise CancelHandler()

    async def roles(callback):
        await allowed(callback)
        fn = getattr(app, "send_roles_panel", None)
        if not fn:
            await callback.answer("⚠️ ارسال نقش در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await fn(callback, app.bot)
        except Exception:
            logging.exception("private resend roles failed")
            await callback.answer("❌ ارسال نقش ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def replace(callback):
        await allowed(callback)
        fn = getattr(app, "show_substitute_list", None)
        if not fn:
            await callback.answer("⚠️ لیست جایگزین‌ها در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await fn(callback)
        except Exception:
            logging.exception("private substitute list failed")
            await callback.answer("❌ اجرای عملیات ناموفق بود.", show_alert=True)
        raise CancelHandler()

    async def help_handler(callback):
        await allowed(callback)
        fn = getattr(app, "help_handler", None)
        if fn:
            await fn(callback.message)
        else:
            try:
                with open("help.txt", "r", encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                text = "📚 راهنما در دسترس نیست."
            await callback.message.edit_text(text, reply_markup=start_keyboard())
        await callback.answer()
        raise CancelHandler()

    regs = [
        (open_management, lambda c: c.data == "manage_game"),
        (open_scenarios, lambda c: c.data == "final:scenarios"),
        (scenario_add, lambda c: c.data == "final:scenario:add"),
        (scenario_remove, lambda c: c.data == "final:scenario:remove"),
        (scenario_delete, lambda c: str(c.data or "").startswith("final:scenario:delete:")),
        (list_players, lambda c: c.data == "finalgm:players"),
        (roles, lambda c: c.data == "finalgm:roles"),
        (remove_menu, lambda c: c.data == "finalgm:remove"),
        (remove_player, lambda c: str(c.data or "").startswith("finalgm:remove:")),
        (birthday_menu, lambda c: c.data == "finalgm:birthday"),
        (birthday_restore, lambda c: str(c.data or "").startswith("finalgm:birthday:")),
        (moderator_menu, lambda c: c.data == "finalgm:moderator"),
        (moderator_set, lambda c: str(c.data or "").startswith("finalgm:moderator:")),
        (replace, lambda c: c.data == "finalgm:replace"),
        (lambda c: player_menu(c, "mute"), lambda c: c.data == "finalgm:mute"),
        (lambda c: player_toggle(c, "mute"), lambda c: str(c.data or "").startswith("finalgm:mute:")),
        (lambda c: player_menu(c, "extra"), lambda c: c.data == "finalgm:extra"),
        (lambda c: player_toggle(c, "extra"), lambda c: str(c.data or "").startswith("finalgm:extra:")),
        (next_menu, lambda c: c.data == "finalgm:next"),
        (lambda c: next_toggle(c, "moderator"), lambda c: c.data == "finalgm:next:moderator"),
        (lambda c: next_toggle(c, "players"), lambda c: c.data == "finalgm:next:players"),
        (cancel_game, lambda c: c.data == "finalgm:cancel"),
        (back, lambda c: c.data == "finalgm:back"),
        (start_callback, lambda c: c.data == "final:start"),
        (help_handler, lambda c: c.data == "final:help"),
    ]
    for fn, filt in regs:
        dp.register_callback_query_handler(fn, filt, state="*")

    # Remove the old private-management callback owners. Group/game-flow
    # handlers are left alone; final UI owns all callbacks surfaced in private.
    legacy_private_names = {
        "manage_game_handler", "toggle_next_player_pm", "toggle_next_moderator_pm",
        "birthday_player_handler", "birthday_player_confirm", "remove_player_handler",
        "remove_player_confirm", "replace_player_list_handler", "choose_substitute_for_replace",
        "do_replace_handler", "challenge_status_pv", "list_players_handler", "list_players_pv",
        "send_roles_panel", "manage_moderator_menu", "show_current_moderator",
        "change_moderator", "set_new_moderator", "show_help", "back_main",
    }
    cq[:] = [
        h for h in list(cq)
        if getattr(getattr(h, "handler", None), "__name__", "") not in legacy_private_names
    ]

    owned = [h for h in list(cq) if getattr(getattr(h, "handler", None), "__module__", "") == __name__]
    others = [h for h in list(cq) if h not in owned]
    cq[:] = owned + others

    dp.register_message_handler(start_message, commands=["start"], state="*")
    if mh:
        for i, h in enumerate(list(mh)):
            if getattr(getattr(h, "handler", None), "__module__", "") == __name__:
                mh.insert(0, mh.pop(i))
                break

    app._final_private_ui_installed = True
    return True
