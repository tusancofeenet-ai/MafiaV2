"""MafiaNights production entry point."""
from __future__ import annotations

import logging
import os

from main_refactored_v4 import MafiaApplicationV4
from runtime.cancel_command import install as install_cancel_command
from runtime.final_persistence import install as install_persistence
from runtime.game_management import GameManagement
from runtime.game_management_compat import install as install_management_compat
from runtime.game_end import install as install_game_end
from runtime.game_archive_v2 import install as install_game_archive
from runtime.management_navigation import install as install_management_navigation
from runtime.production_lobby import install as install_production_lobby
from runtime.role_distribution import install as install_role_distribution
from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.voting_end_game_patch import install as install_voting_end_game_patch
from runtime.voting_runtime import install as install_voting_runtime
from runtime.voting_timer_patch import install as install_voting_timer_patch
from runtime.voting_serverless_patch import install as install_voting_serverless_patch
from runtime.voting_end_target_patch import install as install_voting_end_target_patch
from runtime.voting_postfix import install as install_voting_postfix
from runtime.user_stats import install as install_user_stats
from runtime.player_scoring import install as install_player_scoring
from runtime.player_kick import install as install_player_kick
from runtime.text_commands import install as install_text_commands

TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)

app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp

persistence_status = install_persistence(app)
management = GameManagement(app)
install_management_navigation(app, management)
management.install()
install_management_compat(app, management)
install_game_end(app)
game_archive_status = install_game_archive(app)
install_cancel_command(app)
production_lobby_status = install_production_lobby(app)
role_distribution_status = install_role_distribution(app)
app._canonical_distribute_roles = app._role_distribution_handler
stable_round_status = install_stable_round_engine(app)
voting_end_game_status = install_voting_end_game_patch(app)
voting_runtime_status = install_voting_runtime(app)
voting_timer_status = install_voting_timer_patch(app)
voting_serverless_status = install_voting_serverless_patch(app)
voting_end_target_status = install_voting_end_target_patch(app)
voting_postfix_status = install_voting_postfix(app)
user_stats_status = install_user_stats(app)
player_scoring_status = install_player_scoring(app)
player_discipline_status = install_player_kick(app)
text_commands_status = install_text_commands(app)
logging.info(
    "PRODUCTION_RUNTIME_ACTIVE persistent=%s canonical_lobby=%s management=active game_end=active game_archive=%s role_distribution=%s stable_round=%s voting_end_game=%s voting=%s voting_timer=%s voting_serverless=%s voting_end_target=%s voting_postfix=%s user_stats=%s scoring=%s discipline=%s text_commands=%s",
    persistence_status, production_lobby_status, game_archive_status, role_distribution_status, stable_round_status, voting_end_game_status, voting_runtime_status, voting_timer_status, voting_serverless_status, voting_end_target_status, voting_postfix_status, user_stats_status, player_scoring_status, player_discipline_status, text_commands_status,
)


async def on_startup(dp):
    logging.info(
        "MafiaNights production startup; persistence=%s canonical_lobby=%s management=active game_end=active game_archive=%s role_distribution=%s stable_round=%s voting_end_game=%s voting=%s voting_timer=%s voting_serverless=%s voting_end_target=%s voting_postfix=%s user_stats=%s scoring=%s discipline=%s text_commands=%s",
        persistence_status, production_lobby_status, game_archive_status, role_distribution_status, stable_round_status, voting_end_game_status, voting_runtime_status, voting_timer_status, voting_serverless_status, voting_end_target_status, voting_postfix_status, user_stats_status, player_scoring_status, player_discipline_status, text_commands_status,
    )
    await app.startup()
    try:
        allowed_group_id = int(os.getenv("ALLOWED_GROUP_ID", "-1002356353761"))
        active_game = app.runtime.state.active_game(allowed_group_id)
        if active_game:
            app.group_chat_id = allowed_group_id
            app.ui.group_chat_id = allowed_group_id
            rows = app.runtime.lobby_snapshot(allowed_group_id).get("players") or []
            app.player_slots = {int(row["seat"]): int(row["player_id"]) for row in rows if row.get("seat") is not None and str(row.get("status") or "active") not in {"removed", "dead"}}
            app.moderator_id = int(active_game.get("moderator_id") or 0) or None
            app.game_running = str(active_game.get("status") or "") in {"running", "paused", "turn"}
            state = dict(active_game.get("state") or {})
            app.turn_order = [int(x) for x in state.get("turn_order") or sorted(app.player_slots)]
            app.current_turn_index = int(active_game.get("current_turn_index") or 0)
    except Exception:
        logging.exception("Failed to restore active Telegram game context")


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
