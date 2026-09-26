"""Production entry point for the persistent MafiaNights runtime."""

import html
import logging
import os
import sys
from types import SimpleNamespace

# ============================================================
# EARLY BOOT DIAGNOSTICS
# These prints intentionally happen before importing main1.
# ============================================================

print("[BOOT 1] player_runtime_entry.py started", flush=True)
print(f"[BOOT 2] python={sys.version.split()[0]}", flush=True)
print(f"[BOOT 3] API_TOKEN_PRESENT={bool(os.getenv('API_TOKEN'))}", flush=True)
print(f"[BOOT 4] DATABASE_URL_PRESENT={bool(os.getenv('DATABASE_URL'))}", flush=True)

print("[BOOT 5] importing main1...", flush=True)
import main1 as main
print("[BOOT 6] main1 imported", flush=True)


# Canonical player identity owner. Legacy nickname handlers from main1/nickname_patch
# are disabled on the real Production dispatcher; commands.py owns the user-facing
# nickname commands and runtime.registration owns private registration.
from runtime.player_identity_authority import install as install_player_identity

print("[BOOT 7] installing player identity authority...", flush=True)
install_player_identity(main)
print("[BOOT 8] player identity authority installed", flush=True)


def _disable_legacy_nickname_handlers() -> int:
    registry = getattr(getattr(main.dp, "message_handlers", None), "handlers", None)
    if registry is None:
        return 0

    legacy_names = {
        "set_nick_command",
        "delete_nick_command",
        "get_nick_command",
        "list_nick_command",
    }

    kept = []
    removed = 0

    for item in list(registry):
        callback = getattr(item, "handler", None) or getattr(item, "callback", None)

        if (
            getattr(callback, "__name__", "") in legacy_names
            and getattr(callback, "__module__", "") == "nickname_patch"
        ):
            removed += 1
            continue

        kept.append(item)

    registry[:] = kept

    if removed:
        logging.info(
            "LEGACY NICKNAME HANDLERS DISABLED count=%s",
            removed,
        )

    return removed


_disable_legacy_nickname_handlers()


from runtime.production_bridge import (
    install as install_persistent_bridge,
    startup as persistent_startup,
)
from player_service import player_service
from runtime.webhook_safety import (
    install_latency,
    install_safe_callback_answer,
)
from runtime import registration as player_registration


install_safe_callback_answer()

_bridge = install_persistent_bridge(main)

player_registration.install(main)

main.player_service = player_service

install_latency(main.dp)

logging.info(
    "PERSISTENCE_OPTIMIZATION_ACTIVE "
    "pool=serverless-safe identity-cache=60s active-game-cache=0.75s"
)


# Presentation authority for the REAL production runtime.
# This is opt-in and never changes callbacks, handlers, state, or business logic.
from runtime.emoji_runtime import install as install_custom_emoji_runtime

if install_custom_emoji_runtime(main):
    logging.info("CUSTOM EMOJI PRESENTATION ACTIVE")


from runtime.postgres_fsm_storage import install as install_postgres_fsm_storage

install_postgres_fsm_storage(main)


from runtime.scenario_persistence_patch import (
    install as install_scenario_persistence_patch,
)

install_scenario_persistence_patch(main)


from runtime.game_ui_bugfixes import install as install_game_ui_bugfixes

install_game_ui_bugfixes(main)


from runtime.production_fastpath import install as install_production_fastpath

install_production_fastpath(main)


# Canonical lobby owner.
from runtime.lobby_membership_authority import (
    install as install_lobby_membership,
)

install_lobby_membership(main)


from runtime.lobby_lifecycle_authority import (
    install as install_lobby_lifecycle,
)

install_lobby_lifecycle(main)


from runtime.lobby_ui_final import install as install_final_lobby

install_final_lobby(main)


