from __future__ import annotations

import html
import logging
from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(main):
    """Single authoritative lobby UI; all callbacks use lv4_* names."""
    dp, bot = main.dp, main.bot

    def front(fn):
        handlers = getattr(dp.callback_query_handlers, "handlers", [])
        for i, h in enumerate(handlers):
            if getattr(h, "callback", None) is fn:
                handlers.insert(0, handlers.pop(i)); return

    def active_game():
        try: return main.persistent_runtime.state.active_game(int(main.group_chat_id))
        except Exception: return None

    def snap():
        game = active_game()
        if not game: return {"players": [], "seats": {}, "waiting": []}
        try: return main.persistent_runtime.state.lobby.snapshot(game["id"])
        except Exception: return {"players": [], "seats": {}, "waiting": []}

    def pname(uid, fallback=None):
        try: return main.display_name(int(uid), fallback) or str(uid)
        except Exception: return fallback or str(uid)

    def mention(uid, fallback=None):
        return f'<a href="tg://user?id={int(uid)}"><b>{html.escape(pname(uid, fallback))}</b></a>'

    async def edit(message, text, markup=None):
        try:
            await message.edit_text(text, reply_markup=markup, parse_mode="HTML")
            return message.message_id
        except Exception:
            try:
                m=await bot.send_message(message.chat.id,text,reply_markup=markup,parse_mode="HTML"); return m.message_id
            except Exception:
                logging.exception("lobby_v4 render failed"); return None

    def scenarios_kb():
        kb=InlineKeyboardMarkup(row_width=1)
        for i,(s,cfg) in enumerate(main.scenarios.items()):
            cfg=cfg or {}; roles=cfg.get("roles") or []; minimum=int(cfg.get("min_players") or 1)
            kb.add(InlineKeyboardButton(f"📝 {s} ({minimum}-{len(roles)})",callback_data=f"lv4_scenario:{i}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت",callback_data="back_main")); return kb

    async def moderators_kb():
        kb=InlineKeyboardMarkup(row_width=1)
        for m in await bot.get_chat_administrators(main.group_chat_id):
            kb.add(InlineKeyboardButton(pname(m.user.id,m.user.full_name),callback_data=f"lv4_moderator:{m.user.id}"))
        kb.add(InlineKeyboardButton("⬅️ بازگشت به سناریو",callback_data="lv4_back_scenario")); return kb

    def config_kb():
        kb=InlineKeyboardMarkup(row_width=1)
        kb.add(InlineKeyboardButton("🚀 ایجاد بازی",callback_data="lv4_create"))
        kb.add(InlineKeyboardButton("⬅️ تغییر سناریو",callback_data="lv4_back_scenario")); return kb

    def lobby_text(s):
        game=active_game() or {}; scenario=main.selected_scenario or game.get("scenario_id") or "---"; mod=main.moderator_id or game.get("moderator_id")
        active=[r for r in s.get("players",[]) if not r.get("is_substitute")]; reserved=[r for r in s.get("players",[]) if r.get("is_substitute")]
        max_seats=int(main.MAX_SEATS or len((main.scenarios.get(scenario) or {}).get("roles",[])))
        out=["🎮 <b>لابی Mafia Nights</b>","",f"📝 سناریو: <b>{html.escape(str(scenario))}</b>",f"🎩 گرداننده: {mention(mod) if mod else '---'}",f"👥 بازیکنان: <b>{len(active)}/{max_seats}</b>","","📋 <b>بازیکنان داخل بازی</b>"]
        if active:
            for r in sorted(active,key=lambda x:(x.get('seat') is None,x.get('seat') or 999)):
                seat=r.get('seat'); line=mention(r['player_id'],r.get('first_name') or r.get('username'))
                out.append(f"{seat:02d}. {line}" if seat is not None else f"▫️ {line} — بدون صندلی")
        else: out.append("— هنوز بازیکنی وارد نشده است.")
        if reserved:
            out += ["","🎟 <b>لیست رزرو</b>"]
            for i,r in enumerate(reserved,1): out.append(f"{i}. {mention(r['player_id'],r.get('first_name') or r.get('username'))}")
        return "\n".join(out)

    def lobby_kb(s):
        active=[r for r in s.get('players',[]) if not r.get('is_substitute')]; max_seats=int(main.MAX_SEATS or 0)
        full=max_seats>0 and len(active)>=max_seats and all(r.get('seat') is not None for r in active)
        kb=InlineKeyboardMarkup(row_width=2)
        # Group inline keyboards are shared. A single toggle avoids contradictory buttons.
        kb.add(InlineKeyboardButton("🎮 ورود / خروج از بازی",callback_data="lv4_toggle_player"))
        kb.add(InlineKeyboardButton("💺 انتخاب صندلی",callback_data="lv4_choose_seat"))
        if full:
            kb.add(InlineKeyboardButton("🎟 رزرو / لغو رزرو",callback_data="lv4_toggle_reserve"))
            kb.add(InlineKeyboardButton("🎭 پخش نقش",callback_data="distribute_roles"))
        kb.add(InlineKeyboardButton("⚙️ مدیریت بازی",callback_data="lv4_manage")); return kb

    async def render_lobby(message):
        s=snap(); mid=await edit(message,lobby_text(s),lobby_kb(s));
        if mid: main.lobby_message_id=mid

    async def new_game(c):
        if c.message.chat.type not in ('group','supergroup'): await c.answer('این گزینه باید داخل گروه اجرا شود.',show_alert=True); return
        if active_game(): await c.answer('⚠️ یک بازی فعال وجود دارد؛ ابتدا آن را لغو کنید.',show_alert=True); return
        main.group_chat_id=c.message.chat.id; main.lobby_active=True; main.game_running=False; main.round_active=False
        main.selected_scenario=None; main.moderator_id=None; main.MAX_SEATS=0; main.players.clear(); main.player_slots.clear(); main.waiting_list.clear(); main._lv4_setup=True
        await edit(c.message,'📝 <b>انتخاب سناریو</b>\n\nابتدا سناریوی بازی را انتخاب کنید.',scenarios_kb()); await c.answer()

    async def scenario(c):
        try:
            scenario=list(main.scenarios.keys())[int(c.data.split(':',1)[1])]; cfg=main.scenarios[scenario] or {}
        except Exception: await c.answer('⚠️ سناریو نامعتبر است.',show_alert=True); return
        main.selected_scenario=scenario; main.MAX_SEATS=len(cfg.get('roles') or [])
        try: main.persistent_runtime.lobby.set_scenario(main.group_chat_id,scenario)
        except Exception: pass
        await edit(c.message,f'📝 سناریو: <b>{html.escape(scenario)}</b>\n\n🎩 <b>انتخاب گرداننده</b>',await moderators_kb()); await c.answer('✅ سناریو انتخاب شد')

    async def moderator(c):
        try: uid=int(c.data.split(':',1)[1])
        except Exception: await c.answer('⚠️ گرداننده نامعتبر است.',show_alert=True); return
        admins={m.user.id for m in await bot.get_chat_administrators(main.group_chat_id)}
        if uid not in admins: await c.answer('گرداننده باید مدیر گروه باشد.',show_alert=True); return
        main.moderator_id=uid
        try: main.addons.register(moderator_id=uid,group_id=main.group_chat_id); main.persistent_runtime.lobby.set_moderator(main.group_chat_id,uid)
        except Exception: pass
        if getattr(main,'_lv4_setup',False):
            await edit(c.message,f'📝 سناریو: <b>{html.escape(str(main.selected_scenario))}</b>\n🎩 گرداننده: <b>{html.escape(pname(uid))}</b>\n\nمرحله ۳ از ۳: ایجاد لابی.',config_kb())
        else: await render_lobby(c.message)
        await c.answer('✅ گرداننده انتخاب شد')

    async def back_scenario(c): main._lv4_setup=True; await edit(c.message,'📝 <b>انتخاب سناریو</b>',scenarios_kb()); await c.answer()

    async def create(c):
        if not main.selected_scenario or not main.moderator_id: await c.answer('⚠️ سناریو و گرداننده الزامی است.',show_alert=True); return
        try:
            main.persistent_runtime.lobby.ensure(main.group_chat_id,main.moderator_id,main.selected_scenario)
            main.persistent_runtime.lobby.set_scenario(main.group_chat_id,main.selected_scenario); main.persistent_runtime.lobby.set_moderator(main.group_chat_id,main.moderator_id)
        except Exception: logging.exception('lobby creation failed'); await c.answer('❌ ایجاد لابی انجام نشد.',show_alert=True); return
        main._lv4_setup=False; main.lobby_active=True; main.game_running=False; main.round_active=False; await render_lobby(c.message); await c.answer('✅ لابی ایجاد شد')

    async def toggle_player(c):
        uid=c.from_user.id; game=active_game()
        if not game or main.game_running or main.round_active: await c.answer('⚠️ لابی فعال نیست.',show_alert=True); return
        s=snap(); active=[r for r in s.get('players',[]) if not r.get('is_substitute')]
        row=next((r for r in active if int(r['player_id'])==uid),None)
        if row:
            seat=row.get('seat'); main.persistent_runtime.leave(main.group_chat_id,uid); main.players.pop(uid,None)
            if seat is not None: main.player_slots.pop(seat,None)
            # Promote first reserve into the freed seat.
            after=snap(); waiting=[r for r in after.get('players',[]) if r.get('is_substitute')]
            if seat is not None and waiting:
                p=waiting[0]; pid=int(p['player_id']); main.persistent_runtime.state.games.remove_player(game['id'],pid); main.persistent_runtime.join(main.group_chat_id,pid,seat,main.moderator_id,main.selected_scenario,substitute=False); main.players[pid]=p.get('first_name') or p.get('username') or pname(pid); main.player_slots[seat]=pid
            await render_lobby(c.message); await c.answer('🚪 از بازی خارج شدید'); return
        if any(int(r['player_id'])==uid for r in s.get('players',[]) if r.get('is_substitute')): await c.answer('🎟 شما در رزرو هستید؛ لغو رزرو را بزنید.',show_alert=True); return
        if len(active)>=int(main.MAX_SEATS or 0): await c.answer('🎟 ظرفیت اصلی پر است؛ رزرو را انتخاب کنید.',show_alert=True); return
        main.persistent_runtime.join(main.group_chat_id,uid,None,main.moderator_id,main.selected_scenario,substitute=False); main.players[uid]=pname(uid,c.from_user.full_name); await render_lobby(c.message); await c.answer('✅ وارد بازی شدید')

    async def choose_seat(c):
        if c.from_user.id not in main.players: await c.answer('ابتدا وارد بازی شوید.',show_alert=True); return
        kb=InlineKeyboardMarkup(row_width=3)
        for seat in range(1,int(main.MAX_SEATS or 0)+1):
            uid=main.player_slots.get(seat); kb.insert(InlineKeyboardButton(f'{seat:02d} '+('✅' if uid==c.from_user.id else ('🔒' if uid else '⬜')),callback_data=f'lv4_seat:{seat}'))
        kb.add(InlineKeyboardButton('⬅️ بازگشت',callback_data='lv4_back')); await edit(c.message,'💺 <b>انتخاب صندلی</b>\n\nیک صندلی آزاد انتخاب کنید.',kb); await c.answer()

    async def seat(c):
        uid=c.from_user.id
        try: seat_no=int(c.data.split(':',1)[1])
        except Exception: await c.answer('صندلی نامعتبر.',show_alert=True); return
        if uid not in main.players or (seat_no in main.player_slots and main.player_slots[seat_no]!=uid): await c.answer('این صندلی قابل انتخاب نیست.',show_alert=True); return
        for old,u in list(main.player_slots.items()):
            if u==uid: main.player_slots.pop(old,None); main.persistent_runtime.lobby.clear_seat(main.group_chat_id,uid)
        main.player_slots[seat_no]=uid; main.persistent_runtime.lobby.assign_seat(main.group_chat_id,uid,seat_no); await render_lobby(c.message); await c.answer(f'✅ صندلی {seat_no} انتخاب شد')

    async def reserve(c):
        uid=c.from_user.id; s=snap(); active=[r for r in s.get('players',[]) if not r.get('is_substitute')]; max_seats=int(main.MAX_SEATS or 0)
        if len(active)<max_seats or len([r for r in active if r.get('seat') is not None])<max_seats: await c.answer('رزرو فقط پس از تکمیل لیست و صندلی‌ها فعال است.',show_alert=True); return
        game=active_game(); reserved=[r for r in s.get('players',[]) if r.get('is_substitute')]
        if any(int(r['player_id'])==uid for r in active): await c.answer('شما در لیست اصلی هستید.',show_alert=True); return
        row=next((r for r in reserved if int(r['player_id'])==uid),None)
        if row: main.persistent_runtime.state.games.remove_player(game['id'],uid); await render_lobby(c.message); await c.answer('❌ لغو رزرو شد'); return
        main.persistent_runtime.join(main.group_chat_id,uid,None,main.moderator_id,main.selected_scenario,substitute=True); await render_lobby(c.message); await c.answer('🎟 به رزرو اضافه شدید')

    async def back(c): await render_lobby(c.message); await c.answer()

    async def manage(c):
        admins={m.user.id for m in await bot.get_chat_administrators(main.group_chat_id)}
        if c.from_user.id not in admins: await c.answer('⛔ این بخش فقط مخصوص مدیران گروه است.',show_alert=True); return
        kb=InlineKeyboardMarkup(row_width=1); kb.add(InlineKeyboardButton('🚫 لغو بازی',callback_data='lv4_cancel')); kb.add(InlineKeyboardButton('📝 تغییر سناریو',callback_data='lv4_change_scenario')); kb.add(InlineKeyboardButton('🎩 تغییر گرداننده',callback_data='lv4_change_moderator')); kb.add(InlineKeyboardButton(f"⚔️ چالش: {'فعال' if getattr(main,'challenge_active',True) else 'غیرفعال'}",callback_data='lv4_toggle_challenge')); kb.add(InlineKeyboardButton('🗑 حذف بازیکن',callback_data='lv4_remove_menu')); kb.add(InlineKeyboardButton('📢 حاضری',callback_data='lv4_ready')); kb.add(InlineKeyboardButton('⬅️ بازگشت به لابی',callback_data='lv4_back')); await edit(c.message,'⚙️ <b>مدیریت بازی</b>',kb); await c.answer()

    async def ready(c):
        if c.from_user.id not in {m.user.id for m in await bot.get_chat_administrators(main.group_chat_id)}: await c.answer('⛔ فقط مدیران گروه.',show_alert=True); return
        game=active_game(); ids=set(((game or {}).get('state') or {}).get('ready_ids') or []); text='📢 <b>حاضری بازیکنان</b>\n\n'
        for r in snap().get('players',[]):
            if not r.get('is_substitute'): text+=f"{'✅' if int(r['player_id']) in ids else '⬜'} {mention(r['player_id'],r.get('first_name') or r.get('username'))}\n"
        kb=InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton('✅ آماده‌ام',callback_data='lv4_ready_me')).add(InlineKeyboardButton('⬅️ مدیریت بازی',callback_data='lv4_manage')); await edit(c.message,text or 'بازیکنی در بازی نیست.',kb); await c.answer()

    async def ready_me(c):
        if not any(int(r['player_id'])==c.from_user.id and not r.get('is_substitute') for r in snap().get('players',[])): await c.answer('فقط بازیکنان داخل بازی.',show_alert=True); return
        game=active_game(); raw=dict((game or {}).get('state') or {}); ids=set(raw.get('ready_ids') or []); ids.add(c.from_user.id); raw['ready_ids']=list(ids); main.persistent_runtime.state.games.update_game(game['id'],state=raw); await ready(c)

    async def cancel(c):
        admins={m.user.id for m in await bot.get_chat_administrators(main.group_chat_id)}
        if c.from_user.id!=main.moderator_id and c.from_user.id not in admins: await c.answer('⛔ دسترسی ندارید.',show_alert=True); return
        game=active_game()
        if game:
            for r in list(main.persistent_runtime.state.games.list_players(game['id'])): main.persistent_runtime.state.games.remove_player(game['id'],r['player_id'])
            main.persistent_runtime.state.games.update_game(game['id'],status='cancelled',state={})
        main.players.clear(); main.player_slots.clear(); main.waiting_list.clear(); main.lobby_active=False; main.game_running=False; main.round_active=False; main.group_chat_id=None; main.selected_scenario=None; main.moderator_id=None; main.MAX_SEATS=0
        try: await c.message.edit_text('🚫 <b>بازی لغو شد.</b>\n\nهمه داده‌های بازی پاک شد.',parse_mode='HTML')
        except Exception: pass
        await c.answer('بازی لغو شد')

    async def change_scenario(c): main._lv4_setup=False; await edit(c,'📝 <b>تغییر سناریو</b>',scenarios_kb()); await c.answer()
    async def change_moderator(c): main._lv4_setup=False; await edit(c,'🎩 <b>تغییر گرداننده</b>',await moderators_kb()); await c.answer()
    async def toggle_challenge(c): main.challenge_active=not getattr(main,'challenge_active',True); await manage(c)

    async def remove_menu(c):
        kb=InlineKeyboardMarkup(row_width=1)
        for r in snap().get('players',[]):
            if r.get('is_substitute'): continue
            uid=int(r['player_id']); seat=r.get('seat'); kb.add(InlineKeyboardButton(f"{seat}. {pname(uid,r.get('first_name') or r.get('username'))}" if seat else pname(uid),callback_data=f'lv4_remove:{uid}'))
        kb.add(InlineKeyboardButton('⬅️ بازگشت',callback_data='lv4_manage')); await edit(c,'🗑 <b>حذف بازیکن</b>\n\nبازیکن را انتخاب کنید.',kb); await c.answer()

    async def remove(c):
        uid=int(c.data.split(':',1)[1]); game=active_game(); row=next((r for r in snap().get('players',[]) if int(r['player_id'])==uid and not r.get('is_substitute')),None)
        if not row: await c.answer('بازیکن پیدا نشد.',show_alert=True); return
        seat=row.get('seat'); main.persistent_runtime.leave(main.group_chat_id,uid); main.players.pop(uid,None); main.player_slots.pop(seat,None) if seat is not None else None
        if seat is not None:
            waiting=[r for r in snap().get('players',[]) if r.get('is_substitute')]
            if waiting:
                p=waiting[0]; pid=int(p['player_id']); main.persistent_runtime.state.games.remove_player(game['id'],pid); main.persistent_runtime.join(main.group_chat_id,pid,seat,main.moderator_id,main.selected_scenario,substitute=False); main.players[pid]=p.get('first_name') or p.get('username') or pname(pid); main.player_slots[seat]=pid
        await render_lobby(c.message); await c.answer('✅ بازیکن حذف شد')

    handlers=[
        (new_game,lambda c:c.data=='new_game'),(scenario,lambda c:str(c.data or '').startswith('lv4_scenario:')),(moderator,lambda c:str(c.data or '').startswith('lv4_moderator:')),(back_scenario,lambda c:c.data=='lv4_back_scenario'),(create,lambda c:c.data=='lv4_create'),(toggle_player,lambda c:c.data=='lv4_toggle_player'),(choose_seat,lambda c:c.data=='lv4_choose_seat'),(seat,lambda c:str(c.data or '').startswith('lv4_seat:')),(reserve,lambda c:c.data=='lv4_toggle_reserve'),(back,lambda c:c.data=='lv4_back'),(manage,lambda c:c.data=='lv4_manage'),(ready,lambda c:c.data=='lv4_ready'),(ready_me,lambda c:c.data=='lv4_ready_me'),(cancel,lambda c:c.data=='lv4_cancel'),(change_scenario,lambda c:c.data=='lv4_change_scenario'),(change_moderator,lambda c:c.data=='lv4_change_moderator'),(toggle_challenge,lambda c:c.data=='lv4_toggle_challenge'),(remove_menu,lambda c:c.data=='lv4_remove_menu'),(remove,lambda c:str(c.data or '').startswith('lv4_remove:')),
    ]
    for fn,flt in handlers: dp.register_callback_query_handler(fn,flt); front(fn)
    main.main_menu_keyboard=lambda: InlineKeyboardMarkup().add(InlineKeyboardButton('🎮 بازی جدید',callback_data='new_game'))
    logging.info('✅ Single authoritative lobby UI v4 installed')
