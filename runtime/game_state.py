from __future__ import annotations

from typing import Any, Optional

from repositories.game_repository import GameRepository
from repositories.turn_repository import TurnRepository
from repositories.challenge_repository import ChallengeRepository
from repositories.scenario_repository import ScenarioRepository
from services.lobby_service import LobbyService


class GameState:
    """Single persistence entry point for the game runtime.

    This facade deliberately keeps Telegram/UI concerns out of persistence.
    Legacy globals can be synchronized through this boundary during migration.
    """

    def __init__(self):
        self.games = GameRepository()
        self.turns = TurnRepository()
        self.challenges = ChallengeRepository()
        self.scenarios = ScenarioRepository()
        self.lobby = LobbyService(self.games)

    def active_game(self, group_chat_id: int):
        return self.games.get_active_game(group_chat_id)

    def active_games(self):
        return self.games.list_active_games()

    def ensure_lobby(self, group_chat_id: int, moderator_id: Optional[int] = None,
                     scenario_id: Optional[str] = None, event_number: Optional[int] = None):
        return self.lobby.get_or_create(group_chat_id, moderator_id, scenario_id, event_number)

    def persist_lobby(self, game_id: str, *, state: Optional[dict[str, Any]] = None,
                      current_turn_index: Optional[int] = None,
                      current_turn_seat: Optional[int] = None) -> bool:
        fields: dict[str, Any] = {}
        if state is not None:
            fields["state"] = state
        if current_turn_index is not None:
            fields["current_turn_index"] = current_turn_index
        if current_turn_seat is not None:
            fields["current_turn_seat"] = current_turn_seat
        return self.games.update_game(game_id, **fields) if fields else False

    def add_player(self, game_id: str, player_id: int, seat: Optional[int] = None,
                   is_substitute: bool = False) -> int:
        return self.lobby.join(game_id, player_id, seat, is_substitute)

    def public_players(self, game_id: str):
        return self.lobby.players(game_id)
