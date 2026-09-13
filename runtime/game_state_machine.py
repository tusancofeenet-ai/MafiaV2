from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from runtime.game_state import GameState
from runtime.turn_runtime import PersistentTurnRuntime
from runtime.challenge_runtime import PersistentChallengeRuntime


class Phase(str, Enum):
    LOBBY = "lobby"
    RUNNING = "running"
    TURN = "turn"
    CHALLENGE = "challenge"
    VOTING = "voting"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass(frozen=True)
class Transition:
    phase: Phase
    previous_phase: Optional[Phase]
    game_id: str


class GameStateMachine:
    """Authoritative orchestration boundary for the persisted game lifecycle."""

    def __init__(self, state: Optional[GameState] = None):
        self.state = state or GameState()
        self.turns = PersistentTurnRuntime(self.state)
        self.challenges = PersistentChallengeRuntime(self.state)

    def snapshot(self, group_chat_id: int) -> dict[str, Any]:
        game = self.state.active_game(group_chat_id)
        if not game:
            return {"phase": Phase.FINISHED.value, "game": None, "turn": None, "challenge": None}
        turn = self.turns.current(group_chat_id)
        pending = self.challenges.pending(group_chat_id)
        payload = dict(game.get("state") or {})
        raw_status = str(game.get("status") or "lobby").lower()
        day_phase = str(payload.get("day_phase") or payload.get("phase") or "").lower()
        if raw_status in {"finished", "ended", "cancelled"}:
            phase = Phase.FINISHED
        elif raw_status == "paused":
            phase = Phase.PAUSED
        elif raw_status in {"lobby", "waiting"}:
            phase = Phase.LOBBY
        elif day_phase == Phase.VOTING.value or isinstance(payload.get("voting"), dict) and payload.get("voting", {}).get("phase") in {"waiting", "voting", "round_finished"}:
            phase = Phase.VOTING
        elif pending:
            phase = Phase.CHALLENGE
        elif turn:
            phase = Phase.TURN
        else:
            phase = Phase.RUNNING
        return {"phase": phase.value, "game": game, "turn": turn, "challenge": pending}

    def transition(self, group_chat_id: int, target: Phase) -> Transition:
        game = self.state.active_game(group_chat_id)
        if not game:
            raise ValueError("بازی فعالی برای این گروه وجود ندارد")
        raw_current = str(game.get("status") or "lobby").lower()
        current = Phase(raw_current) if raw_current in {p.value for p in Phase} else Phase.LOBBY
        allowed = {
            Phase.LOBBY: {Phase.RUNNING, Phase.FINISHED},
            Phase.RUNNING: {Phase.TURN, Phase.VOTING, Phase.FINISHED},
            Phase.TURN: {Phase.CHALLENGE, Phase.RUNNING, Phase.VOTING, Phase.FINISHED},
            Phase.CHALLENGE: {Phase.TURN, Phase.PAUSED, Phase.RUNNING, Phase.VOTING, Phase.FINISHED},
            Phase.VOTING: {Phase.RUNNING, Phase.FINISHED},
            Phase.PAUSED: {Phase.CHALLENGE, Phase.TURN, Phase.RUNNING, Phase.VOTING, Phase.FINISHED},
            Phase.FINISHED: set(),
        }
        if target not in allowed[current] and target != current:
            raise ValueError(f"انتقال نامعتبر: {current.value} -> {target.value}")
        self.state.games.update_game(game["id"], status=target.value)
        return Transition(target, current, game["id"])

    def recover(self, group_chat_id: int) -> dict[str, Any]:
        turn = self.turns.recover(group_chat_id)
        snapshot = self.snapshot(group_chat_id)
        return {"snapshot": snapshot, "turn_recovery": turn}

    def recover_all(self) -> list[dict[str, Any]]:
        return [self.recover(int(game["group_chat_id"])) for game in self.state.active_games()]
