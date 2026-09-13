"""Authoritative-state boundary for legacy Telegram globals.

During migration, ``main.py`` still needs mutable globals for rendering and
callback compatibility. They are treated as a derived cache, not the source
of truth. Production can keep the authority object available without paying a
full persistent snapshot + write on every Telegram update.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram.dispatcher.middlewares import BaseMiddleware

PERSISTED_FIELDS = {
    "player_slots", "turn_order", "current_turn_index", "current_turn_seat",
    "players_in_game", "extra_turns", "removed_players",
    "next_by_players_enabled", "next_by_moderator_enabled",
}
EPHEMERAL_FIELDS = {
    "game_message_id", "lobby_message_id", "current_turn_message_id",
    "turn_timer_task", "waiting_message_id", "last_next_time",
}
DERIVED_FIELDS = {
    "waiting_list", "pending_challenges", "challenge_requests",
    "active_challenger_seats", "challenge_mode", "paused_main_player",
    "paused_main_duration", "post_challenge_advance", "day_number",
    "day_phase", "game_running", "lobby_active", "moderator_id",
    "selected_scenario",
}


def _group_id(update: Any) -> int | None:
    message = getattr(update, "message", None) or update
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) not in {"group", "supergroup"}:
        callback = getattr(update, "callback_query", None)
        message = getattr(callback, "message", None) or message
        chat = getattr(message, "chat", None)
    return getattr(chat, "id", None) if chat is not None else None


def _normalise_slots(value: Any) -> dict[int, int]:
    return {int(seat): int(uid) for seat, uid in (value or {}).items()}


def _normalise_order(value: Any) -> list[int]:
    return [int(x) for x in (value or [])]


def _normalise_players_in_game(value: Any) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for key, row in (value or {}).items():
        if not isinstance(row, dict):
            continue
        try:
            result[int(key)] = dict(row)
        except (TypeError, ValueError):
            continue
    return result


def _serialise_players_in_game(value: Any) -> dict[str, dict[str, Any]]:
    return {str(key): dict(row) for key, row in _normalise_players_in_game(value).items()}


def _normalise_removed(value: Any) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for key, row in (value or {}).items():
        if not isinstance(row, dict):
            continue
        try:
            result[int(key)] = dict(row)
        except (TypeError, ValueError):
            continue
    return result


class LegacyStateAuthority:
    """Synchronize legacy compatibility state without making it authoritative."""

    def __init__(self, main_module: Any, runtime: Any):
        self.main = main_module
        self.runtime = runtime

    def _game(self, group_id: int):
        return self.runtime.state.active_game(group_id)

    def hydrate(self, group_id: int) -> dict[str, Any]:
        snapshot = self.runtime.snapshot(group_id)
        game = snapshot.get("game")
        if not game:
            return snapshot
        self.main.group_chat_id = int(group_id)
        self.main.moderator_id = game.get("moderator_id")
        self.main.selected_scenario = game.get("scenario_id")
        self.main.game_running = game.get("status") in {"running", "paused"}
        self.main.lobby_active = game.get("status") == "lobby"
        self.main.current_turn_index = int(game.get("current_turn_index") or 0)
        self.main.current_turn_seat = game.get("current_turn_seat")
        payload = dict(game.get("state") or {})
        slots = payload.get("player_slots")
        if slots is None:
            slots = {str(row["seat"]): int(row["player_id"])
                     for row in (snapshot.get("players") or []) if row.get("seat") is not None}
        self.main.player_slots = _normalise_slots(slots)
        self.main.turn_order = _normalise_order(payload.get("turn_order"))
        self.main.extra_turns = _normalise_order(payload.get("extra_turns"))
        self.main.players_in_game = _normalise_players_in_game(payload.get("players_in_game"))
        self.main.removed_players = {int(group_id): _normalise_removed(payload.get("removed_players"))}
        self.main.next_by_players_enabled = bool(payload.get("next_by_players_enabled", True))
        self.main.next_by_moderator_enabled = bool(payload.get("next_by_moderator_enabled", True))
        day = self.runtime.day_snapshot(group_id)
        self.main.day_number = int(day.get("day") or 0)
        self.main.day_phase = day.get("phase")
        pending = snapshot.get("challenge") or []
        self.main.pending_challenges = {str(row.get("id")): row for row in pending}
        self.main.challenge_requests = {str(row.get("id")): row for row in pending}
        self.main.challenge_mode = bool(pending) or bool(payload.get("challenge_pause", {}).get("active"))
        pause_state = (payload.get("challenge_pause") or {}).get("state") or {}
        self.main.paused_main_player = pause_state.get("paused_main_player")
        self.main.paused_main_duration = pause_state.get("paused_main_duration")
        self.main.post_challenge_advance = bool(pause_state.get("post_challenge_advance", False))
        challenger_ids = {int(row.get("challenger_id")) for row in pending if row.get("challenger_id") is not None}
        self.main.active_challenger_seats = {seat for seat, uid in self.main.player_slots.items() if uid in challenger_ids}
        return snapshot

    def capture_compatibility_mutations(self, group_id: int) -> dict[str, Any] | None:
        game = self._game(group_id)
        if not game:
            return None
        payload = dict(game.get("state") or {})
        payload["player_slots"] = {str(k): int(v) for k, v in _normalise_slots(getattr(self.main, "player_slots", {})).items()}
        payload["turn_order"] = _normalise_order(getattr(self.main, "turn_order", []))
        payload["extra_turns"] = _normalise_order(getattr(self.main, "extra_turns", []))
        payload["players_in_game"] = _serialise_players_in_game(getattr(self.main, "players_in_game", {}))
        gid = int(group_id)
        removed_all = getattr(self.main, "removed_players", {}) or {}
        payload["removed_players"] = _normalise_removed(removed_all.get(gid, {}))
        payload["next_by_players_enabled"] = bool(getattr(self.main, "next_by_players_enabled", True))
        payload["next_by_moderator_enabled"] = bool(getattr(self.main, "next_by_moderator_enabled", True))
        payload["state_authority"] = "persistent"
        current_index = int(getattr(self.main, "current_turn_index", 0) or 0)
        current_seat = getattr(self.main, "current_turn_seat", None)
        self.runtime.state.games.update_game(game["id"], state=payload,
            current_turn_index=current_index,
            current_turn_seat=int(current_seat) if current_seat is not None else None)
        return self.hydrate(group_id)

    def authority_report(self, group_id: int) -> dict[str, Any]:
        snapshot = self.runtime.snapshot(group_id)
        game = snapshot.get("game") or {}
        return {"source_of_truth": "database", "persisted_fields": sorted(PERSISTED_FIELDS),
                "derived_fields": sorted(DERIVED_FIELDS), "ephemeral_fields": sorted(EPHEMERAL_FIELDS),
                "game_id": game.get("id"), "phase": snapshot.get("phase"),
                "has_active_turn": snapshot.get("turn") is not None,
                "pending_challenges": len(snapshot.get("challenge") or [])}


class StateAuthorityMiddleware(BaseMiddleware):
    """Optional legacy bridge; intentionally not installed in fast production mode."""
    def __init__(self, authority: LegacyStateAuthority):
        super().__init__()
        self.authority = authority

    async def on_pre_process_update(self, update: Any, data: dict):
        group_id = _group_id(update)
        if group_id is None:
            return
        try:
            self.authority.hydrate(int(group_id))
        except Exception:
            logging.exception("persistent state hydration failed for group %s", group_id)

    async def on_post_process_update(self, update: Any, result: Any, data: dict):
        group_id = _group_id(update)
        if group_id is None:
            return
        try:
            self.authority.capture_compatibility_mutations(int(group_id))
        except Exception:
            logging.exception("legacy compatibility state capture failed for group %s", group_id)


def install_legacy_state_authority(main_module: Any, runtime: Any, *, install_middleware: bool = True) -> dict[str, Any]:
    """Install the authority object, optionally attaching the expensive middleware."""
    existing = getattr(main_module, "_persistent_state_authority", None)
    if existing is not None:
        return existing
    authority = LegacyStateAuthority(main_module, runtime)
    middleware = StateAuthorityMiddleware(authority)
    dp = getattr(main_module, "dp", None)
    installed = False
    if install_middleware and dp is not None:
        dp.middleware.setup(middleware)
        installed = True
    result = {"authority": authority, "middleware": middleware, "installed": installed,
              "middleware_enabled": bool(install_middleware)}
    main_module._persistent_state_authority = result
    main_module.PERSISTENT_STATE_FIELDS = frozenset(PERSISTED_FIELDS)
    main_module.EPHEMERAL_STATE_FIELDS = frozenset(EPHEMERAL_FIELDS)
    main_module.DERIVED_STATE_FIELDS = frozenset(DERIVED_FIELDS)
    return result