# Canonical /start owner for the production Dispatcher.
# Keep this route here, outside the lobby/private UI modules, so later
# feature installers cannot leave /start without a single deterministic
# handler for either chat type.
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _remove_conflicting_start_handlers():
    registry = getattr(
        getattr(main.dp, "message_handlers", None),
        "handlers",
        None,
    )

    if registry is None:
        return 0

    names = {
        "start_cmd",
        "start_command",
        "canonical_start",
        "start_message",
        "show_start",
        "start_with_profile",
    }

    kept = []
    removed = 0

    for item in list(registry):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)

        if getattr(fn, "__name__", "") in names:
            removed += 1
            continue

        kept.append(item)

    registry[:] = kept

    return removed


async def _production_start(message):
    if message.chat.type == "private":
        if await player_registration.start(main, message):
            return

    if message.chat.type in {"group", "supergroup"}:
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton(
                "🎮 بازی جدید",
                callback_data="fl_new",
            )
        )

        await message.reply(
            "🏠 <b>منوی اصلی Mafia Nights</b>",
            parse_mode="HTML",
            reply_markup=kb,
        )

    elif message.chat.type == "private":
        from runtime.final_private_ui import start_keyboard

        await message.answer(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(),
            parse_mode="HTML",
        )

    else:
        raise CancelHandler()

    logging.info(
        "PRODUCTION /START handled chat_type=%s user_id=%s",
        message.chat.type,
        message.from_user.id,
    )

    return


def _install_production_start():
    _remove_conflicting_start_handlers()

    main.dp.register_message_handler(
        _production_start,
        commands=["start"],
        state="*",
        content_types=["text"],
    )

    registry = getattr(
        getattr(main.dp, "message_handlers", None),
        "handlers",
        None,
    )

    if registry:
        for i, item in enumerate(registry):
            fn = getattr(item, "handler", None) or getattr(item, "callback", None)

            if fn is _production_start:
                registry.insert(0, registry.pop(i))
                break

    logging.info("PRODUCTION /START authority armed")


_install_production_start()


# Canonical management owners:
# GameManagement is business logic and management_surface_final
# is the only management UI surface.
from runtime.game_management import GameManagement

main.game_management = GameManagement(main)
main.game_management.install()


from runtime.management_surface_final import (
    install as install_management_surface,
)

install_management_surface(main)


from runtime.end_game_control import install as install_manual_end_game

install_manual_end_game(main)


if not hasattr(main, "ui") or main.ui is None:
    main.ui = SimpleNamespace()


from runtime.role_distribution import install as install_role_distribution

install_role_distribution(main)

main._canonical_distribute_roles = main._role_distribution_handler

if getattr(main, "_render_final_lobby", None):
    main._render_production_lobby = main._render_final_lobby


from runtime.game_flow_ui_v2 import install as install_game_flow_ui_v2

install_game_flow_ui_v2(main)


from runtime.game_flow_authority import (
    install as install_game_flow_authority,
)

game_flow_authority = install_game_flow_authority(main)


from runtime.callback_authorization import (
    install as install_callback_authorization,
)

install_callback_authorization(main)


from runtime.final_runtime_guard import (
    install as install_final_runtime_guard,
)

install_final_runtime_guard(main)


from runtime.seat_emoji_patch import install as install_seat_emoji_patch

install_seat_emoji_patch(main)


from runtime.user_panel import install as install_user_panel

user_panel = install_user_panel(main)


from runtime.start_profile_patch import (
    install as install_start_profile_patch,
)

install_start_profile_patch(main)


from runtime.user_panel_back_patch import (
    install as install_user_panel_back_patch,
)

install_user_panel_back_patch(main, user_panel)


from runtime.profile_schema_compat import (
    install as install_profile_schema_compat,
)

install_profile_schema_compat(main)


from runtime.profile_enhancements_fixed import (
    install as install_profile_enhancements,
)

profile_enhancements = install_profile_enhancements(
    main,
    user_panel,
)

main.profile_enhancements = profile_enhancements


from runtime.profile_db_compat import (
    install as install_profile_db_compat,
)

install_profile_db_compat(profile_enhancements)


from runtime.progress_schema_compat import (
    install as install_progress_schema_compat,
)

install_progress_schema_compat(main)


