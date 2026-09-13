"""Persistent day-voting runtime for MafiaNights."""
from __future__ import annotations

import asyncio
import html
import time

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

WAIT_OPTIONS = (15, 20, 30)
VOTE_OPTIONS = (15, 20, 30)
AUTO, MANUAL = "auto", "manual"


def _gid(main):
    for obj in (main, getattr(main, "addons", None)):
        for key in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
            value = getattr(obj, key, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _rt(main):
    return getattr(main, "runtime", None)


def _game(main):
    rt, gid = _rt(main), _gid(main)
    return rt.state.active_game(gid) if rt and gid else None


def _state(main):
    return dict((_game(main) or {}).get("state") or {})


def _save(main, payload):
    game, rt = _game(main), _rt(main)
    return bool(game and rt and rt.state.games.update_game(game["id"], state=payload))


def _players(main):
    game, rt = _game(main), _rt(main)
    if game and rt:
        try:
            return [dict(x) for x in rt.state.games.list_players(game["id"]) if str(x.get("status") or "active") not in {"dead", "removed"}]
        except Exception:
            pass
    return [{"seat": int(s), "player_id": int(uid)} for s, uid in sorted((getattr(main, "player_slots", {}) or {}).items())]


def _name(main, uid, seat=None):
    try:
        manager = getattr(main, "nicknames", None)
        for method in ("get_nick", "get"):
            fn = getattr(manager, method, None)
            if fn:
                value = fn(int(uid))
                if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
                    return str(value)
    except Exception:
        pass
    try:
        value = main.display_name(int(uid), None)
        if value and str(value).strip() not in {"?", "❓", "None", "بازیکن"}:
            return str(value)
    except Exception:
        pass
    return f"بازیکن {int(seat or 0)}"


def _row_name(main, row):
    return row.get("nickname") or row.get("first_name") or _name(main, row["player_id"], row.get("seat"))


def _default(main):
    return {"round": 1, "wait_seconds": 20, "vote_seconds": 20, "mode": AUTO, "vote_rights_taken": [], "targets": [int(x["player_id"]) for x in _players(main)], "target_index": 0, "votes": {}, "started_at": None, "deadline": None, "phase": "settings", "selected_round_two": []}


def _v(main):
    payload = _state(main)
    voting = payload.get("voting")
    if not isinstance(voting, dict):
        voting = _default(main)
        payload["voting"] = voting
        _save(main, payload)
    if "vote_rights_taken" not in voting:
        voting["vote_rights_taken"] = list(voting.get("round_two_vote_rights_taken") or [])
        voting.pop("round_two_vote_rights_taken", None)
        _put(main, voting)
    elif "round_two_vote_rights_taken" in voting:
        voting.pop("round_two_vote_rights_taken", None)
        _put(main, voting)
    return voting


def _put(main, voting):
    payload = _state(main)
    payload["voting"] = voting
    _save(main, payload)
    return voting


def _active_rights(v):
    return {int(x) for x in (v.get("vote_rights_taken") or [])}


def _settings_kb(v):
    mode = "خودکار" if v.get("mode") == AUTO else "دستی"
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton(f"⏱ زمان انتظار رای‌گیری: {v['wait_seconds']} ثانیه", callback_data="vote:wait"),
        InlineKeyboardButton(f"⏱ زمان هر رای: {v['vote_seconds']} ثانیه", callback_data="vote:duration"),
        InlineKeyboardButton(f"🚫 گرفتن حق رای ({len(v.get('vote_rights_taken', []))})", callback_data="vote:rights"),
        InlineKeyboardButton(f"🗳 نوع رای‌گیری: {mode}", callback_data="vote:mode"),
        InlineKeyboardButton("▶️ شروع رای‌گیری", callback_data="vote:start"),
    )


def _choices(prefix, values, current):
    kb = InlineKeyboardMarkup(row_width=1)
    for value in values:
        label = f"{value} ثانیه" if isinstance(value, int) else ("خودکار" if value == AUTO else "دستی")
        if value == current:
            label += " ✅"
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:{prefix}:{value}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _rights_kb(main, v):
    taken = _active_rights(v)
    kb = InlineKeyboardMarkup(row_width=1)
    for row in _players(main):
        uid = int(row["player_id"])
        label = f"🚫 {_row_name(main, row)}" + (" ✅" if uid in taken else "")
        kb.add(InlineKeyboardButton(label, callback_data=f"vote:right:{uid}"))
    kb.add(InlineKeyboardButton("⬅️ تنظیمات رای‌گیری", callback_data="vote:settings"))
    return kb


