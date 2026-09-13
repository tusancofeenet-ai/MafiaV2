"""Scenario-driven challenge quotas.

The quota is scoped to the gameplay unit selected by the scenario:
- limited: one challenge request per player per round/day;
- free: one challenge request per player per active speaking turn.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from repositories.scenario_repository import ScenarioRepository


class ScenarioChallengePolicy:
    def __init__(self, app: Any):
        self.app = app
        self.scenarios = ScenarioRepository()

    def _game(self, group_id: int) -> Optional[dict[str, Any]]:
        return self.app.runtime.state.active_game(int(group_id))

    def _config(self, game: dict[str, Any]) -> dict[str, Any]:
        state = game.get("state") or {}
        cfg = state.get("scenario_config")
        if isinstance(cfg, dict):
            return cfg
        scenario = state.get("scenario")
        if isinstance(scenario, dict):
            return {
                "roles": scenario.get("role_rules") or {},
                "sides": scenario.get("sides") or {},
                "challenge_mode": scenario.get("challenge_mode", "limited"),
                "challenge_limit": scenario.get("challenge_limit"),
                "settings": scenario.get("settings") or {},
            }
        scenario_id = game.get("scenario_id")
        if not scenario_id:
            return {}
        row = self.scenarios.get_by_id(int(scenario_id))
        cfg = (row or {}).get("config") or {}
        if isinstance(cfg, str):
            try:
                cfg = json.loads(cfg)
            except Exception:
                cfg = {}
        return cfg if isinstance(cfg, dict) else {}

    def mode(self, group_id: int) -> str:
        game = self._game(group_id)
        if not game:
            return "limited"
        return "free" if str(self._config(game).get("challenge_mode") or "limited").lower() == "free" else "limited"

    def scope_key(self, group_id: int, player_id: int) -> tuple[str, str]:
        game = self._game(group_id)
        if not game:
            return "limited", f"unknown:player:{int(player_id)}"
        mode = self.mode(group_id)
        state = dict(game.get("state") or {})
        if mode == "free":
            turn = self.app.runtime.current_turn(group_id)
            turn_id = str((turn or {}).get("id") or "")
            return mode, f"turn:{turn_id}:player:{int(player_id)}"
        round_number = int(state.get("day_number") or state.get("round_number") or 1)
        return mode, f"round:{round_number}:player:{int(player_id)}"

    def check(self, group_id: int, player_id: int) -> tuple[bool, str, str]:
        game = self._game(group_id)
        if not game:
            return False, "🚫 بازی فعالی وجود ندارد.", ""
        mode, key = self.scope_key(group_id, player_id)
        if mode == "free" and key.startswith("turn::"):
            return False, "⚠️ چالش آزاد فقط در نوبت فعال صحبت قابل استفاده است.", key
        usage = dict((game.get("state") or {}).get("challenge_usage") or {})
        if usage.get(key):
            message = "⚠️ در این نوبت صحبت قبلاً یک چالش گرفته‌اید." if mode == "free" else "⚠️ در این دور قبلاً یک چالش گرفته‌اید."
            return False, message, key
        return True, "", key

    def mark(self, group_id: int, player_id: int, key: str, mode: str) -> bool:
        game = self._game(group_id)
        if not game or not key:
            return False
        state = dict(game.get("state") or {})
        usage = dict(state.get("challenge_usage") or {})
        usage[key] = {"player_id": int(player_id), "scope": mode}
        state["challenge_usage"] = usage
        game["state"] = state
        return bool(self.app.runtime.state.games.update_game(game["id"], state=state))