from runtime.knowledge_assistant import (
    install as install_knowledge_assistant,
)

install_knowledge_assistant(main)


# The production webhook uses player_runtime_entry -> main1, not main.py.
# Keep the assistant admin panel attached to this real production runtime.
from runtime.assistant_admin_panel import (
    install as install_assistant_admin_panel,
)

main.assistant_admin_panel = install_assistant_admin_panel(main)


from commands import register_commands as register_text_commands

register_text_commands(main)


from runtime.telegram_commands import install as install_telegram_commands

install_telegram_commands(main)


from runtime.command_surface_v2 import (
    install as install_command_surface_v2,
)

install_command_surface_v2(main)


from runtime.addons_persistence_patch import (
    install as install_addons_persistence_patch,
)

install_addons_persistence_patch(main)


from runtime.addons_menu_v2 import install as install_addons_menu_v2

install_addons_menu_v2(main)


from runtime.chat_locks import install as install_chat_locks

install_chat_locks(main)


from runtime.private_scenario_crud import (
    install as install_private_scenario_crud,
)

install_private_scenario_crud(main)


from runtime.progress_features_v4 import (
    install as install_progress_features,
)

_progress_features_runtime = install_progress_features(main)

main._progress_features_runtime = _progress_features_runtime


# Canonical private profile/ranking/stats owner.
# It must be installed before commands.py so the canonical text-command
# dispatcher can delegate to the same UserStats instance instead of
# returning "stats unavailable".
from runtime.user_stats import install as install_user_stats

install_user_stats(main)


from runtime.turn_round_authority import (
    install as install_turn_round_authority,
)

install_turn_round_authority(main)


from runtime.stable_round_engine import (
    install as install_stable_round_engine,
)

from runtime.live_controls_v2 import (
    install as install_live_controls_v2,
)

from runtime.stable_round_policy import (
    install as install_stable_round_policy,
)

from runtime.stable_challenge_button_guard import (
    install as install_stable_challenge_button_guard,
)

from runtime.transition_ui_dedup import (
    install as install_transition_ui_dedup,
)

from runtime.voting_runtime import (
    install as install_voting_runtime,
)

from runtime.voting_timer_patch import (
    install as install_voting_timer_patch,
)

from runtime.player_scoring import (
    install as install_player_scoring,
)


install_stable_round_engine(main)

install_live_controls_v2(main)

install_stable_round_policy(main)

install_stable_challenge_button_guard(main)

install_transition_ui_dedup(main)

install_voting_runtime(main)

install_voting_timer_patch(main)


from runtime.phase_transition_authority import (
    install as install_phase_transition_authority,
)

install_phase_transition_authority(main)

install_player_scoring(main)


from runtime.game_info_security_v2 import (
    install as install_game_info_security_v2,
)

install_game_info_security_v2(main)


# Final runtime authorities are armed only after all feature installers have
# completed. No lobby/management implementation is installed here.
from runtime import production_cutover_final

production_cutover_final.install()


def _rearm_single_owner_challenge_handlers():
    """Keep the canonical challenge executor and its policy/guard wrappers only."""

    registry = getattr(
        getattr(main.dp, "callback_query_handlers", None),
        "handlers",
        None,
    )

    if registry is None:
        return

    canonical_request = getattr(
        main,
        "_stable_challenge_request_handler",
        None,
    )

    canonical_choice = getattr(
        main,
        "_stable_challenge_choice_handler",
        None,
    )

    kept = []
    removed = 0

    for item in list(registry):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)

        name = getattr(fn, "__name__", "")
        module = getattr(fn, "__module__", "")

        if name == "handle_challenge_response":
            removed += 1
            continue

        # Stable policy/live-control/button-guard wrappers are canonical
        # adapters; legacy main1 handlers are the only competing executors
        # to remove.
        if name == "challenge_request" and module == "main1":
            removed += 1
            continue

        if name == "challenge_choice" and module == "main1":
            removed += 1
            continue

        kept.append(item)

    registry[:] = kept

    # Prefer the canonical chain without destroying its policy wrappers.
    preferred = []
    rest = []

    for item in list(registry):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)

        name = getattr(fn, "__name__", "")

        if (
            name in {"challenge_request", "challenge_choice"}
            and getattr(fn, "__module__", "").startswith("runtime.")
        ):
            preferred.append(item)
        else:
            rest.append(item)

    if preferred:
        registry[:] = preferred + rest

    logging.info(
        "SINGLE OWNER CHALLENGE rearmed canonical=%s/%s removed=%s",
        bool(canonical_request),
        bool(canonical_choice),
        removed,
    )


