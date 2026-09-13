"""Restart-safe reconstruction of process-local timer/UI state.

Persistence remains authoritative. This layer owns only asyncio tasks and
compatibility metadata that can be reconstructed from persisted turns and
challenges.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Optional

from runtime.recovery_coordinator import RecoveryCoordinator
from runtime.recovery_worker import RecoveryPlan


class EphemeralRecoveryManager:
    """Coordinates restart-safe timers and ephemeral Telegram compatibility state."""

    def __init__(self, runtime: Any, main_module: Any):
        self.runtime = runtime
        self.main = main_module
        self.coordinator = RecoveryCoordinator(runtime.state)
        self._expiry_lock = asyncio.Lock()
        self._last_expired_turn: Optional[str] = None
        self._last_expired_at = 0.0

    def prepare_legacy_ui(self, plans: list[RecoveryPlan]) -> None:
        """Reset stale handles and publish deterministic recovery metadata."""
        self.main.turn_timer_task = None
        self.main.current_turn_message_id = None
        self.main.waiting_message_id = None
        self.main.last_next_time = 0
        self.main.recovered_turn_plans = {
            plan.group_chat_id: {
                "turn_id": plan.turn_id,
                "deadline_epoch": plan.deadline_epoch,
                "remaining_seconds": plan.remaining_seconds,
                "status": plan.status,
            }
            for plan in plans if plan.recoverable and plan.turn_id
        }
        self.main.recovered_challenges = []
        try:
            group_id = getattr(self.main, "ALLOWED_GROUP_ID", None)
            if group_id is not None:
                self.main.recovered_challenges = list(self.runtime.pending_challenges(int(group_id)))
        except Exception:
            logging.exception("challenge recovery snapshot failed")
        self.main.ephemeral_recovery_active = True

    async def _invoke_hook(self, name: str, plan: RecoveryPlan) -> bool:
        hook = getattr(self.main, name, None)
        if not callable(hook):
            return False
        try:
            result = hook(plan)
            if inspect.isawaitable(result):
                await result
            return True
        except TypeError:
            try:
                result = hook(plan.group_chat_id, plan.turn_id)
                if inspect.isawaitable(result):
                    await result
                return True
            except Exception:
                logging.exception("recovery hook %s failed", name)
                return False
        except Exception:
            logging.exception("recovery hook %s failed", name)
            return False

    async def rebuild_ui(self, plans: list[RecoveryPlan]) -> None:
        """Call optional application hooks to rebuild Telegram messages safely."""
        for name in ("rebuild_recovered_lobby", "rebuild_recovered_turn", "rebuild_recovered_challenges"):
            hook = getattr(self.main, name, None)
            if not callable(hook):
                continue
            try:
                result = hook(plans)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logging.exception("ephemeral UI recovery hook %s failed", name)

    async def on_turn_expired(self, plan: RecoveryPlan) -> None:
        """Handle a recovered expiry exactly once for the current persisted turn."""
        async with self._expiry_lock:
            now = time.time()
            if plan.turn_id == self._last_expired_turn and now - self._last_expired_at < 2:
                return
            current = self.runtime.turns.current(plan.group_chat_id)
            if not current or str(current.get("id")) != str(plan.turn_id):
                return
            self._last_expired_turn = str(plan.turn_id)
            self._last_expired_at = now
            handled = await self._invoke_hook("on_recovered_turn_expired", plan)
            if not handled:
                self.runtime.finish_turn(str(plan.turn_id), {
                    "recovery": True,
                    "finish_reason": "timer_expired_after_restart",
                })
            self.main.turn_timer_task = None
            recovered = getattr(self.main, "recovered_turn_plans", None)
            if isinstance(recovered, dict):
                recovered.pop(plan.group_chat_id, None)

    async def start(self) -> list[RecoveryPlan]:
        """Hydrate UI metadata, rebuild optional UI, and schedule exact deadlines."""
        plans = self.coordinator.worker.plans()
        self.prepare_legacy_ui(plans)
        await self.rebuild_ui(plans)
        await self.coordinator.start(self.on_turn_expired)
        return plans

    async def stop(self) -> None:
        await self.coordinator.stop()
        self.main.ephemeral_recovery_active = False

    @property
    def running_turn_ids(self) -> set[str]:
        return self.coordinator.running_turn_ids
