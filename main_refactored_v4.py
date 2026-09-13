"""MafiaNights clean migration target, feature-parity v4."""
from __future__ import annotations

import html
import os

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from main_refactored import MafiaApplication
from repositories.scenario_repository import ScenarioRepository
from runtime.feature_parity_v4 import FeatureParityV4
from runtime.scenario_management_v4 import ScenarioManagementV4
from runtime.scenario_runtime import ScenarioRuntime


class MafiaApplicationV4(MafiaApplication):
    def __init__(self, token: str):
        super().__init__(token)
        self._disable_legacy_lobby_handlers()
        self.scenario_repository = ScenarioRepository()
        self.scenario_runtime = ScenarioRuntime(self)
        self.scenario_management = ScenarioManagementV4(self)
        self.scenario_management.register(self.dp)
        self.feature_parity = FeatureParityV4(self)
        self.feature_parity.register()

    def _disable_legacy_lobby_handlers(self) -> None:
        handler = self.dp.callback_query_handlers
        table = getattr(handler, "handlers", None)
        if table is None:
            return
        handler.handlers[:] = []
        self.dp.register_callback_query_handler(
            self.toggle_challenge,
            lambda c: c.data in {"toggle_challenge", "challenge_toggle"},
        )

    def _scenario_row(self, scenario_id):
        try:
            return self.scenario_runtime.snapshot(int(scenario_id)) if scenario_id else None
        except (TypeError, ValueError):
            return None

    def _scenario_roles(self, scenario):
        row = self._scenario_row(scenario)
        return list((row or {}).get("roles") or [])

    def _max_players(self, scenario=None):
        row = self._scenario_row(scenario)
        if not row:
            return 0
        return int(row.get("max_players") or len(row.get("roles") or []))

    async def _render_lobby(self, group_id: int):
        snapshot = self.runtime.lobby_snapshot(group_id)
        game = snapshot.get("game") or self.runtime.state.active_game(group_id) or {}
        scenario = self._scenario_row(game.get("scenario_id"))
        event_number = game.get("event_number") or 1
        players = snapshot.get("players") or []
        scenario_name = (scenario or {}).get("name") or "انتخاب نشده"
        max_players = int((scenario or {}).get("max_players") or len((scenario or {}).get("roles") or []))
        text = (
            "📋 <b>لابی Mafia Nights</b>\n\n"
            f"🔢 <b>شماره بازی:</b> {event_number}\n"
            f"📝 <b>سناریو:</b> {html.escape(str(scenario_name))}\n"
            f"👥 <b>ظرفیت:</b> {max_players}\n\n"
        )
        for row in sorted(players, key=lambda x: (x.get("seat") is None, x.get("seat") or 999)):
            uid = int(row["player_id"])
            seat = row.get("seat")
            text += f"• <a href='tg://user?id={uid}'>{html.escape(self._name(uid))}</a> — {'رزرو' if seat is None else f'صندلی {seat}'}\n"
        kb = self._keyboard_lobby(game.get("scenario_id"), group_id)
        try:
            if self.ui.lobby_message_id:
                await self.bot.edit_message_text(text, group_id, self.ui.lobby_message_id, parse_mode="HTML", reply_markup=kb)
            else:
                msg = await self.bot.send_message(group_id, text, parse_mode="HTML", reply_markup=kb)
                self.ui.lobby_message_id = msg.message_id
        except Exception:
            try:
                msg = await self.bot.send_message(group_id, text, parse_mode="HTML", reply_markup=kb)
                self.ui.lobby_message_id = msg.message_id
            except Exception:
                pass

    async def choose_scenario(self, callback: types.CallbackQuery):
        rows = self.scenario_repository.list_active()
        if not rows:
            await callback.answer("⚠️ هیچ سناریوی فعالی وجود ندارد.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for row in rows:
            roles = len(row.get("roles") or [])
            kb.add(InlineKeyboardButton(
                f"📝 {row['name']} ({roles} نقش)",
                callback_data=f"scenario:{int(row['id'])}",
            ))
        await callback.message.edit_text(
            "📝 <b>انتخاب سناریو</b>\n\nسناریوی موردنظر را انتخاب کنید:",
            parse_mode="HTML", reply_markup=kb,
        )
        await callback.answer()

    async def scenario_selected(self, callback: types.CallbackQuery):
        group_id = int(callback.message.chat.id)
        try:
            scenario_id = int(callback.data.split(":", 1)[1])
        except (IndexError, ValueError):
            await callback.answer("⚠️ سناریو نامعتبر است.", show_alert=True)
            return
        game = self.runtime.state.active_game(group_id)
        if not game or str(game.get("status")) != "lobby":
            await callback.answer("⚠️ لابی فعال نیست.", show_alert=True)
            return
        try:
            scenario = self.scenario_runtime.apply_to_game(game["id"], scenario_id)
            await self._render_lobby(group_id)
            await callback.answer(f"✅ سناریوی «{scenario['name']}» انتخاب شد.")
        except Exception:
            await callback.answer("❌ انتخاب سناریو انجام نشد.", show_alert=True)


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