def _rearm_single_owner_legacy_game_handlers():
    """Remove obsolete main1 game executors after canonical authorities load.

    The active production path is owned by the dedicated lobby, management,
    turn/phase, voting, role-distribution and game-end authorities. These
    main1 callbacks are retained in the source only for compatibility/reference;
    they must not remain executable in the Production dispatcher.
    """

    registry = getattr(
        getattr(main.dp, "callback_query_handlers", None),
        "handlers",
        None,
    )

    messages = getattr(
        getattr(main.dp, "message_handlers", None),
        "handlers",
        None,
    )

    legacy_callbacks = {
        "manage_scenarios",
        "add_scenario_start",
        "remove_scenario",
        "delete_scenario",
        "manage_game_handler",
        "add_to_substitute_list",
        "replace_player_list_handler",
        "choose_substitute_for_replace",
        "do_replace_handler",
        "remove_player_handler",
        "remove_player_confirm",
        "birthday_player_handler",
        "birthday_player_confirm",
        "cancel_game_handler",
        "start_game",
        "choose_scenario",
        "scenario_selected",
        "choose_moderator",
        "moderator_selected",
        "join_game_callback",
        "leave_game_callback",
        "join_waiting_handler",
        "leave_waiting_handler",
        "cancel_game",
        "confirm_cancel",
        "back_to_lobby",
        "distribute_roles_callback",
        "start_round_handler",
        "start_play",
        "choose_head",
        "speaker_auto",
        "speaker_manual",
        "head_set_handler",
        "handle_start_turn",
        "challenge_off_handler",
        "challenge_toggle_handler",
        "next_turn",
        "start_night",
        "start_new_day",
        "manage_moderator_menu",
        "show_current_moderator",
        "change_moderator",
        "set_new_moderator",
        "toggle_next_player_pm",
        "toggle_next_moderator_pm",
        "resend_roles_handler",
        "list_players_pv",
        "show_substitute_list",
        "choose_substitute",
        "challenge_status_pv",
        "send_roles_panel",
    }

    if registry is not None:
        before = len(registry)

        registry[:] = [
            item
            for item in registry
            if not (
                getattr(
                    getattr(item, "handler", None)
                    or getattr(item, "callback", None),
                    "__name__",
                    "",
                )
                in legacy_callbacks
                and getattr(
                    getattr(item, "handler", None)
                    or getattr(item, "callback", None),
                    "__module__",
                    "",
                )
                == "main1"
            )
        ]

        # main1 still contains two historical registrations whose executor
        # is a lambda around a legacy function. Match the filter source as
        # well so those callbacks cannot outrank the canonical production
        # owners.
        import inspect

        residual_legacy_filters = (
            'c.data == "resend_roles"',
            'c.data == "list_players"',
        )

        kept = []
        residual_removed = 0

        for item in registry:
            fn = getattr(item, "handler", None) or getattr(
                item,
                "callback",
                None,
            )

            if (
                getattr(fn, "__module__", "") != "main1"
                or getattr(fn, "__name__", "") != "<lambda>"
            ):
                kept.append(item)
                continue

            source = ""

            try:
                filters = getattr(item, "filters", None) or []

                source = "\n".join(
                    inspect.getsource(
                        getattr(f, "callback", None)
                        or getattr(f, "filter", None)
                        or f
                    )
                    for f in filters
                )
            except Exception:
                pass

            if any(marker in source for marker in residual_legacy_filters):
                residual_removed += 1
                continue

            kept.append(item)

        registry[:] = kept

        logging.info(
            "SINGLE OWNER LEGACY CALLBACK CUTOVER removed=%s "
            "residual_lambda_removed=%s",
            before - len(registry) + residual_removed,
            residual_removed,
        )

    if messages is not None:
        legacy_messages = {
            "text_commands_handler",
            "global_message_control",
            "add_substitute",
        }

        before = len(messages)

        messages[:] = [
            item
            for item in messages
            if not (
                getattr(
                    getattr(item, "handler", None)
                    or getattr(item, "callback", None),
                    "__name__",
                    "",
                )
                in legacy_messages
                and getattr(
                    getattr(item, "handler", None)
                    or getattr(item, "callback", None),
                    "__module__",
                    "",
                )
                == "main1"
            )
        ]

        logging.info(
            "SINGLE OWNER LEGACY MESSAGE CUTOVER removed=%s",
            before - len(messages),
        )