def _round2_kb(main, v):
    selected = {int(x) for x in (v.get("selected_round_two") or [])}
    kb = InlineKeyboardMarkup(row_width=1)
    for row in _players(main):
        uid = int(row["player_id"])
        kb.add(InlineKeyboardButton(_row_name(main, row) + (" ✅" if uid in selected else ""), callback_data=f"vote:r2pick:{uid}"))
    kb.add(InlineKeyboardButton("🚫 گرفتن حق رای", callback_data="vote:rights"), InlineKeyboardButton("✅ تایید و شروع رای دوم", callback_data="vote:r2confirm"), InlineKeyboardButton("⬅️ بازگشت", callback_data="vote:settings"))
    return kb


def _day_end_kb():
    return InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🗳 رای‌گیری", callback_data="vote:settings"),
        InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night"),
        InlineKeyboardButton("🏁 اتمام بازی", callback_data="end_game"),
    )


async def _settings(main, callback):
    v = _v(main)
    text = f"🗳 <b>تنظیمات رای‌گیری</b>\n\n⏱ زمان انتظار: {v['wait_seconds']} ثانیه\n⏱ زمان هر رای: {v['vote_seconds']} ثانیه\n🚫 بدون حق رای: {len(v.get('vote_rights_taken', []))} نفر\n🗳 نوع: {'خودکار' if v.get('mode') == AUTO else 'دستی'}"
    await callback.message.edit_text(text, reply_markup=_settings_kb(v), parse_mode="HTML")
    await callback.answer()


async def _start_target(main):
    v = _v(main)
    targets = list(v.get("targets") or [])
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target = int(targets[idx])
    rows = {int(x["player_id"]): x for x in _players(main)}
    name = _name(main, target, rows.get(target, {}).get("seat"))
    now = time.time()
    deadline = now + int(v["vote_seconds"])
    v["phase"], v["started_at"], v["deadline"] = "voting", now, deadline
    v.setdefault("votes", {}).setdefault(str(target), [])
    _put(main, v)
    markup = InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🗳 رای می‌دهم", callback_data="vote:cast")) if v.get("mode") == AUTO else None
    await main.bot.send_message(_gid(main), f"🗳 <b>رای برای {html.escape(name)}</b>\n\n⏱ {int(v['vote_seconds'])} ثانیه فرصت دارید.", parse_mode="HTML", reply_markup=markup)
    main._voting_task = None


async def _timer(main, deadline, expected):
    await asyncio.sleep(max(0, float(deadline) - time.time()))
    v = _v(main)
    if v.get("phase") == expected and v.get("deadline") == deadline:
        await (_start_target(main) if expected == "waiting" else _end_target(main))


async def _start_wait(main):
    v = _v(main)
    deadline = time.time() + int(v["wait_seconds"])
    v.update(phase="waiting", started_at=time.time(), deadline=deadline, target_index=0, votes={})
    _put(main, v)
    blocked = _active_rights(v)
    names = [_row_name(main, r) for r in _players(main) if int(r["player_id"]) in blocked]
    blocked_text = "\n".join(f"• {html.escape(x)}" for x in names) if names else "• هیچ‌کس"
    await main.bot.send_message(_gid(main), f"🗳 <b>رای‌گیری پس از {int(v['wait_seconds'])} ثانیه شروع می‌شود.</b>\nبرای رای به هر بازیکن {int(v['vote_seconds'])} ثانیه فرصت دارید.\n\n🚫 <b>بازیکنانی که حق رای ندارند:</b>\n{blocked_text}", parse_mode="HTML")
    main._voting_task = None
    await asyncio.sleep(max(0, float(deadline) - time.time()))
    current = _v(main)
    if current.get("phase") == "waiting" and current.get("deadline") == deadline:
        await _start_target(main)


