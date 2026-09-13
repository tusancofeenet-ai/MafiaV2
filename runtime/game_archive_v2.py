"""Game information, history and event recording UI."""
from __future__ import annotations
import html
from datetime import datetime, timezone, timedelta
from functools import wraps
from typing import Any
from aiogram import types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from runtime.game_management import GameManagement

class ArchiveState(StatesGroup):
    waiting_game_number = State()
    waiting_events = State()

SIDE_ICONS = {"city": "🏙️", "mafia": "🌃", "independent": "🏴‍☠️"}
ROLE_SIDE_HINTS = {"پدرخوانده":"mafia","ماتادور":"mafia","گودمن":"mafia","مافیا":"mafia","لئون":"city","دکتر":"city","کنستانتین":"city","همشهری کین":"city","نوستراداموس":"independent","جک":"independent","مستقل":"independent"}

def _dt(v: Any):
    if not v: return None
    if isinstance(v, datetime): return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d=datetime.fromisoformat(str(v).replace("Z","+00:00")); return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception: return None

def _local(v): return v.astimezone(timezone(timedelta(hours=3,minutes=30))) if v else None

def _name(r): return str(r.get("nickname") or r.get("first_name") or r.get("username") or r.get("player_id") or "👤")

def _side(r,state):
    v=str(r.get("side") or "").lower().strip()
    if v in SIDE_ICONS: return v
    v=(state.get("player_sides") or {}).get(str(r.get("player_id")))
    if v in SIDE_ICONS: return v
    role=str(r.get("role") or "")
    for hint,side in ROLE_SIDE_HINTS.items():
        if hint in role: return side
    return "city"

def _winner(g): return str((g.get("state") or {}).get("game_result") or "")

def _winner_label(v): return {"city":"🏙 شهر","mafia":"🔴 مافیا","independent":"🟣 مستقل","draw":"🤝 مساوی"}.get(v,"تعیین نشده")

def _events(g):
    v=(g.get("state") or {}).get("game_events")
    v=dict(v) if isinstance(v,dict) else {}
    v.setdefault("enabled",False); v.setdefault("text",""); v.setdefault("recorded",bool(v.get("text"))); v.setdefault("published",False)
    return v

def _duration(g):
    start=_dt(g.get("started_at")) or _dt(g.get("created_at")); end=_dt(g.get("finished_at")) or datetime.now(timezone.utc)
    if not start:return "---"
    sec=max(0,int((end-start).total_seconds())); h,rem=divmod(sec,3600); m,s=divmod(rem,60)
    return f"{h} ساعت و {m} دقیقه" if h else (f"{m} دقیقه و {s} ثانیه" if m else f"{s} ثانیه")

def _title(g): return f"📓 بازی {int(g.get('event_number') or 1)}" + (" ✅" if str(g.get("status"))=="finished" else " 🟢")

def _options(gid):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("👥 لیست بازی",callback_data=f"game_info:{gid}:players"),InlineKeyboardButton("📊 آمار بازی",callback_data=f"game_info:{gid}:stats"),
        InlineKeyboardButton("📝 اتفاقات بازی",callback_data=f"game_info:{gid}:events"),InlineKeyboardButton("ℹ️ اطلاعات کلی",callback_data=f"game_info:{gid}:overview"),
        InlineKeyboardButton("⬅️ انتخاب بازی",callback_data=f"game_archive:menu:{gid}"))

def _menu():
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🟢 آخرین بازی فعال",callback_data="game_archive:active:0"),InlineKeyboardButton("🏁 آخرین بازی تمام‌شده",callback_data="game_archive:latest:0"),
        InlineKeyboardButton("🔢 وارد کردن شماره بازی",callback_data="game_archive:input:0"),InlineKeyboardButton("📚 فهرست بازی‌ها",callback_data="game_archive:list:0"))

def _history(gs):
    kb=InlineKeyboardMarkup(row_width=1)
    for g in gs: kb.add(InlineKeyboardButton(_title(g),callback_data=f"game_archive:select:{int(g['id'])}"))
    kb.add(InlineKeyboardButton("⬅️ بازگشت",callback_data="game_archive:menu:0")); return kb

def _overview(g):
    state=dict(g.get("state") or {}); start=_local(_dt(g.get("started_at")) or _dt(g.get("created_at"))); end=_local(_dt(g.get("finished_at")))
    scenario=state.get("scenario_name") or g.get("scenario") or g.get("scenario_id") or "---"
    return "\n".join([f"🎮 <b>{_title(g)}</b>","",f"🔢 شماره بازی: <b>{int(g.get('event_number') or 1)}</b>",f"📌 وضعیت: <b>{html.escape(str(g.get('status') or '---'))}</b>",f"🎭 سناریو: <b>{html.escape(str(scenario))}</b>",f"▶️ شروع: <b>{start:%H:%M:%S}</b>" if start else "▶️ شروع: <b>---</b>",f"⏹ پایان: <b>{end:%H:%M:%S}</b>" if end else "⏹ پایان: <b>---</b>",f"⏱ مدت: <b>{_duration(g)}</b>",f"🏆 برنده: <b>{html.escape(_winner_label(_winner(g)))}</b>"])