# Final challenge/legacy cutover runs only after every canonical installer
# and every helper definition above is available. Keeping this at the end
# of the entry module prevents import-time NameError and guarantees the
# dispatcher is cleaned after all compatibility installers have had their chance
# to register.
_rearm_single_owner_challenge_handlers()

_rearm_single_owner_legacy_game_handlers()


def _remove_duplicate_command_surface_handlers():
    """Keep commands.py as the sole broad text entry point in Production.

    command_surface_v2/v3 remain available as specialized execution adapters,
    but their broad message handlers must not compete with the canonical
    commands.handle_text_commands registration.
    """

    registry = getattr(
        getattr(main.dp, "message_handlers", None),
        "handlers",
        None,
    )

    if registry is None:
        return

    duplicate = {
        ("runtime.command_surface_v2", "command"),
        ("runtime.command_surface_v3", "command"),
    }

    before = len(registry)

    registry[:] = [
        item
        for item in registry
        if (
            getattr(
                getattr(item, "handler", None)
                or getattr(item, "callback", None),
                "__module__",
                "",
            ),
            getattr(
                getattr(item, "handler", None)
                or getattr(item, "callback", None),
                "__name__",
                "",
            ),
        )
        not in duplicate
    ]

    logging.info(
        "SINGLE OWNER COMMAND DISPATCH removed=%s "
        "canonical=commands.handle_text_commands",
        before - len(registry),
    )


_remove_duplicate_command_surface_handlers()


def _rearm_canonical_new_game():
    """Make the final lobby the sole owner of both new-game entry routes."""

    callbacks = getattr(
        getattr(main.dp, "callback_query_handlers", None),
        "handlers",
        [],
    )

    messages = getattr(
        getattr(main.dp, "message_handlers", None),
        "handlers",
        [],
    )

    # Even if a compatibility installer re-registered the legacy main1 callback,
    # it must delegate to the canonical lobby instead of creating its own UI.
    callbacks[:] = [
        item
        for item in callbacks
        if getattr(
            getattr(item, "handler", None)
            or getattr(item, "callback", None),
            "__name__",
            "",
        )
        != "start_game"
    ]

    canonical = getattr(
        main,
        "_canonical_new_game_handler",
        None,
    )

    if canonical is not None:
        for i, item in enumerate(callbacks):
            fn = getattr(item, "handler", None) or getattr(
                item,
                "callback",
                None,
            )

            if fn is canonical:
                callbacks.insert(0, callbacks.pop(i))
                break

    # «بازی جدید» text is allowed to be handled by TextCommands, but that
    # handler now delegates to the same canonical callback. Prefer the final
    # lobby's direct text adapter when present.
    for i, item in enumerate(messages):
        fn = getattr(item, "handler", None) or getattr(
            item,
            "callback",
            None,
        )

        if getattr(fn, "__name__", "") == "new_game_text":
            messages.insert(0, messages.pop(i))
            break

    logging.info(
        "CANONICAL NEW_GAME rearmed: legacy_start_removed final_owner=%s",
        bool(canonical),
    )


_rearm_canonical_new_game()


