"""Advanced profile, statistics, history, achievements and privacy UI."""
from __future__ import annotations

import html
import math
from collections import defaultdict
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import text

from player_repository import PlayerRepository


class AdvancedProfile:
    def __init__(self, app, profile_enhancement=None):
        self.app = app
        self.profile_enhancement = profile_enhancement
        self.repo = PlayerRepository()

    def _session(self):
        return self.repo.SessionLocal()

    def _settings(self, uid: int):
        with self._session() as s:
            row = s.execute(text("select * from public.mafia_profile_settings where user_id=:id"), {"id": int(uid)}).mappings().first()
            if row:
                return dict(row)
            s.execute(text("insert into public.mafia_profile_settings(user_id) values (:id) on conflict do nothing"), {"id": int(uid)})
            s.commit()
            return {"user_id": int(uid), "visibility": "public", "show_gender": True, "show_nickname": True, "show_stats": True, "show_history": False, "show_roles": False, "show_group_stats": False}

    def _profile(self, uid: int):
        with self._session() as s:
            row = s.execute(text("select id,username,first_name,last_name,nickname,gender from public.mafia_players where id=:id"), {"id": int(uid)}).mappings().first()
            return dict(row) if row else {"id": int(uid), "nickname": None, "gender": None}

    def _ratings(self, uid: int):
        with self._session() as s:
            rows = s.execute(text("""
                select r.id,r.game_id,r.score,r.result,r.role,r.win_bonus,r.challenge_bonus,
                       r.warning_penalty,r.kick_penalty,g.event_number,g.group_chat_id,g.status,
                       g.finished_at,g.state
                from public.mafia_ratings r
                left join public.mafia_games g on g.id=r.game_id
                where r.user_id=:uid
                order by g.finished_at desc nulls last,r.id desc
            """), {"uid": int(uid)}).mappings().all()
            return [dict(x) for x in rows]

    @staticmethod
    def _name(row: dict[str, Any], uid: int) -> str:
        return str(row.get("nickname") or " ".join(x for x in (row.get("first_name") or "", row.get("last_name") or "") if x).strip() or row.get("username") or uid)

    @staticmethod
    def _emoji_gender(gender: str | None) -> str:
        return "👩" if gender == "female" else "👨" if gender == "male" else ""

    @staticmethod
    def _signed(v: int) -> str:
        return f"+{v}" if v > 0 else str(v)

    @staticmethod
    def _side(row: dict[str, Any]) -> str:
        state = row.get("state") or {}
        if isinstance(state, dict):
            cfg = state.get("scenario_config") or {}
            rules = cfg.get("role_rules") or {}
            role = row.get("role")
            if isinstance(rules, dict) and isinstance(rules.get(role), dict):
                return str(rules[role].get("side") or "نامشخص")
            snap = state.get("scenario") or {}
            rules = snap.get("role_rules") or {}
            if isinstance(rules, dict) and isinstance(rules.get(role), dict):
                return str(rules[role].get("side") or "نامشخص")
            sides = cfg.get("sides") or snap.get("sides") or {}
            if isinstance(sides, dict):
                return str(sides.get(role) or "نامشخص")
        return "نامشخص"

    def _stats(self, uid: int, group_id: int | None = None):
        rows = self._ratings(uid)
        if group_id is not None:
            rows = [r for r in rows if int(r.get("group_chat_id") or 0) == int(group_id)]
        games = len(rows)
        wins = sum(r.get("result") == "win" for r in rows)
        losses = sum(r.get("result") == "loss" for r in rows)
        draws = sum(r.get("result") == "draw" for r in rows)
        win_bonus = sum(int(r.get("win_bonus") or 0) for r in rows)
        challenge = sum(int(r.get("challenge_bonus") or 0) for r in rows)
        warning = sum(int(r.get("warning_penalty") or 0) for r in rows)
        kick = sum(int(r.get("kick_penalty") or 0) for r in rows)
        delta = sum(int(r.get("score") or 0) for r in rows)
        score = 50 + delta
        win_rate = (wins * 100 / games) if games else 0
        best = max((int(r.get("score") or 0) for r in rows), default=0)
        worst = min((int(r.get("score") or 0) for r in rows), default=0)
        avg = delta / games if games else 0
        current_streak = 0
        current_kind = None
        best_win_streak = 0
        best_loss_streak = 0
        streak = 0
        last_result = None
        for r in reversed(rows):
            result = r.get("result")
            if result == last_result and result in {"win", "loss"}:
                streak += 1
            elif result in {"win", "loss"}:
                streak = 1
            else:
                streak = 0
            if result == "win": best_win_streak = max(best_win_streak, streak)
            if result == "loss": best_loss_streak = max(best_loss_streak, streak)
            last_result = result
        if rows:
            for r in rows:
                if r.get("result") in {"win", "loss"}:
                    if current_kind is None:
                        current_kind = r.get("result"); current_streak = 1
                    elif current_kind == r.get("result"):
                        current_streak += 1
                    else:
                        break
        return {"rows": rows,"games": games,"wins": wins,"losses": losses,"draws": draws,"score": score,"delta": delta,
                "win_bonus": win_bonus,"challenge_bonus": challenge,"warning_penalty": warning,"kick_penalty": kick,
                "challenges": challenge // 3,"warnings": warning,"kicks": sum(int(r.get("kick_penalty") or 0) > 0 for r in rows),
                "win_rate": win_rate,"best": best,"worst": worst,"avg": avg,"current_streak": current_streak,
                "current_kind": current_kind,"best_win_streak": best_win_streak,"best_loss_streak": best_loss_streak}

    def _xp(self, st):
        xp = st["games"] * 100 + st["win_bonus"] + st["challenge_bonus"] - st["warning_penalty"] - st["kick_penalty"]
        xp = max(0, int(xp))
        level = 1 + xp // 500
        next_xp = level * 500
        progress = int((xp % 500) * 100 / 500)
        return xp, level, next_xp, progress

    def _achievements(self, st):
        a = []
        checks = [
            ("🎮", "اولین بازی", st["games"] >= 1),
            ("🔥", "۱۰ بازی", st["games"] >= 10),
            ("🏅", "۲۵ بازی", st["games"] >= 25),
            ("👑", "۵۰ بازی", st["games"] >= 50),
            ("🏆", "۱۰ برد", st["wins"] >= 10),
            ("⚔️", "۱۰ چالش", st["challenges"] >= 10),
            ("🧼", "۱۰ بازی بدون تذکر", sum(int(r.get("warning_penalty") or 0) == 0 for r in st["rows"]) >= 10),
            ("📈", "درصد برد بالای ۵۰٪", st["games"] >= 10 and st["win_rate"] >= 50),
            ("🔥", "۵ برد پیاپی", st["best_win_streak"] >= 5),
            ("🛡️", "۵۰ امتیاز مثبت", st["delta"] >= 50),
        ]
        return [(i,e) for i,e,ok in checks if ok]

    def _role_stats(self, rows):
        data = defaultdict(lambda: {"games":0,"wins":0,"losses":0,"draws":0,"delta":0})
        for r in rows:
            role = r.get("role") or "نامشخص"
            x = data[role]; x["games"] += 1; x["delta"] += int(r.get("score") or 0)
            if r.get("result") == "win": x["wins"] += 1
            elif r.get("result") == "loss": x["losses"] += 1
            else: x["draws"] += 1
        return sorted(data.items(), key=lambda x: (-x[1]["games"], x[0]))

    def _side_stats(self, rows):
        data = defaultdict(lambda: {"games":0,"wins":0,"losses":0,"draws":0,"delta":0})
        for r in rows:
            side = self._side(r); x = data[side]; x["games"] += 1; x["delta"] += int(r.get("score") or 0)
            if r.get("result") == "win": x["wins"] += 1
            elif r.get("result") == "loss": x["losses"] += 1
            else: x["draws"] += 1
        return sorted(data.items(), key=lambda x: (-x[1]["games"], x[0]))

    async def advanced(self, callback: types.CallbackQuery):
        uid = int(callback.from_user.id); st = self._stats(uid); xp, level, next_xp, progress = self._xp(st)
        p = self._profile(uid); display = self._name(p, uid); gender = self._emoji_gender(p.get("gender"))
        badges = self._achievements(st)
        text_body = (f"📊 <b>پروفایل و آمار پیشرفته</b>\n\n<b>{gender} {html.escape(display)}</b>\n"
                      f"⭐ امتیاز: <b>{st['score']}</b> | 🏅 رتبه سطح: <b>{level}</b>\n"
                      f"✨ XP: <b>{xp}</b> | پیشرفت سطح: <b>{progress}%</b>\n\n"
                      f"🎮 بازی: {st['games']} | 🏆 برد: {st['wins']} | ❌ باخت: {st['losses']} | 🤝 مساوی: {st['draws']}\n"
                      f"📈 نرخ برد: <b>{st['win_rate']:.1f}%</b>\n"
                      f"🔥 رکورد برد پیاپی: {st['best_win_streak']} | رکورد باخت پیاپی: {st['best_loss_streak']}\n"
                      f"🏅 دستاوردهای بازشده: {len(badges)}")
        kb = InlineKeyboardMarkup(row_width=2)
        kb.row(InlineKeyboardButton("📈 آمار کامل", callback_data="profile:advanced:overview"), InlineKeyboardButton("⭐ امتیاز", callback_data="profile:advanced:score"))
        kb.row(InlineKeyboardButton("🎭 نقش‌ها", callback_data="profile:advanced:roles"), InlineKeyboardButton("⚔️ سایدها", callback_data="profile:advanced:sides"))
        kb.row(InlineKeyboardButton("📜 تاریخچه بازی", callback_data="profile:advanced:history"), InlineKeyboardButton("🏆 دستاوردها", callback_data="profile:advanced:achievements"))
        kb.row(InlineKeyboardButton("👥 آمار گروه", callback_data="profile:advanced:group"), InlineKeyboardButton("🔒 حریم خصوصی", callback_data="profile:advanced:privacy"))
        kb.add(InlineKeyboardButton("⬅️ پروفایل", callback_data="up:profile"))
        await callback.message.edit_text(text_body, parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def overview(self, callback: types.CallbackQuery):
        st = self._stats(callback.from_user.id); text_body = ("📈 <b>آمار کامل</b>\n\n"
            f"🎮 بازی‌ها: {st['games']}\n🏆 برد: {st['wins']}\n❌ باخت: {st['losses']}\n🤝 مساوی: {st['draws']}\n"
            f"📈 نرخ برد: {st['win_rate']:.1f}%\n⭐ امتیاز فعلی: {st['score']}\n"
            f"⬆️ بهترین تغییر بازی: {self._signed(st['best'])}\n⬇️ بدترین تغییر بازی: {self._signed(st['worst'])}\n"
            f"📊 میانگین تغییر هر بازی: {self._signed(round(st['avg']))}\n"
            f"🔥 برد پیاپی فعلی: {st['current_streak'] if st['current_kind']=='win' else 0}\n"
            f"💥 باخت پیاپی فعلی: {st['current_streak'] if st['current_kind']=='loss' else 0}\n"
            f"🏆 بهترین برد پیاپی: {st['best_win_streak']}\n💥 بدترین باخت پیاپی: {st['best_loss_streak']}")
        await self._edit(callback, text_body, "profile:advanced")

    async def score(self, callback: types.CallbackQuery):
        st = self._stats(callback.from_user.id); net = st['win_bonus'] + st['challenge_bonus'] - st['warning_penalty'] - st['kick_penalty']
        text_body = ("⭐ <b>ریز امتیاز</b>\n\n🎯 امتیاز پایه: <b>50</b>\n🏆 برد ساید: <b>+%s</b>\n⚔️ چالش: <b>+%s</b> (%s چالش)\n⚠️ تذکر: <b>-%s</b>\n🚫 کیک: <b>-%s</b>\n📈 تغییر خالص: <b>%s</b>\n⭐ امتیاز فعلی: <b>%s</b>" % (st['win_bonus'],st['challenge_bonus'],st['challenges'],st['warning_penalty'],st['kick_penalty'],self._signed(net),st['score']))
        await self._edit(callback, text_body, "profile:advanced")

    async def roles(self, callback: types.CallbackQuery):
        rows = self._role_stats(self._stats(callback.from_user.id)["rows"])
        lines = ["🎭 <b>عملکرد بر اساس نقش</b>", ""]
        if not rows: lines.append("هنوز سابقه‌ای ثبت نشده است.")
        for role, x in rows[:15]:
            rate = x['wins'] * 100 / x['games'] if x['games'] else 0
            lines.append(f"• <b>{html.escape(str(role))}</b> — {x['games']} بازی | {x['wins']} برد | {rate:.0f}% | Δ {self._signed(x['delta'])}")
        await self._edit(callback, "\n".join(lines), "profile:advanced")

    async def sides(self, callback: types.CallbackQuery):
        rows = self._side_stats(self._stats(callback.from_user.id)["rows"])
        lines = ["⚔️ <b>عملکرد بر اساس ساید</b>", ""]
        if not rows: lines.append("هنوز سابقه‌ای ثبت نشده است.")
        for side, x in rows:
            rate = x['wins'] * 100 / x['games'] if x['games'] else 0
            lines.append(f"• <b>{html.escape(str(side))}</b> — {x['games']} بازی | {x['wins']} برد | {rate:.0f}% | Δ {self._signed(x['delta'])}")
        await self._edit(callback, "\n".join(lines), "profile:advanced")

    async def history(self, callback: types.CallbackQuery):
        rows = self._stats(callback.from_user.id)["rows"][:12]
        lines = ["📜 <b>تاریخچه آخرین بازی‌ها</b>", ""]
        if not rows: lines.append("هنوز سابقه بازی ثبت نشده است.")
        for r in rows:
            result = "🏆 برد" if r.get("result") == "win" else "❌ باخت" if r.get("result") == "loss" else "🤝 مساوی"
            event = r.get("event_number") or "—"; role = r.get("role") or "—"; delta = self._signed(int(r.get("score") or 0))
            lines.append(f"• بازی #{event} — {result} | 🎭 {html.escape(str(role))} | Δ {delta}")
        await self._edit(callback, "\n".join(lines), "profile:advanced")

    async def achievements(self, callback: types.CallbackQuery):
        st = self._stats(callback.from_user.id); unlocked = {x[1] for x in self._achievements(st)}
        all_items = ["اولین بازی","۱۰ بازی","۲۵ بازی","۵۰ بازی","۱۰ برد","۱۰ چالش","۱۰ بازی بدون تذکر","درصد برد بالای ۵۰٪","۵ برد پیاپی","۵۰ امتیاز مثبت"]
        lines = ["🏆 <b>دستاوردها و مدال‌ها</b>", ""]
        for item in all_items: lines.append(("✅ " if item in unlocked else "🔒 ") + item)
        await self._edit(callback, "\n".join(lines), "profile:advanced")

    async def group(self, callback: types.CallbackQuery):
        gid = int(getattr(callback.message.chat, "id", 0)); st = self._stats(callback.from_user.id, gid)
        if not st['games']:
            body = "👥 <b>آمار این گروه</b>\n\nهنوز سابقه‌ای برای شما در این گروه ثبت نشده است."
        else:
            body = (f"👥 <b>آمار این گروه</b>\n\n🎮 بازی: {st['games']}\n🏆 برد: {st['wins']}\n❌ باخت: {st['losses']}\n🤝 مساوی: {st['draws']}\n"
                    f"📈 نرخ برد: {st['win_rate']:.1f}%\n⭐ امتیاز گروهی: {st['score']}\n📊 تغییر خالص: {self._signed(st['delta'])}")
        await self._edit(callback, body, "profile:advanced")

    async def privacy(self, callback: types.CallbackQuery):
        st = self._settings(callback.from_user.id); vis = st.get("visibility", "public")
        labels = {"public":"عمومی","basic":"فقط اطلاعات پایه","private":"خصوصی"}
        kb = InlineKeyboardMarkup(row_width=1)
        for value in ("public","basic","private"):
            mark = "✅ " if vis == value else ""
            kb.add(InlineKeyboardButton(mark + labels[value], callback_data=f"profile:advanced:privacy:set:{value}"))
        kb.add(InlineKeyboardButton("⬅️ آمار پیشرفته", callback_data="profile:advanced"))
        await callback.message.edit_text("🔒 <b>حریم خصوصی پروفایل</b>\n\nعمومی: اطلاعات پایه قابل مشاهده است.\nفقط پایه: آمار تفصیلی مخفی است.\nخصوصی: پروفایل کامل فقط برای خودتان قابل مشاهده است.", parse_mode="HTML", reply_markup=kb); await callback.answer()

    async def set_privacy(self, callback: types.CallbackQuery):
        value = str(callback.data).rsplit(":",1)[-1]
        if value not in {"public","basic","private"}: return await callback.answer("❌ گزینه نامعتبر", show_alert=True)
        with self._session() as s:
            s.execute(text("insert into public.mafia_profile_settings(user_id,visibility) values (:id,:v) on conflict(user_id) do update set visibility=excluded.visibility,updated_at=now()"), {"id": int(callback.from_user.id), "v": value}); s.commit()
        await callback.answer("✅ حریم خصوصی ذخیره شد."); await self.privacy(callback)

    async def _edit(self, callback, body, back):
        await callback.message.edit_text(body, parse_mode="HTML", reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ بازگشت", callback_data=back))); await callback.answer()

    async def public_profile(self, message: types.Message, uid: int):
        stg = self._settings(uid); p = self._profile(uid)
        if stg.get("visibility") == "private" and uid != int(message.from_user.id):
            await message.reply("🔒 این پروفایل خصوصی است."); return
        st = self._stats(uid); display = self._name(p, uid); gender = self._emoji_gender(p.get("gender")) if stg.get("show_gender") else ""
        lines = [f"👤 <b>پروفایل {gender} {html.escape(display)}</b>"]
        if stg.get("show_nickname") and p.get("nickname"): lines.append(f"✏️ نام مستعار: {html.escape(str(p['nickname']))}")
        if stg.get("show_stats") and stg.get("visibility") != "basic":
            lines += [f"🎮 بازی: {st['games']}",f"🏆 برد: {st['wins']}",f"📈 نرخ برد: {st['win_rate']:.1f}%",f"⭐ امتیاز: {st['score']}"]
        elif stg.get("show_stats"):
            lines += [f"🎮 بازی: {st['games']}",f"⭐ امتیاز: {st['score']}"]
        await message.reply("\n".join(lines), parse_mode="HTML")

    async def group_command(self, message: types.Message):
        if message.chat.type not in {"group","supergroup"} or not message.reply_to_message:
            return
        await self.public_profile(message, int(message.reply_to_message.from_user.id)); raise CancelHandler()

    def register(self):
        dp = self.app.dp
        dp.register_callback_query_handler(self.advanced, lambda c: c.data == "profile:advanced")
        dp.register_callback_query_handler(self.overview, lambda c: c.data == "profile:advanced:overview")
        dp.register_callback_query_handler(self.score, lambda c: c.data == "profile:advanced:score")
        dp.register_callback_query_handler(self.roles, lambda c: c.data == "profile:advanced:roles")
        dp.register_callback_query_handler(self.sides, lambda c: c.data == "profile:advanced:sides")
        dp.register_callback_query_handler(self.history, lambda c: c.data == "profile:advanced:history")
        dp.register_callback_query_handler(self.achievements, lambda c: c.data == "profile:advanced:achievements")
        dp.register_callback_query_handler(self.group, lambda c: c.data == "profile:advanced:group")
        dp.register_callback_query_handler(self.privacy, lambda c: c.data == "profile:advanced:privacy")
        dp.register_callback_query_handler(self.set_privacy, lambda c: str(c.data or "").startswith("profile:advanced:privacy:set:"))
        dp.register_message_handler(self.group_command, lambda m: (m.text or "").strip() in {"پروفایل", "/profile"}, content_types=types.ContentTypes.TEXT)
        return self


def install(app, profile_enhancement=None):
    instance = AdvancedProfile(app, profile_enhancement)
    instance.register()
    app._advanced_profile = instance
    return instance