def _players(g,rows):
    state=dict(g.get("state") or {}); win=_winner(g); out=[f"👥 <b>لیست بازی {int(g.get('event_number') or 1)}</b>",""]
    for r in sorted(rows,key=lambda x:int(x.get("seat") or 999)):
        side=_side(r,state); trophy=" 🏆" if win and win!="draw" and side==win else ""; out.append(f"{SIDE_ICONS.get(side,'👤')} {int(r.get('seat') or 0):02d}. <b>{html.escape(_name(r))}</b> — {html.escape(str(r.get('role') or '---'))}{trophy}")
    return "\n".join(out)

def _stats(g,rows):
    state=dict(g.get("state") or {}); counts={"city":0,"mafia":0,"independent":0}; alive=0
    for r in rows: counts[_side(r,state)]+=1; alive += 1 if bool(r.get("is_alive",True)) else 0
    return f"📊 <b>آمار بازی {int(g.get('event_number') or 1)}</b>\n\n👥 بازیکنان: <b>{len(rows)}</b>\n❤️ زنده: <b>{alive}</b>\n💀 حذف‌شده: <b>{len(rows)-alive}</b>\n\n🏙 شهر: <b>{counts['city']}</b>\n🌃 مافیا: <b>{counts['mafia']}</b>\n🏴‍☠️ مستقل: <b>{counts['independent']}</b>\n\n🏆 نتیجه: <b>{html.escape(_winner_label(_winner(g)))}</b>\n⏱ مدت: <b>{_duration(g)}</b>"

def _events_text(g):
    e=_events(g); text=str(e.get("text") or "").strip() or "فعلا اتفاقات بازی ثبت نشده"; status="🟢 فعال" if e.get("enabled") else "⚪ غیرفعال"
    return f"📝 <b>اتفاقات بازی {int(g.get('event_number') or 1)}</b>\n{status}\n\n{html.escape(text)}"

