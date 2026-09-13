"""Database-backed scenario persistence boundary.

The legacy module still exposes ``save_scenarios()`` and keeps a compatibility
``scenarios`` dictionary. On Vercel that dictionary/file cannot be the source of
truth, so this patch redirects saves to the existing PostgreSQL
``mafia_scenarios`` repository and hydrates the compatibility dictionary from
that table on every cold import.
"""
from __future__ import annotations

import logging

from repositories.scenario_repository import ScenarioRepository


def _normalise(row):
    roles = row.get("roles") or []
    if isinstance(roles, str):
        roles = [x.strip() for x in roles.split(",") if x.strip()]
    return {
        "roles": list(roles),
        "min_players": int(row.get("min_players") or 1),
        "max_players": int(row.get("max_players") or len(roles)),
    }


def _load(repo, app):
    rows = repo.list_active()
    if rows:
        app.scenarios = {str(row["name"]): _normalise(row) for row in rows}
        return len(rows)
    # First migration: seed the DB from the committed scenarios.json only once.
    source = getattr(app, "scenarios", {}) or {}
    for name, value in source.items():
        if not isinstance(value, dict):
            continue
        repo.upsert(
            name=str(name),
            description=value.get("description"),
            min_players=int(value.get("min_players") or 1),
            max_players=int(value.get("max_players") or len(value.get("roles") or [])),
            roles=value.get("roles") or [],
            config=value.get("config") or {},
            is_active=True,
        )
    rows = repo.list_active()
    if rows:
        app.scenarios = {str(row["name"]): _normalise(row) for row in rows}
    return len(rows)


def install(app):
    if getattr(app, "_scenario_persistence_patch_installed", False):
        return False

    repo = ScenarioRepository()
    try:
        count = _load(repo, app)
    except Exception:
        logging.exception("Scenario DB hydration failed; keeping committed scenarios.json fallback")
        count = 0

    def save_scenarios():
        """Compatibility API: persist the complete in-memory scenario map to DB."""
        scenarios = getattr(app, "scenarios", {}) or {}
        try:
            for name, value in scenarios.items():
                value = value if isinstance(value, dict) else {}
                roles = value.get("roles") or []
                repo.upsert(
                    name=str(name),
                    description=value.get("description"),
                    min_players=int(value.get("min_players") or 1),
                    max_players=int(value.get("max_players") or len(roles)),
                    roles=roles,
                    config=value.get("config") or {},
                    is_active=True,
                )
            active = {str(x["name"]) for x in repo.list_active()}
            for name in active - {str(x) for x in scenarios.keys()}:
                with repo.engine.begin() as conn:
                    from sqlalchemy import text
                    conn.execute(text("update public.mafia_scenarios set is_active=false, updated_at=now() where name=:name"), {"name": name})
            return True
        except Exception:
            logging.exception("Scenario DB save failed")
            return False

    app.save_scenarios = save_scenarios
    app._scenario_repository = repo
    app._scenario_persistence_patch_installed = True
    logging.info("Scenario DB authority installed; active scenarios=%d", count)
    return True
