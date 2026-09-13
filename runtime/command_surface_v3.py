from __future__ import annotations
import html
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.dispatcher.handler import CancelHandler
from runtime import voting_runtime as vr
from runtime import stable_round_engine as sre
from runtime.game_end import _summary_text, _main_markup

ALIASES={"vote":{"رای گیری","رأی گیری","رای‌گیری","رأی‌گیری"},"end":{"پایان بازی","اتمام بازی"},"chief":{"سردست","تغییر سردست"},"remove":{"حذف بازیکن"},"start":{"شروع دور"}}
def norm(s): return " ".join((s or "").strip().replace("‌"," ").split()).casefold()
def install(app):
    if getattr(app,"_command_surface_v3",False): return False
    app._command_surface_v3=True
    dp=app.dp
    def resolve(s):
        n=norm(s)
        for k,v in ALIASES.items():
            if n in {norm(x) for x in v}: return k
    def game(gid): return app.runtime.state.active_game(int(gid))
    async def manager(m,g):
        if int(m.from_user.id)==int(g.get("moderator_id") or -1): return True
        try:return (await app.bot.get_chat_member(m.chat.id,m.from_user.id)).status in {"creator","administrator"}
        except Exception:return False
    async def command(m):
        c=resolve(m.text)
        if not c:return
        if m.chat.type not in {"group","supergroup"}: await m.reply("ℹ️ این دستور فقط داخل گروه بازی است."); raise CancelHandler()
        g=game(m.chat.id)
        if not g or not await manager(m,g): await m.reply("⛔ بازی فعال نیست یا دسترسی ندارید."); raise CancelHandler()
        if c=="vote":
            v=vr._v(app); await m.reply(f"🗳 <b>تنظیمات رای‌گیری</b>\n\n⏱ انتظار: {v['wait_seconds']} ثانیه\n⏱ هر رای: {v['vote_seconds']} ثانیه\n🚫 بدون حق رای: {len(v.get('vote_rights_taken',[]))}\n🗳 نوع: {'خودکار' if v.get('mode')==vr.AUTO else 'دستی'}",parse_mode="HTML",reply_markup=vr._settings_kb(v)); raise CancelHandler()
        if c=="end":
            if str(g.get("status"))!="running": await m.reply("❌ فقط بازی در حال اجرا قابل اتمام است."); raise CancelHandler()
            state=dict(g.get("state") or {}); await m.reply(_summary_text(g),parse_mode="HTML",reply_markup=_main_markup(int(g['id']),state.get('game_result'),bool((state.get('game_events') or {}).get('enabled')))); raise CancelHandler()
        if c=="chief":
            target=m.reply_to_message.from_user if m.reply_to_message else None
            if not target: await m.reply("❗ برای تغییر سردست روی پیام مدیر موردنظر ریپلای کنید."); raise CancelHandler()
            admins={int(a.user.id) for a in await app.bot.get_chat_administrators(m.chat.id)}
            if int(target.id) not in admins: await m.reply("❌ سردست باید مدیر گروه باشد."); raise CancelHandler()
            app.runtime.state.games.update_game(g["id"],moderator_id=int(target.id)); app.moderator_id=int(target.id)
            await m.reply(f"🎩 سردست به <b>{html.escape(target.full_name)}</b> تغییر کرد.",parse_mode="HTML"); raise CancelHandler()
        if c=="remove":
            target=m.reply_to_message.from_user if m.reply_to_message else None
            if not target: await m.reply("❗ برای حذف بازیکن روی پیام او ریپلای کنید."); raise CancelHandler()
            row=next((r for r in app.runtime.state.games.list_players(g['id']) if int(r['player_id'])==int(target.id)),None)
            if not row: await m.reply("❌ بازیکن پیدا نشد."); raise CancelHandler()
            app.runtime.state.games.set_player_seat(g['id'],int(target.id),None); app.runtime.state.games.set_player_status(g['id'],int(target.id),"removed")
            await m.reply(f"🗑 <b>{html.escape(str(row.get('nickname') or target.full_name))}</b> از بازی حذف شد.",parse_mode="HTML"); raise CancelHandler()
        if c=="start":
            if str(g.get("status")) not in {"running","paused"}: await m.reply("❌ بازی در حال اجرا نیست."); raise CancelHandler()
            if getattr(app,"_stable_day_active",False) and not getattr(app,"_stable_day_ended",False): await m.reply("⚠️ این دور قبلاً شروع شده است."); raise CancelHandler()
            sre._ensure(app); base=sre._base_order(app)
            if not base: await m.reply("⚠️ بازیکنی برای شروع دور وجود ندارد."); raise CancelHandler()
            app._stable_day_active=True; app._stable_day_ended=False; app._stable_phase="normal"; app._stable_normal_order=list(base); app._stable_extra_seats=set(); app._stable_extra_used=set(); app._stable_challenge_used=set(); app._stable_challenge_locked=set(); app.turn_order=list(base); app.current_turn_index=0; app.challenge_mode=False
            await sre._advance(app); await m.reply("✅ دور شروع شد."); raise CancelHandler()
    dp.register_message_handler(command,lambda m:resolve(getattr(m,"text",None)) is not None,content_types="text",state="*")
    reg=getattr(getattr(dp,"message_handlers",None),"handlers",[])
    for i,item in enumerate(reg):
        if getattr(item,"handler",None) is command: reg.insert(0,reg.pop(i)); break
    return True