def install(app: Any) -> bool:
    dp=app.dp
    original=getattr(GameManagement,"panel",None)
    if original and not getattr(GameManagement,"_archive_v2_wrapped",False):
        @wraps(original)
        def panel(self,game_id):
            kb=original(self,game_id); kb.row(InlineKeyboardButton("🎮 اطلاعات بازی",callback_data=f"game_archive:menu:{int(game_id)}"),InlineKeyboardButton("📝 ثبت اتفاقات",callback_data=f"game_archive:events_menu:{int(game_id)}")); return kb
        GameManagement.panel=panel; GameManagement._archive_v2_wrapped=True
    def get_game(gid): return app.runtime.state.games.get_game(int(gid))
    def group_games(gid,finished=False):
        gs=app.runtime.state.games.list_games(int(gid),limit=100); return [g for g in gs if not finished or str(g.get("status"))=="finished"]
    async def allowed(obj,g):
        uid=int(obj.from_user.id)
        if uid==int(g.get("moderator_id") or 0): return True
        gid=int(g.get("group_chat_id") or obj.message.chat.id)
        try:return (await app.bot.get_chat_member(gid,uid)).status in {"creator","administrator"}
        except Exception:return False
    async def archive(cb,state):
        p=str(cb.data or "").split(":")
        if len(p)!=3 or p[0]!="game_archive":return
        action,ref=p[1],int(p[2]); gid=int(cb.message.chat.id)
        if action=="input": await state.update_data(origin=gid); await state.set_state(ArchiveState.waiting_game_number); await cb.message.edit_text("🔢 <b>شماره بازی</b>\n\nشماره بازی را وارد کنید:",parse_mode="HTML"); await cb.answer(); return
        if action=="menu": await cb.message.edit_text("🎮 <b>اطلاعات بازی‌ها</b>\n\nآخرین بازی، آخرین بازی تمام‌شده یا شماره بازی را انتخاب کنید:",parse_mode="HTML",reply_markup=_menu()); await cb.answer(); return
        if action=="active": g=app.runtime.state.active_game(gid)
        elif action=="latest":
            gs=group_games(gid,True); g=gs[0] if gs else None
        elif action=="list":
            gs=group_games(gid,True)[:30]
            if not gs: await cb.answer("ℹ️ آرشیو خالی است.",show_alert=True); return
            if not await allowed(cb,gs[0]): await cb.answer("⛔ دسترسی ندارید.",show_alert=True); return
            await cb.message.edit_text("📚 <b>بازی‌های گذشته</b>\n\nبازی موردنظر را انتخاب کنید:",parse_mode="HTML",reply_markup=_history(gs)); await cb.answer(); return
        elif action=="select": g=get_game(ref)
        elif action=="events_menu":
            g=get_game(ref)
            if not g or not await allowed(cb,g): await cb.answer("❌ بازی پیدا نشد یا دسترسی ندارید.",show_alert=True); return
            await state.update_data(events_game_id=ref); await state.set_state(ArchiveState.waiting_events); await cb.message.edit_text(f"📝 <b>ثبت اتفاقات بازی {int(g.get('event_number') or 1)}</b>\n\nمتن کامل اتفاقات بازی را در یک پیام ارسال کنید.\n\nمثال:\n🌙 شب معارفه\n\n❔ مستقل\nنوستراداموس: ژیار استعلام گرفت و عدد صفر دید و با شهر بازی کرد.\n\n------------\n😴 شب اول\n\n😈 مافیا\nشات/سلاخی: ناصر\nگودمن:\nماتادور: رضا\n\n😊 شهر\nلئون: هلن، متین زد\nدکتر: عارفه، متین سیو داد",parse_mode="HTML"); await cb.answer(); return
        else: await cb.answer("❌ عملیات نامعتبر است.",show_alert=True); return
        if not g: await cb.answer("ℹ️ بازی موردنظر پیدا نشد.",show_alert=True); return
        if not await allowed(cb,g): await cb.answer("⛔ دسترسی ندارید.",show_alert=True); return
        await cb.message.edit_text(_overview(g),parse_mode="HTML",reply_markup=_options(int(g["id"]))); await cb.answer()
    async def info(cb):
        p=str(cb.data or "").split(":");
        if len(p)!=3 or p[0]!="game_info":return
        g=get_game(int(p[1]));
        if not g or not await allowed(cb,g): await cb.answer("❌ بازی پیدا نشد یا دسترسی ندارید.",show_alert=True); return
        rows=app.runtime.state.games.list_players(int(g["id"])); action=p[2]
        output=_players(g,rows) if action=="players" else _stats(g,rows) if action=="stats" else _events_text(g) if action=="events" else _overview(g)
        await cb.message.edit_text(output,parse_mode="HTML",reply_markup=_options(int(g["id"]))); await cb.answer()
    async def number(message,state):
        raw=(message.text or "").strip().replace("٬","").replace(",","")
        if not raw.isdigit() or int(raw)<1: await message.reply("❌ شماره بازی باید یک عدد مثبت باشد."); return
        data=await state.get_data(); games=group_games(int(data.get("origin") or message.chat.id)); g=next((x for x in games if int(x.get("event_number") or 0)==int(raw)),None); await state.finish()
        if not g: await message.reply(f"❌ بازی شماره <b>{int(raw)}</b> پیدا نشد.",parse_mode="HTML",reply_markup=_menu()); return
        if not await allowed(message,g): await message.reply("⛔ دسترسی ندارید."); return
        await message.reply(_overview(g),parse_mode="HTML",reply_markup=_options(int(g["id"])))
    async def events_value(message,state):
        data=await state.get_data(); g=get_game(int(data.get("events_game_id") or 0))
        if not g or not await allowed(message,g): await state.finish(); await message.reply("⛔ دسترسی ندارید."); return
        text=(message.text or "").strip()
        if not text: await message.reply("❌ متن اتفاقات خالی است."); return
        gs=dict(g.get("state") or {}); e=_events(g); e.update({"text":text,"recorded":True,"published":False,"updated_at":datetime.now(timezone.utc).isoformat()}); gs["game_events"]=e; app.runtime.state.games.update_game(int(g["id"]),state=gs); await state.finish(); await message.reply(f"✅ اتفاقات بازی <b>{int(g.get('event_number') or 1)}</b> ذخیره شد.",parse_mode="HTML")
        if e.get("enabled") and str(g.get("status"))=="finished":
            try:
                await app.bot.send_message(int(g["group_chat_id"]),_events_text({**g,"state":gs}),parse_mode="HTML"); e["published"]=True; gs["game_events"]=e; app.runtime.state.games.update_game(int(g["id"]),state=gs)
            except Exception: pass
    dp.register_callback_query_handler(archive,lambda c:str(c.data or "").startswith("game_archive:")); dp.register_callback_query_handler(info,lambda c:str(c.data or "").startswith("game_info:")); dp.register_message_handler(number,state=ArchiveState.waiting_game_number,content_types=types.ContentTypes.TEXT); dp.register_message_handler(events_value,state=ArchiveState.waiting_events,content_types=types.ContentTypes.TEXT)
    return True
