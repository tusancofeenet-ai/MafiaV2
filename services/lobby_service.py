from __future__ import annotations

from typing import Any, Dict, Optional

from repositories.game_repository import GameRepository


class LobbyService:
    """Authoritative lobby facade backed by Supabase/PostgreSQL."""

    def __init__(self, repository: Optional[GameRepository] = None):
        self.repository = repository or GameRepository()

    def get_or_create(self, group_chat_id: int, moderator_id: Optional[int] = None,
                      scenario_id: Optional[str] = None, event_number: Optional[int] = None) -> Dict[str, Any]:
        game = self.repository.get_active_game(group_chat_id)
        if game:
            return game
        if event_number is None:
            event_number = self.repository.next_event_number(group_chat_id)
        event_number = int(event_number)
        if event_number < 1:
            raise ValueError("شماره بازی باید حداقل ۱ باشد")
        game_id = self.repository.create_game(group_chat_id=group_chat_id, moderator_id=moderator_id, scenario_id=scenario_id, event_number=event_number, state={"phase": "lobby", "waiting": [], "seat_count": 0})
        return self.repository.get_active_game(group_chat_id) or {"id": game_id, "group_chat_id": group_chat_id, "event_number": event_number}

    def start_new(self, group_chat_id: int, event_number: Optional[int] = None) -> Dict[str, Any]:
        active = self.repository.get_active_game(group_chat_id)
        if active:
            status = str(active.get("status") or "")
            if status in {"running", "paused"}: raise RuntimeError("یک بازی در حال اجراست و امکان ایجاد بازی جدید وجود ندارد")
            if status == "lobby": self.repository.update_game(active["id"], status="finished")
        if event_number is None: event_number = self.repository.next_event_number(group_chat_id)
        number = int(event_number)
        if number < 1: raise ValueError("شماره بازی باید حداقل ۱ باشد")
        game_id = self.repository.create_game(group_chat_id=group_chat_id, moderator_id=None, scenario_id=None, event_number=number, state={"phase": "scenario_selection", "waiting": [], "seat_count": 0})
        return self.repository.get_active_game(group_chat_id) or {"id": game_id, "group_chat_id": int(group_chat_id), "event_number": number, "status": "lobby", "scenario_id": None, "moderator_id": None}

    def set_event_number(self, game_id: str, event_number: int) -> bool:
        number = int(event_number)
        if number < 1: raise ValueError("شماره بازی باید حداقل ۱ باشد")
        return self.repository.update_game(game_id, event_number=number)

    def set_scenario(self, game_id: str, scenario_id: str) -> bool: return self.repository.update_game(game_id, scenario_id=scenario_id)
    def set_moderator(self, game_id: str, moderator_id: int) -> bool: return self.repository.update_game(game_id, moderator_id=int(moderator_id))
    def join(self, game_id: str, player_id: int, seat: Optional[int] = None, is_substitute: bool = False) -> int:
        resolved_game_id = int(game_id)
        # Backward compatibility: older handlers passed group_chat_id here.
        active = self.repository.get_active_game(int(game_id))
        if active:
            resolved_game_id = int(active["id"])
        return self.repository.add_player(game_id=resolved_game_id, player_id=player_id, seat=seat, status="waiting" if seat is None else "active", is_substitute=is_substitute)
    def leave(self, game_id: str, player_id: int) -> bool: return self.repository.remove_player(game_id, player_id)
    def assign_seat(self, game_id: str, player_id: int, seat: int) -> bool: return self.repository.set_player_seat(game_id, player_id, seat)
    def clear_seat(self, game_id: str, player_id: int) -> bool: return self.repository.set_player_seat(game_id, player_id, None)

    def set_status(self, game_id: str, player_id: int, status: str) -> bool:
        allowed = {"active", "waiting", "removed", "substitute", "finished"}
        if status not in allowed: raise ValueError(f"وضعیت نامعتبر: {status}")
        return self.repository.set_player_status(game_id, player_id, status)

    def promote_waiting(self, game_id: str, seat: int): return self.repository.promote_waiting_player(game_id, seat)

    def players(self, game_id: str) -> list[dict[str, Any]]:
        rows = self.repository.list_players(game_id)
        return [{
            "id": row.get("id"), "player_id": row.get("player_id"), "seat": row.get("seat"), "status": row.get("status"),
            "role": row.get("role"), "is_alive": row.get("is_alive", True), "is_substitute": row.get("is_substitute", False),
            "username": row.get("username"), "first_name": row.get("first_name"), "last_name": row.get("last_name"), "nickname": row.get("nickname"),
        } for row in rows]

    def snapshot(self, game_id: str) -> Dict[str, Any]:
        rows = self.players(game_id)
        return {"players": rows, "seats": {str(row["seat"]): row["player_id"] for row in rows if row.get("seat") is not None}, "waiting": [row["player_id"] for row in rows if row.get("seat") is None and row.get("status") == "waiting"]}