# Final assistant authority for the REAL production runtime.
# player_runtime_entry -> main1 is the webhook path; main.py is not imported here.
# Re-arm the explicit slash-command AI handler after every feature
# installer so generic player/text handlers cannot consume /ask or /mafia.
try:
    _handlers = getattr(
        main.dp.message_handlers,
        "handlers",
        [],
    )

    _panel = getattr(
        main,
        "assistant_admin_panel",
        None,
    )

    _assistant_handler = getattr(
        main,
        "_knowledge_assistant_handler",
        None,
    )

    _assistant_names = {
        "title",
        "content",
        "scenario",
        "role",
        "source",
        "save_group_key",
        "open",
    }

    _fsm, _explicit, _rest = [], [], []

    for _item in list(_handlers):
        _cb = getattr(_item, "handler", None) or getattr(
            _item,
            "callback",
            None,
        )

        _owner = getattr(_cb, "__self__", None)
        _name = getattr(_cb, "__name__", "")

        if (
            _panel is not None
            and _owner is _panel
            and _name in _assistant_names
        ):
            _fsm.append(_item)

        elif (
            _assistant_handler is not None
            and _cb is _assistant_handler
        ):
            _explicit.append(_item)

        else:
            _rest.append(_item)

    if _fsm or _explicit:
        _handlers[:] = _fsm + _explicit + _rest

    logging.info(
        "ASSISTANT PRODUCTION AUTHORITY ACTIVE fsm=%s explicit=%s",
        len(_fsm),
        len(_explicit),
    )

except Exception:
    logging.exception(
        "Failed to arm final assistant production authority"
    )


# Final canonical text-command authority for the REAL production runtime.
# Generic feature handlers may be registered after commands.py; keep the
# canonical text-command dispatcher immediately after the chat-lock guard.
try:
    _handlers = getattr(
        main.dp.message_handlers,
        "handlers",
        [],
    )

    _command_handlers = []
    _lock_handlers = []
    _other_handlers = []

    for _item in list(_handlers):
        _cb = getattr(_item, "handler", None) or getattr(
            _item,
            "callback",
            None,
        )

        _module = getattr(_cb, "__module__", "")
        _name = getattr(_cb, "__name__", "")

        if (
            _module == "commands"
            and _name == "handle_text_commands"
        ):
            _command_handlers.append(_item)

        elif _name == "chat_lock_message_guard":
            _lock_handlers.append(_item)

        else:
            _other_handlers.append(_item)

    if _command_handlers:
        # Never let a generic catch-all handler consume a Persian text command
        # before commands.py gets it. The lock guard remains first.
        _handlers[:] = (
            _lock_handlers
            + _command_handlers
            + _other_handlers
        )

        logging.info(
            "CANONICAL TEXT COMMAND AUTHORITY REARMED "
            "lock=%s commands=%s total=%s",
            len(_lock_handlers),
            len(_command_handlers),
            len(_handlers),
        )

    else:
        logging.error(
            "CANONICAL TEXT COMMAND AUTHORITY missing "
            "handle_text_commands"
        )

except Exception:
    logging.exception(
        "Failed to rearm canonical text commands"
    )


_original_startup = main.on_startup


