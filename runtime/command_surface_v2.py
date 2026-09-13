from __future__ import annotations

import html
from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text
from player_repository import PlayerRepository

ALIASES = {
    "stats": {"آمار","امار","آمار من","امار من"},
    "nickname_set": {"تنظیم مستعار","تنظیم نام مستعار"},
    "nickname_del": {"حذف مستعار","حذف نام مستعار"},
    "nickname_get": {"نام مستعار","دیدن نام مستعار"},
    "nickname_list": {"لیست مستعار","لیست نامهای مستعار","لیست نام‌های مستعار"},
    "mute": {"سکوت"}, "unmute": {"حذف سکوت"}, "extra": {"ترن اضافه","ترن اضافهم"},
    "sub": {"جایگزین","/sub"}, "sub_list": {"لیست جایگزین","لیست جایگزین‌ها"}, "sub_del": {"حذف جایگزین"},
    "vote": {"رای گیری","رأی گیری","رای‌گیری","رأی‌گیری"}, "end": {"پایان بازی","اتمام بازی"},
    "night": {"فاز شب","شروع فاز شب"}, "day": {"شروع روز","شروع فاز روز"}, "chief": {"سردست","تغییر سردست"},
    "challenge_settings": {"تنظیم چالش"}, "next_settings": {"تنظیم نکست"}, "remove": {"حذف بازیکن"},
    "next": {"نکست"}, "start_round": {"شروع دور"},
}

def norm(s): return " ".join((s or "").strip().replace("‌"," ").split()).casefold()
def resolve(s):
    n=norm(s)
    for k,v in ALIASES.items():
        if n in {norm(x) for x in v}: return k
    return None

