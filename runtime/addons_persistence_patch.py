"""Move MafiaAddons group settings off Vercel's read-only filesystem."""
from __future__ import annotations

import copy
import json
import logging
import types

from repositories.base import DatabaseRepository
from mafia_addons import DEFAULT_GROUP_SETTINGS


def install(app):
    addons = getattr(app, "addons", None)
    if addons is None or getattr(addons, "_db_persistence_installed", False):
        return False
    try:
        repo = DatabaseRepository()
    except Exception:
        logging.exception("addons persistence: database repository unavailable")
        return False

    original_get = addons.get_group_settings
    original_set = addons.set_group_settings

    def get_group_settings(self, group_id):
        try:
            with repo.SessionLocal() as session:
                from sqlalchemy import text
                row = session.execute(
                    text("select settings from public.mafia_addon_settings where group_id=:gid"),
                    {"gid": int(group_id)},
                ).mappings().first()
                if row:
                    value = row["settings"] or {}
                    return value if isinstance(value, dict) else copy.deepcopy(DEFAULT_GROUP_SETTINGS)
        except Exception:
            logging.warning("addons persistence: DB read failed; using compatibility settings", exc_info=True)
        return original_get(group_id)

    def set_group_settings(self, group_id, settings_dict):
        self._all_settings[str(group_id)] = settings_dict
        if self.group_id and str(self.group_id) == str(group_id):
            self.settings = settings_dict
        try:
            with repo.SessionLocal() as session:
                from sqlalchemy import text
                session.execute(
                    text("""
                        insert into public.mafia_addon_settings (group_id, settings, updated_at)
                        values (:gid, :settings::jsonb, now())
                        on conflict (group_id) do update set
                          settings=excluded.settings,
                          updated_at=now()
                    """),
                    {"gid": int(group_id), "settings": json.dumps(settings_dict or {}, ensure_ascii=False)},
                )
                session.commit()
        except Exception:
            logging.warning("addons persistence: DB write failed; keeping in-memory settings", exc_info=True)

    addons.get_group_settings = types.MethodType(get_group_settings, addons)
    addons.set_group_settings = types.MethodType(set_group_settings, addons)
    addons._addons_repository = repo
    addons._db_persistence_installed = True
    return True
