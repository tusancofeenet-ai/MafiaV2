"""Production bootstrap bridge for the persistent MafiaNights runtime."""
from __future__ import annotations

import logging
import os
from typing import Any

from runtime.game_runtime import PersistentGameRuntime
from runtime.migration_adapter import MigrationAdapter
from runtime.day_cutover import install_legacy_day_cutover
from runtime.state_authority import install_legacy_state_authority
from runtime.legacy_global_audit import assert_not_authoritative
from runtime.startup_recovery import recover_persisted_games
from runtime.turn_cutover import install_legacy_turn_cutover
from runtime.ephemeral_recovery import EphemeralRecoveryManager


def install(main_module: Any) -> dict[str, Any]:
    """Attach one persistent runtime without per-update DB synchronization.

    Production handlers now read/write the persistent runtime directly. The
    old lobby/state middlewares performed a full snapshot before and after
    every Telegram update, multiplying DB round-trips and causing multi-second
    webhook latency. The compatibility authority remains available explicitly
    for recovery/debugging, but is not installed as an update middleware.
    """
    runtime = PersistentGameRuntime()
    adapter = MigrationAdapter(game_runtime=runtime)

    main_module.persistent_runtime = runtime
    main_module.runtime = runtime
    main_module._migration_adapter = adapter
    main_module._persistent_challenge_runtime = runtime.challenges

    turn_cutover = install_legacy_turn_cutover(main_module, adapter)
    lobby_cutover = None
    day_cutover = install_legacy_day_cutover(main_module, runtime)
    state_authority = install_legacy_state_authority(main_module, runtime, install_middleware=False)
    assert_not_authoritative(main_module)
    ephemeral_recovery = EphemeralRecoveryManager(runtime, main_module)
    main_module._ephemeral_recovery = ephemeral_recovery
    return {
        "runtime": runtime,
        "adapter": adapter,
        "turn_cutover": turn_cutover,
        "lobby_cutover": lobby_cutover,
        "day_cutover": day_cutover,
        "state_authority": state_authority,
        "ephemeral_recovery": ephemeral_recovery,
        "legacy_global_audit": main_module.LEGACY_GLOBAL_AUDIT,
    }


async def recover_and_hydrate(main_module: Any) -> list[dict[str, Any]]:
    """Recover active games, hydrate compatibility state, then rebuild timers."""
    runtime = getattr(main_module, "persistent_runtime", None)
    if runtime is None:
        runtime = PersistentGameRuntime()
        main_module.persistent_runtime = runtime
        main_module.runtime = runtime

    results = await recover_persisted_games(main_module)
    allowed_group = getattr(main_module, "ALLOWED_GROUP_ID", None)
    if allowed_group is None:
        return results

    try:
        group_id = int(allowed_group)
        authority = getattr(main_module, "_persistent_state_authority", {}).get("authority")
        if authority is not None:
            authority.hydrate(group_id)
        else:
            snapshot = runtime.snapshot(group_id)
            game = snapshot.get("game")
            if not game:
                return results
            main_module.group_chat_id = int(game["group_chat_id"])
            main_module.moderator_id = game.get("moderator_id")
            main_module.game_running = game.get("status") in {"running", "paused"}
            main_module.lobby_active = game.get("status") == "lobby"

        snapshot = runtime.snapshot(group_id)
        game = snapshot.get("game")
        if not game:
            return results
        main_module.group_chat_id = int(game["group_chat_id"])
        main_module.moderator_id = game.get("moderator_id")
        main_module.game_running = game.get("status") in {"running", "paused"}
        main_module.lobby_active = game.get("status") == "lobby"

        manager = getattr(main_module, "_ephemeral_recovery", None)
        if manager is not None:
            plans = await manager.start()
            main_module.recovered_turn_plans = {
                plan.group_chat_id: {
                    "turn_id": plan.turn_id,
                    "deadline_epoch": plan.deadline_epoch,
                    "remaining_seconds": plan.remaining_seconds,
                }
                for plan in plans if plan.recoverable and plan.turn_id
            }
    except Exception:
        logging.exception("legacy state/timer recovery failed during startup")
    return results


async def startup(main_module: Any, original_startup: Any) -> list[dict[str, Any]]:
    """Run persistent recovery without deleting a webhook in Vercel.

    The legacy main1 startup always calls delete_webhook(), which is correct
    for long-polling but breaks a request-driven Vercel webhook: the first
    webhook request deletes the webhook and all subsequent Telegram updates
    stop arriving. Preserve the original startup for local polling only.
    """
    if original_startup is not None and not os.getenv("VERCEL"):
        await original_startup(main_module.dp)
    elif os.getenv("VERCEL"):
        logging.info("Webhook runtime detected; skipped polling-only delete_webhook startup.")
    return await recover_and_hydrate(main_module)
