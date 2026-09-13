"""MafiaNights clean Telegram application target."""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils import executor
from aiogram.utils.exceptions import MessageCantBeEdited, MessageNotModified, MessageToEditNotFound

from mafia_addons import MafiaAddons
from player_service import player_service
from runtime.game_runtime import PersistentGameRuntime
from runtime.game_state_machine import Phase
from runtime.ephemeral_recovery import EphemeralRecoveryManager

DEFAULT_TURN_DURATION = 120
DEFAULT_CHALLENGE_DURATION = 60
ALLOWED_GROUP_ID = int(os.getenv("ALLOWED_GROUP_ID", "0") or 0)
SCENARIOS_FILE = Path("scenarios.json")

@dataclass
class TelegramRuntime:
    group_chat_id: Optional[int] = None
    lobby_message_id: Optional[int] = None
    game_message_id: Optional[int] = None
    current_turn_message_id: Optional[int] = None
    waiting_message_id: Optional[int] = None
    turn_timer_task: Optional[asyncio.Task] = None
    last_next_at: float = 0.0
    recovered_turn_plans: dict[int, dict[str, Any]] = field(default_factory=dict)
    recovered_challenges: list[dict[str, Any]] = field(default_factory=list)

class MafiaApplication:
    """Clean application shell around the persistent Mafia runtime."""
    def __init__(self, token: str):
        self.bot = Bot(token=token, parse_mode="HTML")
        self.dp = Dispatcher(self.bot, storage=MemoryStorage())
        self.runtime = PersistentGameRuntime()
        self.ui = TelegramRuntime()
        self.addons = MafiaAddons(self.bot)
        self.scenarios = self._load_scenarios()
        self.challenge_enabled: dict[int, bool] = {}
        self.roles: dict[int, dict[int, str]] = {}
        self.pending_event_number: dict[tuple[int, int], int] = {}
        self.recovery = EphemeralRecoveryManager(self.runtime, self)
        self._register_handlers()

    @staticmethod
    def _load_scenarios() -> dict[str, dict[str, Any]]:
        if SCENARIOS_FILE.exists():
            try:
                data = json.loads(SCENARIOS_FILE.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                logging.exception("failed to load scenarios")
        return {"سناریو کلاسیک": {"roles": ["مافیا", "مافیا", "شهروند", "شهروند", "شهروند"], "min_players": 5}}

    def _scenario_roles(self, scenario: str) -> list[str]:
        return list((self.scenarios.get(scenario) or {}).get("roles") or [])

    def _max_players(self, scenario: Optional[str]) -> int:
        return len(self._scenario_roles(scenario)) if scenario else 0

    async def _ensure_player(self, user: types.User) -> None:
        try: player_service.ensure_player(user)
        except Exception: logging.exception("player profile sync failed for %s", user.id)

    def _name(self, user_id: int, fallback: str = "❓") -> str:
        try: return player_service.display_name(user_id, fallback)
        except Exception: return fallback

    def _snapshot(self, group_id: int) -> dict[str, Any]: return self.runtime.snapshot(group_id)

    def _players_by_seat(self, group_id: int) -> dict[int, dict[str, Any]]:
        snapshot = self.runtime.lobby_snapshot(group_id)
        return {int(row["seat"]): row for row in snapshot.get("players", []) if row.get("seat") is not None and row.get("status") in {"active", "substitute"}}

    def _turn_order(self, group_id: int) -> list[int]:
        game = self.runtime.state.active_game(group_id)
        return [int(x) for x in ((game or {}).get("state") or {}).get("turn_order") or []]

    def _current_index(self, group_id: int) -> int: return int((self.runtime.state.active_game(group_id) or {}).get("current_turn_index") or 0)

    def _persist_turn_pointer(self, group_id: int, order: list[int], index: int) -> None:
        game = self.runtime.state.active_game(group_id)
        if not game: return
        state = dict(game.get("state") or {}); state["turn_order"] = [int(x) for x in order]
        seat = order[index] if order and 0 <= index < len(order) else None
        self.runtime.state.games.update_game(game["id"], state=state, current_turn_index=index, current_turn_seat=seat)

    def _keyboard_main(self):
        return InlineKeyboardMarkup(row_width=1).add(InlineKeyboardButton("🎮 بازی جدید", callback_data="new_game"), InlineKeyboardButton("📖 راهنما", callback_data="help"))

    def _keyboard_lobby(self, scenario: Optional[str], group_id: int):
        kb = InlineKeyboardMarkup(row_width=5); game = self.runtime.state.active_game(group_id) or {}; event_number = game.get("event_number") or 1; occupied = self._players_by_seat(group_id)
        for seat in range(1, self._max_players(scenario) + 1): kb.insert(InlineKeyboardButton(str(seat) if seat not in occupied else f"{seat} ({self._name(int(occupied[seat]['player_id']))})", callback_data=f"slot_{seat}"))
        kb.row(InlineKeyboardButton("✅ ورود", callback_data="join_game"), InlineKeyboardButton("❌ خروج", callback_data="leave_game"))
        kb.add(InlineKeyboardButton("📝 انتخاب سناریو", callback_data="choose_scenario"), InlineKeyboardButton(f"🔢 شماره بازی: {event_number}", callback_data="set_event_number"), InlineKeyboardButton("🚫 لغو بازی", callback_data="cancel_game"))
        return kb

    async def _render_lobby(self, group_id: int):
        snapshot = self.runtime.lobby_snapshot(group_id); game = snapshot.get("game") or self.runtime.state.active_game(group_id) or {}; scenario = game.get("scenario_id"); event_number = game.get("event_number") or 1; players = snapshot.get("players") or []
        text = "📋 <b>لابی Mafia Nights</b>\n\n" + f"🔢 <b>شماره بازی:</b> {event_number}\n" + f"🗓 سناریو: {html.escape(str(scenario or 'انتخاب نشده'))}\n\n"
        for row in sorted(players, key=lambda x: (x.get("seat") is None, x.get("seat") or 999)):
            uid = int(row["player_id"]); seat = row.get("seat"); text += f"• <a href='tg://user?id={uid}'>{html.escape(self._name(uid))}</a> — {'رزرو' if seat is None else f'صندلی {seat}'}\n"
        try:
            if self.ui.lobby_message_id: await self.bot.edit_message_text(text, group_id, self.ui.lobby_message_id, parse_mode="HTML", reply_markup=self._keyboard_lobby(scenario, group_id))
            else: msg = await self.bot.send_message(group_id, text, parse_mode="HTML", reply_markup=self._keyboard_lobby(scenario, group_id)); self.ui.lobby_message_id = msg.message_id
        except (MessageNotModified, MessageCantBeEdited): pass
        except MessageToEditNotFound:
            msg = await self.bot.send_message(group_id, text, parse_mode="HTML", reply_markup=self._keyboard_lobby(scenario, group_id)); self.ui.lobby_message_id = msg.message_id

    async def new_game(self, callback):
        try:
            await callback.answer("⏳ در حال آماده‌سازی بازی...")
            if not callback.message or not callback.message.chat: return
            group_id = int(callback.message.chat.id); logging.info("new_game callback received for group %s by user %s", group_id, getattr(callback.from_user, "id", None))
            if ALLOWED_GROUP_ID and group_id != ALLOWED_GROUP_ID: await callback.message.answer("❌ این ربات در این گروه فعال نیست."); return
            self.ui.group_chat_id = group_id; self.runtime.lobby.ensure(group_id); await self._render_lobby(group_id)
        except Exception:
            logging.exception("new_game callback failed")
            try: await callback.message.answer("❌ اجرای بازی جدید با خطا مواجه شد. خطا در لاگ ثبت شد.")
            except Exception: logging.exception("failed to send new_game error message")

    async def set_event_number(self, callback):
        group_id = int(callback.message.chat.id); game = self.runtime.state.active_game(group_id)
        if not game or game.get("status") != Phase.LOBBY.value: await callback.answer("❌ لابی فعال نیست.", show_alert=True); return
        self.pending_event_number[(group_id, int(callback.from_user.id))] = group_id; current = int(game.get("event_number") or 1); await callback.answer(); await callback.message.answer(f"🔢 شماره بازی را ارسال کنید.\nشماره فعلی: <b>{current}</b>\n\nفقط یک عدد مثبت ارسال کنید.", parse_mode="HTML")

    async def _event_number_input(self, message: types.Message):
        group_id = int(message.chat.id); key = (group_id, int(message.from_user.id))
        if key not in self.pending_event_number: return
        self.pending_event_number.pop(key, None); raw = (message.text or "").strip()
        try: number = int(raw)
        except ValueError: await message.answer("❌ شماره بازی باید فقط عدد باشد. دوباره از دکمه «شماره بازی» استفاده کنید."); return
        if number < 1: await message.answer("❌ شماره بازی باید حداقل ۱ باشد."); return
        game = self.runtime.state.active_game(group_id)
        if not game or game.get("status") != Phase.LOBBY.value: await message.answer("❌ لابی فعال نیست."); return
        try: self.runtime.state.lobby.set_event_number(game["id"], number); await self._render_lobby(group_id); await message.answer(f"✅ شماره بازی روی <b>{number}</b> ثبت شد.", parse_mode="HTML")
        except Exception: logging.exception("failed to update event number for game %s", game.get("id")); await message.answer("❌ ثبت شماره بازی انجام نشد. خطا در لاگ ثبت شد.")

    async def join(self, callback):
        group_id = int(callback.message.chat.id); user = callback.from_user; await self._ensure_player(user); game = self.runtime.state.active_game(group_id)
        if not game or game.get("status") != Phase.LOBBY.value: await callback.answer("❌ لابی فعال نیست.", show_alert=True); return
        snapshot = self.runtime.lobby_snapshot(group_id)
        if any(int(r["player_id"]) == user.id for r in snapshot.get("players", [])): await callback.answer("⚠️ شما قبلاً وارد شده‌اید.", show_alert=True); return
        scenario = (snapshot.get("game") or {}).get("scenario_id"); occupied = self._players_by_seat(group_id); maximum = self._max_players(scenario)
        if not maximum: await callback.answer("⚠️ ابتدا سناریو را انتخاب کنید.", show_alert=True); return
        seat = next((s for s in range(1, maximum + 1) if s not in occupied), None); self.runtime.lobby.join(group_id, user.id, seat); await self._render_lobby(group_id); await callback.answer(f"✅ صندلی {seat} برای شما ثبت شد." if seat else "📌 به لیست رزرو اضافه شدید.")

    async def leave(self, callback):
        group_id = int(callback.message.chat.id); self.runtime.lobby.leave(group_id, callback.from_user.id); await self._render_lobby(group_id); await callback.answer("❌ از بازی خارج شدید.")
    async def choose_scenario(self, callback):
        kb = InlineKeyboardMarkup(row_width=1)
        for name in self.scenarios: kb.add(InlineKeyboardButton(name, callback_data=f"scenario:{name}"))
        await callback.message.edit_text("📝 سناریو را انتخاب کنید:", reply_markup=kb); await callback.answer()
    async def scenario_selected(self, callback):
        scenario = callback.data.split(":", 1)[1]; group_id = int(callback.message.chat.id)
        if scenario not in self.scenarios: await callback.answer("⚠️ سناریو وجود ندارد.", show_alert=True); return
        self.runtime.lobby.set_scenario(group_id, scenario); await self._render_lobby(group_id); await callback.answer("✅ سناریو انتخاب شد.")
    async def toggle_challenge(self, callback):
        gid = int(callback.message.chat.id)
        self.challenge_enabled[gid] = not self.challenge_enabled.get(gid, True)
        self.challenge_active = self.challenge_enabled[gid]
        await callback.answer("⚔ چالش " + ("روشن شد." if self.challenge_enabled[gid] else "خاموش شد."))
    async def start_turn(self, group_id: int, seat: int, index: int, *, challenge: bool = False):
        row = self._players_by_seat(group_id).get(int(seat))
        if not row: return
        order = self._turn_order(group_id); self._persist_turn_pointer(group_id, order, index); duration = DEFAULT_CHALLENGE_DURATION if challenge else DEFAULT_TURN_DURATION
        self.runtime.start_turn(group_id, max(1, index + 1), seat=int(seat), player_id=int(row["player_id"]), turn_type="challenge" if challenge else "main", duration_seconds=duration, current_turn_index=index, state={"challenge": challenge})
        await self.bot.send_message(group_id, f"{'⚔' if challenge else '🎙'} نوبت <a href='tg://user?id={int(row['player_id'])}'>{html.escape(self._name(int(row['player_id'])))}</a> است. ({duration} ثانیه)", parse_mode="HTML")

    async def startup(self):
        await self.bot.delete_webhook(drop_pending_updates=True); plans = await self.recovery.start(); logging.info("recovered %d persisted turn plans", len(plans))
    async def shutdown(self): await self.recovery.stop(); await self.bot.session.close()

    def _register_handlers(self):
        self.dp.register_callback_query_handler(self.new_game, lambda c: c.data == "new_game")
        self.dp.register_callback_query_handler(self.join, lambda c: c.data in {"join", "join_game"})
        self.dp.register_callback_query_handler(self.leave, lambda c: c.data in {"leave", "leave_game"})
        self.dp.register_callback_query_handler(self.choose_scenario, lambda c: c.data == "choose_scenario")
        self.dp.register_callback_query_handler(self.scenario_selected, lambda c: c.data.startswith("scenario:"))
        self.dp.register_callback_query_handler(self.set_event_number, lambda c: c.data == "set_event_number")
        self.dp.register_callback_query_handler(self.toggle_challenge, lambda c: c.data in {"toggle_challenge", "challenge_toggle"})
        self.dp.register_callback_query_handler(self.cancel_game, lambda c: c.data == "cancel_game")
        self.dp.register_message_handler(self._event_number_input, lambda m: bool(m.chat and m.from_user and (int(m.chat.id), int(m.from_user.id)) in self.pending_event_number), content_types=types.ContentTypes.TEXT)
        self.dp.register_message_handler(self._start_command, commands=["start"])

    async def cancel_game(self, callback):
        game = self.runtime.state.active_game(int(callback.message.chat.id))
        if game:
            self.runtime.state.games.update_game(game["id"], status=Phase.FINISHED.value, state={})
            try: self.runtime.state.games.clear_game_players(game["id"])
            except Exception: logging.exception("failed to clear cancelled game players")
        await callback.message.edit_text("🚫 بازی لغو شد."); await callback.answer("بازی لغو شد.")

    async def _start_command(self, message):
        args = (message.get_args() or "").strip()
        role_handler = getattr(self, "_handle_role_deep_link", None)
        if args.startswith("role_") and role_handler:
            handled = await role_handler(message)
            if handled: return
        await message.answer("🏠 منوی بازی:", reply_markup=self._keyboard_main())

TOKEN = os.getenv("API_TOKEN")
if not TOKEN: raise ValueError("API_TOKEN environment variable is not set!")
app = MafiaApplication(TOKEN)
bot = app.bot
dp = app.dp
async def on_startup(dp): await app.startup()
async def on_shutdown(dp): await app.shutdown()
if __name__ == "__main__": executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