async def on_startup(dp):
    try:
        results = await persistent_startup(
            main,
            _original_startup,
        )

        logging.info(
            "Persistent runtime startup recovery completed: %s",
            results,
        )

    except Exception:
        logging.exception(
            "Persistent runtime startup recovery failed; "
            "continuing webhook startup"
        )

    try:
        configured_gid = getattr(
            main,
            "ALLOWED_GROUP_ID",
            None,
        )

        if configured_gid:
            main.group_chat_id = int(configured_gid)

            admins = await main.bot.get_chat_administrators(
                main.group_chat_id
            )

            main.admins = {
                a.user.id
                for a in admins
            }

            main.group_admins = list(main.admins)

    except Exception:
        logging.exception(
            "Failed to initialize private UI group/admin authorization"
        )

    from runtime.final_private_ui import (
        install as install_final_private_ui,
    )

    await install_final_private_ui(main)


    from runtime.private_pv_authority_v2 import (
        install as install_canonical_private_pv,
    )

    await install_canonical_private_pv(main)


    from runtime.pv_route_priority_v2 import (
        install as install_pv_route_priority,
    )

    await install_pv_route_priority(main)


    from runtime.private_ui_recovery_v3 import (
        install as install_private_ui_recovery_v3,
    )

    await install_private_ui_recovery_v3(main)


    from runtime.private_ui_recovery_v5 import (
        install as install_private_ui_recovery_v5,
    )

    await install_private_ui_recovery_v5(main)


    from runtime.private_ui_recovery_v6 import (
        install as install_private_ui_recovery_v6,
    )

    await install_private_ui_recovery_v6(main)


    from runtime.private_ui_recovery_v7 import (
        install as install_private_ui_recovery_v7,
    )

    await install_private_ui_recovery_v7(main)


    from runtime.private_ui_recovery_v8 import (
        install as install_private_ui_recovery_v8,
    )

    await install_private_ui_recovery_v8(main)


    # Private UI recovery layers register their own /start routes.
    # Re-arm the single production owner after those installers so neither
    # PV nor group /start can be shadowed.
    _install_production_start()

    _rearm_canonical_new_game()

    _rearm_single_owner_challenge_handlers()

    _rearm_single_owner_legacy_game_handlers()


    try:
        register_menu = getattr(
            main,
            "_register_telegram_commands",
            None,
        )

        if register_menu is not None:
            await register_menu()

    except Exception:
        logging.exception(
            "Failed to register Telegram command menu"
        )


    # Re-apply progress UI after final private-UI authorities
    # replace the start keyboard.
    try:
        progress_runtime = getattr(
            main,
            "_progress_features_runtime",
            None,
        )

        if progress_runtime is not None:
            progress_runtime._patch_ui()
            progress_runtime.rearm()

            logging.info(
                "PROGRESS UI AND HANDLERS REARMED "
                "AFTER PRIVATE UI AUTHORITIES"
            )

    except Exception:
        logging.exception(
            "Failed to re-apply progress UI after private UI authorities"
        )


    from runtime.faceoff import install as install_faceoff

    await install_faceoff(main)


    # Final assistant callback authority.
    # Private UI recovery layers above may promote generic callback handlers,
    # so install the deterministic aip:* router only after every startup-time
    # callback installer has finished.
    from runtime.assistant_callback_router import (
        install as install_assistant_callback_router,
    )

    install_assistant_callback_router(main)


    # Final message-handler authority: several compatibility installers are
    # registered after AssistantAdminPanel. Re-prioritize its FSM handlers now,
    # at the very end of startup, so waiting_group_key (and knowledge-entry FSM
    # states) cannot be consumed by the generic player-id/text parsers.
    try:
        panel = getattr(
            main,
            "assistant_admin_panel",
            None,
        )

        registry = getattr(
            getattr(main.dp, "message_handlers", None),
            "handlers",
            None,
        )

        if panel is not None and registry is not None:
            assistant_names = {
                "title",
                "content",
                "scenario",
                "role",
                "source",
                "save_group_key",
                "open",
            }

            mine, rest = [], []

            for item in list(registry):
                cb = getattr(item, "callback", None) or getattr(
                    item,
                    "handler",
                    None,
                )

                if (
                    getattr(cb, "__self__", None) is panel
                    and getattr(cb, "__name__", "")
                    in assistant_names
                ):
                    mine.append(item)
                else:
                    rest.append(item)

            if mine:
                registry[:] = mine + rest

                logging.info(
                    "ASSISTANT FSM MESSAGE AUTHORITY REARMED handlers=%s",
                    len(mine),
                )

    except Exception:
        logging.exception(
            "assistant admin: final FSM message prioritization failed"
        )


    # Final assistant message authority.
    # Startup-time UI recovery and command installers above can register
    # generic text handlers after the module-level rearm, so do this one
    # last time after every startup installer has completed.
    try:
        _handlers = getattr(
            main.dp.message_handlers,
            "handlers",
            [],
        )

        _assistant_handler = getattr(
            main,
            "_knowledge_assistant_handler",
            None,
        )

        _panel = getattr(
            main,
            "assistant_admin_panel",
            None,
        )

        _assistant_names = {
            "title",
            "content",
            "scenario",
            "role",
            "source",
            "save_group_key",
            "open",
        }

        _fsm, _explicit, _rest = [], [], []

        for _item in list(_handlers):
            _cb = getattr(
                _item,
                "callback",
                None,
            ) or getattr(
                _item,
                "handler",
                None,
            )

            _owner = getattr(
                _cb,
                "__self__",
                None,
            )

            _name = getattr(
                _cb,
                "__name__",
                "",
            )

            if (
                _panel is not None
                and _owner is _panel
                and _name in _assistant_names
            ):
                _fsm.append(_item)

            elif (
                _assistant_handler is not None
                and _cb is _assistant_handler
            ):
                _explicit.append(_item)

            else:
                _rest.append(_item)

        if _fsm or _explicit:
            _handlers[:] = (
                _fsm
                + _explicit
                + _rest
            )

        logging.info(
            "ASSISTANT FINAL MESSAGE AUTHORITY REARMED "
            "fsm=%s explicit=%s total=%s",
            len(_fsm),
            len(_explicit),
            len(_handlers),
        )

    except Exception:
        logging.exception(
            "assistant admin: final message authority rearm failed"
        )


    # Absolute last startup authority:
    # private-UI recovery layers above can register generic text handlers
    # after the module-level rearm. Re-arm the canonical commands.py
    # dispatcher only after every startup installer has completed.
    try:
        _handlers = getattr(
            main.dp.message_handlers,
            "handlers",
            [],
        )

        _command_handlers = []
        _lock_handlers = []
        _other_handlers = []

        for _item in list(_handlers):
            _cb = getattr(
                _item,
                "callback",
                None,
            ) or getattr(
                _item,
                "handler",
                None,
            )

            _module = getattr(
                _cb,
                "__module__",
                "",
            )

            _name = getattr(
                _cb,
                "__name__",
                "",
            )

            if (
                _module == "commands"
                and _name == "handle_text_commands"
            ):
                _command_handlers.append(_item)

            elif _name == "chat_lock_message_guard":
                _lock_handlers.append(_item)

            else:
                _other_handlers.append(_item)

        if _command_handlers:
            _handlers[:] = (
                _lock_handlers
                + _command_handlers
                + _other_handlers
            )

            logging.info(
                "CANONICAL TEXT COMMAND AUTHORITY FINAL "
                "startup_lock=%s commands=%s total=%s",
                len(_lock_handlers),
                len(_command_handlers),
                len(_handlers),
            )

        else:
            logging.error(
                "CANONICAL TEXT COMMAND AUTHORITY FINAL "
                "missing handle_text_commands"
            )

    except Exception:
        logging.exception(
            "Failed final startup rearm of canonical text commands"
        )


    logging.info(
        "ASSISTANT ADMIN PANEL + CALLBACK ROUTER ACTIVE "
        "in player_runtime_entry"
    )


main.on_startup = on_startup


if __name__ == "__main__":
    from aiogram import executor

    logging.info("POLLING TRACE 1: entering executor.start_polling")

    async def _traced_startup(dp):
        logging.info("POLLING TRACE 2: traced on_startup entered")
        try:
            await main.on_startup(dp)
            logging.info("POLLING TRACE 3: traced on_startup returned")
        except Exception:
            logging.exception("POLLING TRACE ERROR: main.on_startup failed")
            raise

    try:
        logging.info("POLLING TRACE 4: calling executor.start_polling")

        executor.start_polling(
            main.dp,
            skip_updates=True,
            on_startup=_traced_startup,
        )

        logging.info("POLLING TRACE 5: executor.start_polling returned")

    except Exception:
        logging.exception(
            "POLLING TRACE ERROR: executor.start_polling failed"
        )
        raise
