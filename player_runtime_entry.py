"""Production entry point for the persistent MafiaNights runtime."""

import logging
import main1 as main
from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup
from player_service import player_service
from runtime.webhook_safety import install_latency, install_safe_callback_answer

install_safe_callback_answer()
_bridge = install_persistent_bridge(main)
main.player_service = player_service
install_latency(main.dp)
logging.info("PERSISTENCE_OPTIMIZATION_ACTIVE pool=serverless-safe identity-cache=60s active-game-cache=0.75s")
logging.info("PRODUCTION_FAST_PATH active=1 legacy-lobby-middleware=off legacy-state-middleware=off identity-bridge=off")

from runtime.postgres_fsm_storage import install as install_postgres_fsm_storage
install_postgres_fsm_storage(main)
from runtime.scenario_persistence_patch import install as install_scenario_persistence_patch
install_scenario_persistence_patch(main)
from runtime.game_ui_bugfixes import install as install_game_ui_bugfixes
install_game_ui_bugfixes(main)
from runtime.production_fastpath import install as install_production_fastpath
install_production_fastpath(main)
from runtime.lobby_ui_v6 import install as install_lobby_ui
install_lobby_ui(main)
from runtime.lobby_callback_cutover import install as install_lobby_callback_cutover
install_lobby_callback_cutover(main)
from runtime.lobby_ui_v7_patch import install as install_lobby_v7_patch
install_lobby_v7_patch(main)
from runtime.lobby_ui_v8_patch import install as install_lobby_ui_v8
install_lobby_ui_v8(main)
from runtime.lobby_ui_v9_patch import install as install_lobby_ui_v9
install_lobby_ui_v9(main)
from runtime.game_flow_ui_v2 import install as install_game_flow_ui_v2
install_game_flow_ui_v2(main)
from runtime.game_flow_authority import install as install_game_flow_authority
install_game_flow_authority(main)
from runtime.challenge_authority import install as install_challenge_authority
install_challenge_authority(main)
from runtime.callback_authorization import install as install_callback_authorization
install_callback_authorization(main)
from runtime.final_runtime_guard import install as install_final_runtime_guard
install_final_runtime_guard(main)
from runtime.seat_emoji_patch import install as install_seat_emoji_patch
install_seat_emoji_patch(main)

from runtime.user_panel import install as install_user_panel
user_panel = install_user_panel(main)
from runtime.start_profile_patch import install as install_start_profile_patch
install_start_profile_patch(main)
from runtime.user_panel_back_patch import install as install_user_panel_back_patch
install_user_panel_back_patch(main, user_panel)
from runtime.profile_enhancements_fixed import install as install_profile_enhancements
profile_enhancements = install_profile_enhancements(main, user_panel)

from commands import register_commands as register_text_commands
register_text_commands(main)
from runtime.command_surface_v2 import install as install_command_surface_v2
install_command_surface_v2(main)

from runtime.addons_persistence_patch import install as install_addons_persistence_patch
install_addons_persistence_patch(main)
from runtime.addons_menu_v2 import install as install_addons_menu_v2
install_addons_menu_v2(main)
from runtime.private_navigation_authority import install as install_private_navigation_authority
install_private_navigation_authority(main)

from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.live_controls_v2 import install as install_live_controls_v2
from runtime.lobby_challenge_v2 import install as install_lobby_challenge_v2
from runtime.stable_round_policy import install as install_stable_round_policy
from runtime.stable_challenge_button_guard import install as install_stable_challenge_button_guard
from runtime.transition_ui_dedup import install as install_transition_ui_dedup
from runtime.role_distribution_notice import install as install_role_distribution_notice
from runtime.voting_runtime import install as install_voting_runtime
install_stable_round_engine(main)
install_live_controls_v2(main)
install_lobby_challenge_v2(main)
install_stable_round_policy(main)
install_stable_challenge_button_guard(main)
install_transition_ui_dedup(main)
install_voting_runtime(main)

from runtime.game_info_security_v2 import install as install_game_info_security_v2
install_game_info_security_v2(main)
install_lobby_callback_cutover(main)

_original_startup = main.on_startup

async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)
    try:
        configured_gid = getattr(main, "ALLOWED_GROUP_ID", None)
        if configured_gid:
            main.group_chat_id = int(configured_gid)
            admins = await main.bot.get_chat_administrators(main.group_chat_id)
            main.admins = {a.user.id for a in admins}
            main.group_admins = list(main.admins)
    except Exception:
        logging.exception("Failed to initialize private UI group/admin authorization")
    from runtime.final_private_ui import install as install_final_private_ui
    await install_final_private_ui(main)
    from runtime.private_start_guard_v2 import install as install_private_start_guard_v2
    install_private_start_guard_v2(main)
    install_role_distribution_notice(main)
    install_lobby_callback_cutover(main)
    logging.info("FINAL UI AUTHORITY ACTIVE")

if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
