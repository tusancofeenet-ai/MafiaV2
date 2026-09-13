from __future__ import annotations

from typing import Any, Optional

from runtime.game_state import GameState


class PersistentLobbyRuntime:
    """UI-agnostic authoritative runtime for lobby state.

    Group-based convenience methods remain for gameplay compatibility. New
    lobby code should use the game id from its callback and validate the game
    before mutating it, so stale Telegram callbacks cannot target a newer game.
    """

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()

    def ensure(self, group_chat_id: int, moderator_id: Optional[int] = None,
               scenario_id: Optional[str] = None, event_number: Optional[int] = None):
        return self.state.ensure_lobby(group_chat_id, moderator_id, scenario_id, event_number)

    def start_new(self, group_chat_id: int, event_number: Optional[int] = None):
        return self.state.lobby.start_new(group_chat_id, event_number)

    def join(self, group_chat_id: int, player_id: int, seat: Optional[int] = None,
             moderator_id: Optional[int] = None, scenario_id: Optional[str] = None,
             event_number: Optional[int] = None, is_substitute: bool = False,
             substitute: Optional[bool] = None) -> dict[str, Any]:
        if substitute is not None:
            is_substitute = bool(substitute)
        # Compatibility API: callers that intentionally use this method may
        # still create/rehydrate a lobby. Canonical Telegram lobby handlers do
        # NOT use it; they require an existing lobby first.
        game = self.ensure(group_chat_id, moderator_id, scenario_id, event_number)
        row_id = self.state.add_player(game["id"], player_id, seat, is_substitute)
        return {"game_id": game["id"], "game_player_id": row_id, "player_id": int(player_id),
                "seat": seat, "is_substitute": is_substitute}

    def leave(self, group_chat_id: int, player_id: int) -> bool:
        game = self.state.active_game(group_chat_id)
        return bool(game and self.state.lobby.leave(game["id"], player_id))

    def assign_seat(self, group_chat_id: int, player_id: int, seat: int) -> bool:
        game = self.state.active_game(group_chat_id)
        return bool(game and self.state.lobby.assign_seat(game["id"], player_id, seat))

    def clear_seat(self, group_chat_id: int, player_id: int) -> bool:
        game = self.state.active_game(group_chat_id)
        return bool(game and self.state.lobby.clear_seat(game["id"], player_id))

    def promote_waiting(self, group_chat_id: int, seat: int):
        game = self.state.active_game(group_chat_id)
        return self.state.lobby.promote_waiting(game["id"], seat) if game else None

    def set_status(self, group_chat_id: int, player_id: int, status: str) -> bool:
        game = self.state.active_game(group_chat_id)
        return bool(game and self.state.lobby.set_status(game["id"], player_id, status))

    def snapshot(self, group_chat_id: int) -> dict[str, Any]:
        game = self.state.active_game(group_chat_id)
        if not game:
            return {"game": None, "players": [], "seats": {}, "waiting": []}
        return {
            "game": {
                "id": game["id"],
                "group_chat_id": game["group_chat_id"],
                "moderator_id": game.get("moderator_id"),
                "scenario_id": game.get("scenario_id"),
                "event_number": game.get("event_number"),
                "status": game.get("status"),
                "state": game.get("state") or {},
            },
            **self.state.lobby.snapshot(game["id"]),
        }

    def set_moderator(self, group_chat_id: int, moderator_id: int) -> bool:
        game = self.state.active_game(group_chat_id)
        return bool(game and self.state.lobby.set_moderator(game["id"], moderator_id))

    def set_scenario(self, group_chat_id: int, scenario_id: str) -> bool:
        game = self.state.active_game(group_chat_id)
        return bool(game and self.state.lobby.set_scenario(game["id"], scenario_id))

    def set_event_number(self, group_chat_id: int, event_number: int) -> bool:
        game = self.state.active_game(group_chat_id)
        return bool(game and self.state.lobby.set_event_number(game["id"], int(event_number)))

    def persist_legacy_state(self, group_chat_id: int, *, state: Optional[dict[str, Any]] = None,
                             current_turn_index: Optional[int] = None,
                             current_turn_seat: Optional[int] = None) -> bool:
        game = self.state.active_game(group_chat_id)
        if not game:
            return False
        return self.state.persist_lobby(game["id"], state=state,
                                        current_turn_index=current_turn_index,
                                        current_turn_seat=current_turn_seat)