async def _end_target(main):
    v = _v(main)
    targets = list(v.get("targets") or [])
    idx = int(v.get("target_index") or 0)
    if idx >= len(targets):
        return await _finish_round(main)
    target = int(targets[idx])
    voted = {int(x) for x in (v.get("votes") or {}).get(str(target), [])}
    rows = {int(x["player_id"]): x for x in _players(main)}
    target_name = _name(main, target, rows.get(target, {}).get("seat"))
    voter_text = "\n".join(f"• {html.escape(_name(main, uid, rows.get(uid, {}).get('seat')))}" for uid in voted) or "• هیچ‌کس"
    await main.bot.send_message(_gid(main), f"📊 <b>نتیجه رای‌گیری برای {html.escape(target_name)}</b>\n\n🗳 تعداد رای: <b>{len(voted)}</b>\n👥 رای‌دهندگان:\n{voter_text}", parse_mode="HTML")
    v["target_index"], v["started_at"], v["deadline"] = idx + 1, None, None
    _put(main, v)
    await _start_target(main)


async def _finish_round(main):
    v = _v(main)
    v["phase"], v["deadline"] = "round_finished", None
    _put(main, v)
    await main.bot.send_message(_gid(main), f"✅ رای‌گیری دور {int(v.get('round') or 1)} به پایان رسید.", reply_markup=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🔄 شروع رای دوم", callback_data="vote:round2"), InlineKeyboardButton("🌙 پایان رای‌گیری", callback_data="vote:end")))


async def _round2(main, callback):
    v = _v(main)
    await callback.message.edit_text("🔄 <b>بازیکنان رای دوم را انتخاب کنید.</b>\n\nانتخاب هدف‌های دور دوم مستقل از حق رای است. برای گرفتن حق رای از «🚫 گرفتن حق رای» استفاده کنید؛ این فهرست شامل همه بازیکنان حاضر است.", reply_markup=_round2_kb(main, v), parse_mode="HTML")
    await callback.answer()


def install(main):
    if getattr(main, "_voting_runtime_installed", False):
        return False
    dp = getattr(main, "dp", None)
    if dp is None:
        return False

    async def only_mod(c):
        if int(c.from_user.id) != int(getattr(main, "moderator_id", -1) or -1):
            await c.answer("⛔ فقط گرداننده دسترسی دارد.", show_alert=True)
            raise CancelHandler()

    async def settings(c):
        await only_mod(c)
        await _settings(main, c)

    async def wait_menu(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text("⏱ <b>زمان انتظار را انتخاب کنید.</b>", reply_markup=_choices("wait", WAIT_OPTIONS, v["wait_seconds"]), parse_mode="HTML")
        await c.answer()

    async def wait_set(c):
        await only_mod(c)
        v = _v(main)
        v["wait_seconds"] = int(c.data.split(":")[-1])
        _put(main, v)
        await _settings(main, c)

    async def duration_menu(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text("⏱ <b>زمان هر رای را انتخاب کنید.</b>", reply_markup=_choices("duration", VOTE_OPTIONS, v["vote_seconds"]), parse_mode="HTML")
        await c.answer()

    async def duration_set(c):
        await only_mod(c)
        v = _v(main)
        v["vote_seconds"] = int(c.data.split(":")[-1])
        _put(main, v)
        await _settings(main, c)

    async def rights(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text("🚫 <b>بازیکنان بدون حق رای</b>", reply_markup=_rights_kb(main, v), parse_mode="HTML")
        await c.answer()

    async def right_toggle(c):
        await only_mod(c)
        uid = int(c.data.split(":")[-1])
        v = _v(main)
        rights_set = _active_rights(v)
        if uid in rights_set:
            rights_set.remove(uid)
        else:
            rights_set.add(uid)
        v["vote_rights_taken"] = sorted(rights_set)
        _put(main, v)
        await rights(c)

    async def mode_menu(c):
        await only_mod(c)
        v = _v(main)
        await c.message.edit_text("🗳 <b>نوع رای‌گیری</b>", reply_markup=_choices("mode", (AUTO, MANUAL), v.get("mode")), parse_mode="HTML")
        await c.answer()

    async def mode_set(c):
        await only_mod(c)
        v = _v(main)
        v["mode"] = c.data.split(":")[-1]
        _put(main, v)
        await _settings(main, c)

    async def start(c):
        await only_mod(c)
        v = _v(main)
        if v.get("phase") in {"waiting", "voting"}:
            await c.answer("⏳ رای‌گیری در حال اجراست.", show_alert=True)
            raise CancelHandler()
        fresh = _default(main)
        fresh.update(wait_seconds=int(v.get("wait_seconds", 20)), vote_seconds=int(v.get("vote_seconds", 20)), mode=v.get("mode", AUTO), vote_rights_taken=list(v.get("vote_rights_taken") or []), selected_round_two=list(v.get("selected_round_two") or []))
        v = fresh
        payload = _state(main)
        payload["voting"] = v
        _save(main, payload)
        rt = _rt(main)
        gid = _gid(main)
        if rt and gid:
            rt.days.set_phase(gid, "voting", extra={"voting": fresh})
        await c.answer("🗳 رای‌گیری آماده شد.")
        await _start_wait(main)
        raise CancelHandler()

    async def cast(c):
        v = _v(main)
        if v.get("phase") != "voting":
            await c.answer("⏳ زمان رای‌گیری این هدف تمام شده است.", show_alert=True)
            raise CancelHandler()
        uid = int(c.from_user.id)
        if uid in _active_rights(v):
            await c.answer("🚫 حق رای شما گرفته شده است.", show_alert=True)
            raise CancelHandler()
        target = int(list(v.get("targets") or [])[int(v.get("target_index") or 0)])
        bucket = list((v.setdefault("votes", {})).setdefault(str(target), []))
        if uid in {int(x) for x in bucket}:
            await c.answer("⚠️ رای شما قبلاً ثبت شده است.", show_alert=True)
            raise CancelHandler()
        bucket.append(uid)
        v["votes"][str(target)] = bucket
        _put(main, v)
        await c.answer("✅ رای شما ثبت شد.")

    async def r2(c):
        await only_mod(c)
        await _round2(main, c)

    async def r2pick(c):
        await only_mod(c)
        uid = int(c.data.split(":")[-1])
        v = _v(main)
        selected = {int(x) for x in (v.get("selected_round_two") or [])}
        if uid in selected:
            selected.remove(uid)
        else:
            selected.add(uid)
        v["selected_round_two"] = sorted(selected)
        _put(main, v)
        await _round2(main, c)

    async def r2confirm(c):
        await only_mod(c)
        v = _v(main)
        selected = [int(x) for x in (v.get("selected_round_two") or [])]
        if not selected:
            await c.answer("حداقل یک بازیکن را انتخاب کنید.", show_alert=True)
            raise CancelHandler()
        v["round"] = 2
        v["targets"] = selected
        v["target_index"] = 0
        v["votes"] = {}
        v["phase"] = "waiting"
        v["deadline"] = None
        _put(main, v)
        await c.answer("🔄 رای دوم آماده شد.")
        await _start_wait(main)
        raise CancelHandler()

    async def end(c):
        await only_mod(c)
        v = _v(main)
        v["phase"], v["deadline"] = "finished", None
        _put(main, v)
        await c.message.edit_text("🏁 <b>رای‌گیری به پایان رسید.</b>", parse_mode="HTML")
        await c.answer()

    async def night(c):
        await only_mod(c)
        rt = _rt(main)
        gid = _gid(main)
        if rt and gid:
            rt.days.start_night(gid)
        await c.answer("🌙 فاز شب شروع شد.")
        raise CancelHandler()

    handlers = [
        (lambda c: c.data == "vote:settings", settings),
        (lambda c: c.data == "vote:wait", wait_menu),
        (lambda c: c.data.startswith("vote:wait:"), wait_set),
        (lambda c: c.data == "vote:duration", duration_menu),
        (lambda c: c.data.startswith("vote:duration:"), duration_set),
        (lambda c: c.data == "vote:rights", rights),
        (lambda c: c.data.startswith("vote:right:"), right_toggle),
        (lambda c: c.data == "vote:mode", mode_menu),
        (lambda c: c.data.startswith("vote:mode:"), mode_set),
        (lambda c: c.data == "vote:start", start),
        (lambda c: c.data == "vote:cast", cast),
        (lambda c: c.data == "vote:round2", r2),
        (lambda c: c.data.startswith("vote:r2pick:"), r2pick),
        (lambda c: c.data == "vote:r2confirm", r2confirm),
        (lambda c: c.data == "vote:end", end),
        (lambda c: c.data == "start_night", night),
    ]
    for predicate, handler in handlers:
        dp.register_callback_query_handler(handler, predicate, state="*")
    main._voting_runtime_installed = True
    return True
