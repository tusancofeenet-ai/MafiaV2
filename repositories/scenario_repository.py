from sqlalchemy import text
from .base import DatabaseRepository


class ScenarioRepository(DatabaseRepository):
    """Persistence for mafia_scenarios."""

    def list_active(self):
        with self.SessionLocal() as session:
            rows = session.execute(text(
                "select id, name, description, min_players, max_players, roles, config "
                "from public.mafia_scenarios where is_active = true "
                "order by sort_order nulls last, id"
            )).mappings().all()
            return [dict(row) for row in rows]

    def get_by_name(self, name):
        with self.SessionLocal() as session:
            row = session.execute(text(
                "select * from public.mafia_scenarios where name = :name limit 1"
            ), {"name": name}).mappings().first()
            return dict(row) if row else None

    def get_by_id(self, scenario_id):
        with self.SessionLocal() as session:
            row = session.execute(text(
                "select * from public.mafia_scenarios where id = :scenario_id limit 1"
            ), {"scenario_id": int(scenario_id)}).mappings().first()
            return dict(row) if row else None

    def upsert(self, name, description=None, min_players=None, max_players=None, roles=None, config=None, is_active=True):
        import json
        with self.SessionLocal() as session:
            row = session.execute(text(
                "insert into public.mafia_scenarios "
                "(name, description, min_players, max_players, roles, config, is_active, updated_at) "
                "values (:name, :description, :min_players, :max_players, cast(:roles as jsonb), cast(:config as jsonb), :is_active, now()) "
                "on conflict (name) do update set description = excluded.description, "
                "min_players = excluded.min_players, max_players = excluded.max_players, "
                "roles = excluded.roles, config = excluded.config, is_active = excluded.is_active, updated_at = now() "
                "returning id"
            ), {
                "name": name, "description": description, "min_players": min_players,
                "max_players": max_players, "roles": json.dumps(roles or [], ensure_ascii=False),
                "config": json.dumps(config or {}, ensure_ascii=False), "is_active": is_active,
            }).scalar_one()
            session.commit()
            return row

    def update_by_id(self, scenario_id, name, description=None, min_players=None, max_players=None, roles=None, config=None, is_active=True):
        """Update an existing scenario without creating a duplicate when its name changes."""
        import json
        with self.SessionLocal() as session:
            row = session.execute(text(
                "update public.mafia_scenarios set name=:name, description=:description, "
                "min_players=:min_players, max_players=:max_players, roles=cast(:roles as jsonb), "
                "config=cast(:config as jsonb), is_active=:is_active, updated_at=now() "
                "where id=:id returning id"
            ), {
                "id": int(scenario_id), "name": name, "description": description,
                "min_players": min_players, "max_players": max_players,
                "roles": json.dumps(roles or [], ensure_ascii=False),
                "config": json.dumps(config or {}, ensure_ascii=False), "is_active": is_active,
            }).scalar_one_or_none()
            if row is None:
                raise ValueError("scenario not found")
            session.commit()
            return row

    def set_active(self, scenario_id, is_active=False):
        with self.SessionLocal() as session:
            row = session.execute(text(
                "update public.mafia_scenarios set is_active=:active, updated_at=now() "
                "where id=:id returning id"
            ), {"id": int(scenario_id), "active": bool(is_active)}).scalar_one_or_none()
            if row is None:
                raise ValueError("scenario not found")
            session.commit()
            return row
