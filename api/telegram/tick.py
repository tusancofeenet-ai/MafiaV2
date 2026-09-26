
"""Durable scheduler tick for MafiaNights voting deadlines."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time

from sqlalchemy import text
from repositories.base import DatabaseRepository

_runtime_module = None
_startup_complete = False
_loop: asyncio.AbstractEventLoop | None = None
_last_tick_at = 0.0
_MIN_TICK_INTERVAL = float(os.getenv("TICK_MIN_INTERVAL", "4"))


def _response(body, status="200 OK"):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return (
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(raw))),
        ],
        raw,
    )


def _has_due_vote() -> bool:
    """Cheap database gate: avoid booting the full bot for idle cron ticks."""
    repo = DatabaseRepository()
    with repo.engine.begin() as conn:
        row = conn.execute(text("""
            select 1
            from public.mafia_games
            where coalesce(state->'voting'->>'phase', '') in ('waiting', 'voting')
              and nullif(state->'voting'->>'deadline', '') is not null
              and (state->'voting'->>'deadline')::double precision
                  <= extract(epoch from now())
            limit 1
        """)).first()
        return row is not None


def _runtime():
    global _runtime_module
    if _runtime_module is None:
        import player_runtime_entry
        _runtime_module = player_runtime_entry
    return _runtime_module


async def _tick():
    global _startup_complete
    runtime_entry = _runtime()

    if not _startup_complete:
        try:
            await runtime_entry.on_startup(runtime_entry.main.dp)
        except Exception:
            # Startup helpers are best-effort for the scheduler.
            logging.exception(
                "VOTING TICK STARTUP FAILED; continuing"
            )
        finally:
            _startup_complete = True

    from runtime import voting_runtime
    return bool(await voting_runtime.tick(runtime_entry.main))


def _run(coro):
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()

    asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


def app(environ, start_response):
    global _last_tick_at

    result = {}
    now = time.monotonic()

    if now - _last_tick_at < _MIN_TICK_INTERVAL:
        result.update({
            "ok": True,
            "processed": False,
            "skipped": "rate_limited",
        })
        status, headers, body = _response(result)
        start_response(status, headers)
        return [body]

    _last_tick_at = now

    try:
        if not _has_due_vote():
            result.update({
                "ok": True,
                "processed": False,
                "skipped": "no_due_vote",
            })
            status, headers, body = _response(result)
            start_response(status, headers)
            return [body]

        changed = _run(_tick())
        result.update({
            "ok": True,
            "processed": changed,
        })

    except Exception as exc:
        logging.exception("VOTING TICK FAILED")
        result.update({
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        })

    status, headers, body = _response(result)
    start_response(status, headers)
    return [body]


handler = app
