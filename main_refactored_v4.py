"""MafiaNights clean migration target, feature-parity v4."""

from __future__ import annotations

import html
import logging
import os

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from main_refactored import MafiaApplication
from repositories.scenario_repository import ScenarioRepository
from runtime.feature_parity_v4 import FeatureParityV4
from runtime.scenario_management_v4 import ScenarioManagementV4
from runtime.scenario_runtime import ScenarioRuntime


logger = logging.getLogger(__name__)


class MafiaApplicationV4(MafiaApplication):
    """Production application facade for the v4 runtime."""

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
        """Remove legacy callback handlers before registering v4 handlers."""
        handler = getattr(self.dp, "callback_query_handlers", None)
        table = getattr(handler, "handlers", None)

        if table is None:
            logger.warning(
                "Callback handler table is unavailable; "
                "legacy lobby handlers were not cleared."
            )
            return

        table[:] = []

        self.dp.register_callback_query_handler(
            self.toggle_challenge,
            lambda callback: callback.data
            in {"toggle_challenge", "challenge_toggle"},
        )

    def _scenario_row(self, scenario_id):
        """Return a scenario snapshot or None for an invalid/missing ID."""
        if scenario_id in (None, ""):
            return None

        try:
            return self.scenario_runtime.snapshot(int(scenario_id))
        except (TypeError, ValueError):
            return None

    def _scenario_roles(self, scenario):
        """Return the roles configured for a scenario."""
        row = self._scenario_row(scenario)
        return list((row or {}).get("roles") or [])

    def _max_players(self, scenario=None):
        """Return the configured maximum player count for a scenario."""
        row = self._scenario_row(scenario)

        if not row:
            return 0

        return int(
            row.get("max_players")
            or len(row.get("roles") or [])
        )

    async def _render_lobby(self, group_id: int):
        """Render/update the current lobby message for a group."""
        snapshot = self.runtime.lobby_snapshot(group_id)

        game = (
            snapshot.get("game")
            or self.runtime.state.active_game(group_id)
            or {}
        )

        scenario = self._scenario_row(game.get("scenario_id"))

        event_number = game.get("event_number") or 1
        players = snapshot.get("players") or []

        scenario_name = (
            (scenario or {}).get("name")
            or "انتخاب نشده"
        )

        max_players = int(
            (scenario or {}).get("max_players")
            or len((scenario or {}).get("roles") or [])
        )

        lines = [
            "📋 <b>لابی Mafia Nights</b>",
            "",
            f"🔢 <b>شماره بازی:</b> {event_number}",
            f"📝 <b>سناریو:</b> {html.escape(str(scenario_name))}",
            f"👥 <b>ظرفیت:</b> {max_players}",
            "",
        ]

        sorted_players = sorted(
            players,
            key=lambda row: (
                row.get("seat") is None,
                row.get("seat") or 999,
            ),
        )

        for row in sorted_players:
            try:
                user_id = int(row["player_id"])
            except (KeyError, TypeError, ValueError):
                logger.warning(
                    "Skipping malformed lobby player row: %r",
                    row,
                )
                continue

            seat = row.get("seat")

            seat_text = (
                "رزرو"
                if seat is None
                else f"صندلی {seat}"
            )

            lines.append(
                f"• <a href='tg://user?id={user_id}'>"
                f"{html.escape(self._name(user_id))}"
                f"</a> — {seat_text}"
            )

        text = "\n".join(lines)

        keyboard = self._keyboard_lobby(
            game.get("scenario_id"),
            group_id,
        )

        message_id = getattr(
            self.ui,
            "lobby_message_id",
            None,
        )

        if not message_id:
            try:
                message = await self.bot.send_message(
                    group_id,
                    text,
                    parse_mode="HTML",
                    reply_markup=keyboard,
                )
            except Exception:
                logger.exception(
                    "Failed to create lobby message for group %s",
                    group_id,
                )
                return

            self.ui.lobby_message_id = message.message_id
            return

        try:
            await self.bot.edit_message_text(
                text,
                group_id,
                message_id,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
            return

        except Exception as exc:
            logger.warning(
                "Failed to edit lobby message %s in group %s: %s",
                message_id,
                group_id,
                exc,
            )

        try:
            message = await self.bot.send_message(
                group_id,
                text,
                parse_mode="HTML",
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception(
                "Failed to recreate lobby message for group %s",
                group_id,
            )
            return

        self.ui.lobby_message_id = message.message_id

    async def choose_scenario(
        self,
        callback: types.CallbackQuery,
    ):
        """Show active scenarios available for the current lobby."""
        rows = self.scenario_repository.list_active()

        if not rows:
            await callback.answer(
                "⚠️ هیچ سناریوی فعالی وجود ندارد.",
                show_alert=True,
            )
            return

        keyboard = InlineKeyboardMarkup(row_width=1)

        for row in rows:
            roles = len(row.get("roles") or [])

            keyboard.add(
                InlineKeyboardButton(
                    f"📝 {row['name']} ({roles} نقش)",
                    callback_data=f"scenario:{int(row['id'])}",
                )
            )

        await callback.message.edit_text(
            "📝 <b>انتخاب سناریو</b>\n\n"
            "سناریوی موردنظر را انتخاب کنید:",
            parse_mode="HTML",
            reply_markup=keyboard,
        )

        await callback.answer()

    async def scenario_selected(
        self,
        callback: types.CallbackQuery,
    ):
        """Apply the selected scenario to the active lobby."""
        group_id = int(callback.message.chat.id)

        try:
            scenario_id = int(
                callback.data.split(":", 1)[1]
            )
        except (IndexError, ValueError, TypeError):
            await callback.answer(
                "⚠️ سناریو نامعتبر است.",
                show_alert=True,
            )
            return

        game = self.runtime.state.active_game(group_id)

        if not game or str(game.get("status")) != "lobby":
            await callback.answer(
                "⚠️ لابی فعال نیست.",
                show_alert=True,
            )
            return

        try:
            scenario = self.scenario_runtime.apply_to_game(
                game["id"],
                scenario_id,
            )

            await self._render_lobby(group_id)

        except Exception:
            logger.exception(
                "Failed to apply scenario %s to game %s",
                scenario_id,
                game.get("id"),
            )

            await callback.answer(
                "❌ انتخاب سناریو انجام نشد.",
                show_alert=True,
            )
            return

        await callback.answer(
            f"✅ سناریوی «{scenario['name']}» انتخاب شد."
        )


TOKEN = os.getenv("API_TOKEN")

if not TOKEN:
    raise RuntimeError(
        "API_TOKEN environment variable is not set."
    )


app = MafiaApplicationV4(TOKEN)

bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor

    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
