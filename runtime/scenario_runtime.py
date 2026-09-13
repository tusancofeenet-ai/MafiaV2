"""Authoritative scenario adapter used by the live game runtime."""
from __future__ import annotations

import json
from typing import Any, Optional

from repositories.scenario_repository import ScenarioRepository


class ScenarioRuntime:
    """Resolve a persisted scenario and expose its gameplay configuration.

    The lobby stores only ``scenario_id``.  The complete scenario definition
    is copied into game.state when selected so the running game keeps the
    exact rules that were selected, even if an administrator edits the
    scenario later.
    """

    def __init__(self, app: Any):
        self.app = app
        self.repo = ScenarioRepository()

    @staticmethod
    def _config(row: dict[str, Any]) -> dict[str, Any]:
        value = row.get("config") or {}
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                value = {}
        return value if isinstance(value, dict) else {}

    def get(self, scenario_id: Optional[int]) -> Optional[dict[str, Any]]:
        if not scenario_id:
            return None
        row = self.repo.get_by_id(int(scenario_id))
        if not row or not row.get("is_active", True):
            return None
        row = dict(row)
        row["config"] = self._config(row)
        row["roles"] = list(row.get("roles") or [])
        return row

    def snapshot(self, scenario_id: Optional[int]) -> Optional[dict[str, Any]]:
        row = self.get(scenario_id)
        if not row:
            return None
        cfg = row["config"]
        return {
            "id": int(row["id"]),
            "name": row.get("name"),
            "description": row.get("description"),
            "min_players": int(row.get("min_players") or 0),
            "max_players": int(row.get("max_players") or len(row["roles"])),
            "roles": row["roles"],
            "role_rules": cfg.get("roles") or {},
            "sides": cfg.get("sides") or {},
            "challenge_mode": "free" if cfg.get("challenge_mode") == "free" else "limited",
            "challenge_limit": cfg.get("challenge_limit"),
            "settings": cfg.get("settings") or {},
        }

    def apply_to_game(self, game_id: str, scenario_id: int) -> dict[str, Any]:
        scenario = self.snapshot(scenario_id)
        if not scenario:
            raise ValueError("سناریوی انتخاب‌شده معتبر یا فعال نیست")
        game = self.app.runtime.state.games.get_game(game_id)
        if not game:
            raise ValueError("بازی پیدا نشد")
        state = dict(game.get("state") or {})
        state["scenario"] = scenario
        state["scenario_config"] = {
            "roles": scenario["role_rules"],
            "sides": scenario["sides"],
            "challenge_mode": scenario["challenge_mode"],
            "challenge_limit": scenario["challenge_limit"],
            "settings": scenario["settings"],
        }
        state["scenario_name"] = scenario["name"]
        state["challenge_usage"] = {}
        self.app.runtime.state.games.update_game(
            game_id,
            scenario_id=int(scenario_id),
            state=state,
        )
        return scenario

    def current(self, group_id: int) -> Optional[dict[str, Any]]:
        game = self.app.runtime.state.active_game(group_id)
        if not game:
            return None
        state = dict(game.get("state") or {})
        cached = state.get("scenario")
        if isinstance(cached, dict) and cached.get("id"):
            return cached
        return self.snapshot(game.get("scenario_id"))
