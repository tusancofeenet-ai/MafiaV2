"""MafiaNights player scoring rules.

Base rating is 50. Per-game rating rows store the delta and its exact
components so the profile can explain every point gained or lost.
"""
from __future__ import annotations

import html
import logging
from typing import Any

from repositories.rating_repository import RatingRepository
import runtime.game_end as game_end

BASE_SCORE = 50
WIN_POINTS = 20
CHALLENGE_POINTS = 3
KICK_PENALTY = 20
WARNING_PENALTIES = (1, 2, 3, 4, 5)


def warning_penalty(count: int) -> int:
    count = max(0, int(count))
    if count <= len(WARNING_PENALTIES):
        return sum(WARNING_PENALTIES[:count])
    return sum(WARNING_PENALTIES) + sum(range(len(WARNING_PENALTIES) + 1, count + 1))


def _count_challenges(app: Any, game_id: int, user_id: int) -> int:
    try:
        rows = app.runtime.state.challenges.list_challenges(int(game_id))
        return sum(1 for row in rows if int(row.get("target_id") or 0) == int(user_id) and str(row.get("status") or "").lower() not in {"cancelled", "canceled", "rejected"})
    except Exception:
        logging.exception("failed to count challenges game=%s user=%s", game_id, user_id)
        return 0


def _warning_count(row: dict[str, Any], state: dict[str, Any]) -> int:
    warnings = state.get("warnings") or {}
    value = warnings.get(str(int(row.get("player_id") or 0)))
    if value is None:
        value = row.get("warning_count", 0)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _is_kicked(row: dict[str, Any], state: dict[str, Any]) -> bool:
    kicked = state.get("kicked_players") or {}
    return bool(kicked.get(str(int(row.get("player_id") or 0)))) or str(row.get("status") or "") == "kicked"


def score_game(app: Any, game: dict[str, Any], rows: list[dict[str, Any]], winner: str) -> None:
    """Record exactly one rating delta per player for a finalized game."""
    repo = RatingRepository()
    state = dict(game.get("state") or {})
    recorded = {str(x) for x in (state.get("rating_recorded_players") or [])}

    for row in rows:
        uid = int(row["player_id"])
        key = str(uid)
        if key in recorded:
            continue
        side = game_end._role_side(row, state)
        win_bonus = WIN_POINTS if winner != "draw" and side == winner else 0
        challenge_count = _count_challenges(app, int(game["id"]), uid)
        challenge_bonus = challenge_count * CHALLENGE_POINTS
        warnings = _warning_count(row, state)
        warning_total = warning_penalty(warnings)
        kicked = _is_kicked(row, state)
        kick_penalty = KICK_PENALTY if kicked else 0
        delta = win_bonus + challenge_bonus - warning_total - kick_penalty
        result = "draw" if winner == "draw" else ("win" if side == winner else "loss")
        try:
            repo.record(
                uid,
                int(game["id"]),
                int(delta),
                result,
                str(row.get("role") or ""),
                win_bonus=win_bonus,
                challenge_bonus=challenge_bonus,
                warning_penalty=warning_total,
                kick_penalty=kick_penalty,
            )
            recorded.add(key)
        except Exception:
            logging.exception("failed to record rating game=%s user=%s", game.get("id"), uid)

    state["rating_recorded_players"] = sorted(recorded)
    app.runtime.state.games.update_game(game["id"], state=state)


def _patch_final_report() -> None:
    if getattr(game_end, "_score_final_report_patched", False):
        return
    original = game_end._final_text

    def final_text(game: dict[str, Any], rows: list[dict[str, Any]]) -> str:
        text = original(game, rows)
        state = dict(game.get("state") or {})
        kicked = {str(k) for k, v in (state.get("kicked_players") or {}).items() if v}
        for row in rows:
            if str(int(row.get("player_id") or 0)) not in kicked:
                continue
            seat = int(row.get("seat") or 0)
            name = str(row.get("nickname") or row.get("first_name") or row.get("username") or row.get("player_id") or "👤")
            text = text.replace(f"{seat:02d} {html.escape(name)}", f"{seat:02d} 🚫 {html.escape(name)}", 1)
        return text

    game_end._final_text = final_text
    game_end._score_final_report_patched = True


def install(app: Any) -> bool:
    """Replace legacy end-game scoring and mark kicked players in reports."""
    game_end._score_players = lambda app_, game_, rows_, winner_: score_game(app_, game_, rows_, winner_)
    _patch_final_report()
    app.player_scoring = {
        "base": BASE_SCORE,
        "win": WIN_POINTS,
        "challenge": CHALLENGE_POINTS,
        "kick": KICK_PENALTY,
        "warnings": WARNING_PENALTIES,
    }
    return True