def install(app):
    if getattr(app,"_command_surface_v2",False): return False
    app._command_surface_v2=True
    dp=app.dp
    def game(gid): return app.runtime.state.active_game(int(gid))
    async def manager(m,g=None):
        if g and int(m.from_user.id)==int(g.get("moderator_id") or -1): return True
        try: return (await app.bot.get_chat_member(m.chat.id,m.from_user.id)).status in {"creator","administrator"}
        except Exception:return False
    def rows(g): return app.runtime.state.games.list_players(g["id"]) if g else []
    def pname(r): return str(r.get("nickname") or r.get("first_name") or r.get("username") or r.get("player_id") or "👤")
    async def stats(m):
        uid=int(m.reply_to_message.from_user.id if m.reply_to_message else m.from_user.id)
        try:
            with PlayerRepository().SessionLocal() as s:
                rs=s.execute(text("select result,score,win_bonus,challenge_bonus,warning_penalty,kick_penalty from public.mafia_ratings where user_id=:id"),{"id":uid}).mappings().all()
            games=len(rs); wins=sum(r["result"]=="win" for r in rs); losses=sum(r["result"]=="loss" for r in rs); draws=sum(r["result"]=="draw" for r in rs)
            delta=sum(int(r.get("score") or 0) for r in rs); score=50+delta
            await m.reply(f"📊 <b>آمار بازی</b>\n\n🎮 بازی: <b>{games}</b>\n🏆 برد: <b>{wins}</b>\n❌ باخت: <b>{losses}</b>\n🤝 مساوی: <b>{draws}</b>\n⭐ امتیاز: <b>{score}</b>\n📈 نرخ برد: <b>{(wins*100/games if games else 0):.1f}%</b>",parse_mode="HTML")
        except Exception:
            await m.reply("❌ نمایش اطلاعات آمار انجام نشد.")
    async def nickname(m,kind):
        g=game(m.chat.id) if m.chat.type in {"group","supergroup"} else None
        if kind=="list":
            if m.chat.type not in {"group","supergroup"} or not await manager(m,g): await m.reply("⛔ فقط مدیر گروه."); return
            with PlayerRepository().SessionLocal() as s: rs=s.execute(text("select id,nickname from public.mafia_players where nickname is not null and trim(nickname)<>'' order by nickname" )).mappings().all()
            await m.reply("📛 <b>لیست نام‌های مستعار</b>\n\n"+"\n".join(f"• {html.escape(str(r['nickname']))} — <code>{r['id']}</code>" for r in rs) if rs else "📛 نام مستعاری ثبت نشده است.",parse_mode="HTML"); return
        target=m.reply_to_message.from_user if m.reply_to_message else None
        if not target: await m.reply("❗ این دستور باید با ریپلای روی کاربر استفاده شود."); return
        if kind=="get":
            with PlayerRepository().SessionLocal() as s: v=s.execute(text("select nickname from public.mafia_players where id=:id"),{"id":target.id}).scalar()
            await m.reply(f"📛 نام مستعار: <b>{html.escape(str(v))}</b>" if v else "ℹ️ نام مستعاری ثبت نشده است.",parse_mode="HTML"); return
        if not await manager(m,g): await m.reply("⛔ فقط مدیر گروه."); return
        if kind=="del":
            with PlayerRepository().SessionLocal() as s: s.execute(text("update public.mafia_players set nickname=null,updated_at=now() where id=:id"),{"id":target.id}); s.commit()
            await m.reply("🗑 نام مستعار حذف شد."); return
        raw=(m.text or "").strip().replace("‌"," "); value=raw.split(" ",2)[-1].strip() if len(raw.split())>2 else ""
        if not value: await m.reply("❗ نام مستعار را بعد از دستور بنویسید."); return
        with PlayerRepository().SessionLocal() as s:
            s.execute(text("insert into public.mafia_players(id,username,first_name,last_name,nickname,created_at,updated_at) values(:id,:u,:f,:l,:n,now(),now()) on conflict(id) do update set nickname=:n,updated_at=now()"),{"id":target.id,"u":target.username,"f":target.first_name,"l":target.last_name,"n":value}); s.commit()
        await m.reply(f"✅ نام مستعار <b>{html.escape(value)}</b> ثبت شد.",parse_mode="HTML")
    async def simple_game_action(m,cmd):
        if m.chat.type not in {"group","supergroup"}: await m.reply("ℹ️ این دستور فقط داخل گروه بازی است."); return
        g=game(m.chat.id)
        if not g or not await manager(m,g): await m.reply("⛔ بازی فعال نیست یا دسترسی ندارید."); return
        st=dict(g.get("state") or {})
        if cmd in {"mute","unmute","extra"}:
            target=m.reply_to_message.from_user if m.reply_to_message else None
            if not target: await m.reply("❗ روی پیام بازیکن ریپلای کنید."); return
            uid=int(target.id); seat=next((int(r["seat"]) for r in rows(g) if int(r["player_id"])==uid and r.get("seat") is not None),None)
            if seat is None: await m.reply("❌ بازیکن فعال پیدا نشد."); return
            key={"mute":"_gm_muted_next_round","unmute":"_gm_muted_next_round","extra":"_gm_extra_next_round"}[cmd]
            current=set(getattr(app,key,set()) or set())
            if cmd=="mute": current.add(seat); app._gm_muted_next_round=current
            elif cmd=="unmute": current.discard(seat); app._gm_muted_next_round=current
            else: current.add(seat); app._gm_extra_next_round=current
            await m.reply("✅ تنظیم شد."); return
        if cmd in {"night","day"}:
            try:
                if cmd=="night": app.runtime.day.start_night(m.chat.id)
                else: app.runtime.day.start_new_day(m.chat.id)
                await m.reply("✅ فاز تغییر کرد.")
            except Exception as e: await m.reply(f"❌ تغییر فاز انجام نشد: {html.escape(str(e))}")
            return
        if cmd=="next_settings":
            ns=dict(st.get("next_settings") or {"allow_players_next":True,"allow_moderator_next":True,"anti_spam":True});
            kb=InlineKeyboardMarkup(row_width=1)
            for k,t in (("allow_players_next","👤 نکست بازیکن"),("allow_moderator_next","🎩 نکست گرداننده"),("anti_spam","🛡 ضداسپم")): kb.add(InlineKeyboardButton(f"{t}: {'فعال' if ns.get(k,True) else 'غیرفعال'}",callback_data=f"mgmt:{g['id']}:next_toggle:{k}"))
            await m.reply("⏭ <b>تنظیم نکست</b>",parse_mode="HTML",reply_markup=kb); return
        if cmd=="challenge_settings":
            enabled=bool(getattr(app,"challenge_enabled",{}).get(int(m.chat.id),True)); await m.reply(f"⚔️ وضعیت چالش: <b>{'فعال' if enabled else 'غیرفعال'}</b>\nبرای تغییر از پنل مدیریت استفاده کنید.",parse_mode="HTML"); return
        if cmd=="next":
            active=getattr(app,"_active",lambda:None)()
            if active is None:
                try: active=int(app.turn_order[app.current_turn_index])
                except Exception: active=None
            if active is None: await m.reply("⚠️ نوبت فعالی نیست."); return
            if int(m.from_user.id) not in {int((getattr(app,"player_slots",{}) or {}).get(active) or -1),int(getattr(app,"moderator_id",-2) or -2)}: await m.reply("⛔ اجازه نکست ندارید."); return
            try:
                app.current_turn_index+=1; await app._advance(app) if hasattr(app,"_advance") else None
            except Exception: pass
            await m.reply("⏭ نکست اجرا شد."); return
        await m.reply("ℹ️ این دستور به پنل مدیریت متصل است؛ از دکمه‌های مدیریت برای عملیات پیچیده استفاده کنید.")
    async def command(m):
        c=resolve(m.text)
        if c=="stats": await stats(m)
        elif c.startswith("nickname_"): await nickname(m,{"nickname_set":"set","nickname_del":"del","nickname_get":"get","nickname_list":"list"}[c])
        elif c in {"mute","unmute","extra","night","day","challenge_settings","next_settings","next"}: await simple_game_action(m,c)
        elif c in {"sub","sub_list","sub_del"}:
            g=game(m.chat.id)
            if not g or not await manager(m,g): await m.reply("⛔ دسترسی ندارید."); return
            target=m.reply_to_message.from_user if m.reply_to_message else None
            if c=="sub" and target:
                app.runtime.state.games.add_player(g["id"],target.id,status="waiting",is_substitute=True); await m.reply("✅ بازیکن به لیست جایگزین اضافه شد.")
            elif c=="sub_list":
                rs=[r for r in rows(g) if r.get("is_substitute")]; await m.reply("🔄 <b>لیست جایگزین</b>\n\n"+"\n".join(f"• {pname(r)}" for r in rs) if rs else "🔄 لیست جایگزین خالی است.",parse_mode="HTML")
            elif c=="sub_del" and target: app.runtime.state.games.remove_player(g["id"],target.id); await m.reply("🗑 جایگزین حذف شد.")
        elif c in {"vote","end","chief","remove","start_round"}: await m.reply("ℹ️ این دستور در پنل مدیریت موجود است و باید با همان سطح دسترسی اجرا شود.")
    dp.register_message_handler(command,lambda m: resolve(getattr(m,"text",None)) is not None,content_types=types.ContentTypes.TEXT,state="*")
    reg=getattr(getattr(dp,"message_handlers",None),"handlers",[])
    for i,item in enumerate(reg):
        if getattr(item,"handler",None) is command: reg.insert(0,reg.pop(i)); break
    return True
