from __future__ import annotations

import html
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from repositories.scenario_repository import ScenarioRepository


def install(main):
    if getattr(main, "_lobby_ui_v9_installed", False):
        return False
    main._lobby_ui_v9_installed = True
    repo = ScenarioRepository()
    dp = main.dp
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if reg is None:
        return False

    def rows(key):
        data = [(r, str(r.get("name") or "")) for r in repo.list_active()]
        if key == "father": data = [(r,n) for r,n in data if n.startswith("پدرخوانده-")]
        elif key == "classic": data = [(r,n) for r,n in data if n.startswith("کلاسیک ")]
        elif key == "don": data = [(r,n) for r,n in data if n == "کاپو" or "دن مافیا" in [str(x) for x in (r.get("roles") or [])]]
        elif key == "gambler": data = [(r,n) for r,n in data if n in {"قمار باز", "قمارباز"}]
        elif key == "zodiac": data = [(r,n) for r,n in data if n == "زودیاک"]
        elif key == "other":
            popular = {"پدرخوانده-جک","پدرخوانده-شرلوک","پدرخوانده-نوسترا","کلاسیک 12","کلاسیک 13","قمار باز","قمارباز","زودیاک","کاپو"}
            data = [(r,n) for r,n in data if n not in popular]
        return data

    def catalog():
        kb = InlineKeyboardMarkup(row_width=3)
        for label,key in (("👑 پدرخوانده","father"),("🎭 کلاسیک","classic"),("🎩 دن","don"),("🎲 قمارباز","gambler"),("☢️ زودیاک","zodiac")):
            kb.insert(InlineKeyboardButton(label, callback_data=f"lv9_cat:{key}"))
        kb.add(InlineKeyboardButton("📚 سایر سناریوها", callback_data="lv9_cat:other"))
        return kb

    def scenario_kb(key):
        kb = InlineKeyboardMarkup(row_width=3)
        for row,n in rows(key):
            sid = int(row["id"])
            label = n.replace("پدرخوانده-", "") if key == "father" else (n.replace("کلاسیک ", "") + " نفره" if key == "classic" else ("کاپو" if key == "don" and n == "کاپو" else n))
            kb.insert(InlineKeyboardButton(f"{label} ({len(row.get('roles') or [])})", callback_data=f"lv9_s:{key}:{sid}"))
        kb.row(InlineKeyboardButton("⬅️ سناریوهای محبوب", callback_data="lv9_catalog"))
        return kb

    async def show_catalog(c):
        await c.message.edit_text("📝 <b>انتخاب سناریو</b>\n\n⭐ دسته‌بندی سناریوها:", parse_mode="HTML", reply_markup=catalog())
        await c.answer()
        raise CancelHandler()

    async def new(c):
        if getattr(main, "game_running", False) or getattr(main, "round_active", False):
            await c.answer("⚠️ بازی در حال اجراست.", show_alert=True); raise CancelHandler()
        try:
            if getattr(main, "runtime", None): main.runtime.lobby.ensure(int(c.message.chat.id))
        except Exception: pass
        main.group_chat_id = int(c.message.chat.id); main.lobby_active = True; main.game_running = False; main.round_active = False
        await show_catalog(c)

    async def category(c):
        key = str(c.data).split(":",1)[1]
        title = {"father":"👑 <b>پدرخوانده</b>","classic":"🎭 <b>کلاسیک</b>","don":"🎩 <b>دن</b>","gambler":"🎲 <b>قمارباز</b>","zodiac":"☢️ <b>زودیاک</b>","other":"📚 <b>سایر سناریوها</b>"}.get(key,"📝 <b>سناریوها</b>")
        await c.message.edit_text(f"{title}\n\nنسخه موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=scenario_kb(key))
        await c.answer(); raise CancelHandler()

    async def choose(c):
        p = str(c.data).split(":")
        if len(p) != 3: return
        key,sid = p[1],int(p[2])
        row = repo.get_by_id(sid)
        if not row or not row.get("is_active",True):
            await c.answer("❌ سناریو معتبر نیست.", show_alert=True); raise CancelHandler()
        selected = str(row["name"]); gid = int(c.message.chat.id)
        try:
            if getattr(main,"runtime",None): main.runtime.lobby.set_scenario(gid, selected)
            game = main.runtime.state.active_game(gid)
            if game:
                state = dict(game.get("state") or {}); state["scenario_name"] = selected; state["scenario_id"] = sid
                main.runtime.state.games.update_game(game["id"], scenario_id=sid, state=state)
        except Exception:
            await c.answer("❌ ذخیره سناریو انجام نشد.", show_alert=True); raise CancelHandler()
        main.selected_scenario = selected; main.MAX_SEATS = len(row.get("roles") or [])
        if getattr(main,"_lv6_change_scenario",False) and getattr(main,"moderator_id",None):
            main._lv6_change_scenario=False; await c.message.edit_text(f"✅ سناریو «{html.escape(selected)}» تغییر کرد."); await c.answer(); raise CancelHandler()
        admins = await main.bot.get_chat_administrators(gid); kb=InlineKeyboardMarkup(row_width=3)
        for a in admins: kb.insert(InlineKeyboardButton(a.user.full_name[:24], callback_data=f"lv9_m:{int(a.user.id)}"))
        await c.message.edit_text(f"📝 <b>{html.escape(selected)}</b>\n\n🎩 <b>انتخاب گرداننده</b>", parse_mode="HTML", reply_markup=kb)
        await c.answer("✅ سناریو انتخاب شد"); raise CancelHandler()

    async def change(c):
        admins={int(a.user.id) for a in await main.bot.get_chat_administrators(int(c.message.chat.id))}
        if int(c.from_user.id) not in admins: await c.answer("⛔ فقط مدیران.",show_alert=True); raise CancelHandler()
        main._lv6_change_scenario=True; await show_catalog(c)

    async def moderator(c):
        gid=int(c.message.chat.id); uid=int(str(c.data).split(":")[1]); admins={int(a.user.id) for a in await main.bot.get_chat_administrators(gid)}
        if uid not in admins: await c.answer("❌ گرداننده باید مدیر گروه باشد.",show_alert=True); raise CancelHandler()
        if getattr(main,"runtime",None): main.runtime.lobby.set_moderator(gid,uid)
        main.moderator_id=uid; main.group_chat_id=gid
        try:
            game=main.runtime.state.active_game(gid)
            if game: main.runtime.state.games.update_game(game["id"], moderator_id=uid)
        except Exception: pass
        await c.message.edit_text("✅ <b>لابی آماده شد.</b>",parse_mode="HTML"); await c.answer(); raise CancelHandler()

    for fn,flt in ((new,lambda c:c.data=="lv6_new"),(show_catalog,lambda c:c.data=="lv9_catalog"),(category,lambda c:str(c.data).startswith("lv9_cat:")),(choose,lambda c:str(c.data).startswith("lv9_s:")),(moderator,lambda c:str(c.data).startswith("lv9_m:")),(change,lambda c:c.data=="lv6_change_s")):
        dp.register_callback_query_handler(fn,flt,state="*")
        for i,item in enumerate(reg):
            if getattr(item,"callback",None) is fn: reg.insert(0,reg.pop(i)); break
    return True
