"""Persistent scheduler tick for MafiaNights voting deadlines."""
from __future__ import annotations

import asyncio
import json
import os
import time


def _response(body, status="200 OK"):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return status, [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(raw)))], raw


def app(environ, start_response):
    # Supabase pg_cron invokes this endpoint every 10 seconds. Use the patched
    # runtime helpers installed by main.py and keep each transition idempotent.
    try:
        import main
        from runtime import voting_runtime

        gid = int(os.getenv("ALLOWED_GROUP_ID", "-1002356353761"))
        app_obj = main.app
        app_obj.group_chat_id = gid
        app_obj.ui.group_chat_id = gid
        game = app_obj.runtime.state.active_game(gid)
        voting = dict((game or {}).get("state", {}).get("voting") or {})
        deadline = voting.get("deadline")
        phase = str(voting.get("phase") or "")
        now = time.time()

        if deadline and float(deadline) <= now and phase == "waiting":
            asyncio.run(voting_runtime._start_target(app_obj))
            result = {"ok": True, "processed": True, "action": "start_target", "phase": phase}
        elif deadline and float(deadline) <= now and phase == "voting":
            asyncio.run(voting_runtime._end_target(app_obj))
            after_game = app_obj.runtime.state.active_game(gid)
            after = dict((after_game or {}).get("state", {}).get("voting") or {})
            result = {"ok": True, "processed": True, "action": "end_target", "phase": phase, "next_phase": str(after.get("phase") or ""), "target_index": int(after.get("target_index") or 0)}
        elif phase == "next_target_pending":
            asyncio.run(voting_runtime._start_target(app_obj))
            result = {"ok": True, "processed": True, "action": "next_target", "phase": phase}
        elif phase == "round_finished_pending":
            asyncio.run(voting_runtime._finish_round(app_obj))
            result = {"ok": True, "processed": True, "action": "finish_round", "phase": phase}
        else:
            result = {"ok": True, "processed": False, "phase": phase}
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    status, headers, body = _response(result)
    start_response(status, headers)
    return [body]


handler = app
