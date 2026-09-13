"""PostgreSQL-backed aiogram 2 FSM storage for webhook/serverless runtimes."""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from repositories.base import DatabaseRepository


class PostgresFSMStorage(DatabaseRepository):
    """aiogram 2.25-compatible persistent storage backed by PostgreSQL."""

    def __init__(self, database_url: str | None = None):
        super().__init__(database_url)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("""
                create table if not exists public.mafia_fsm_state (
                    chat_id text not null,
                    user_id text not null,
                    state text,
                    data jsonb not null default '{}'::jsonb,
                    bucket jsonb not null default '{}'::jsonb,
                    updated_at timestamptz not null default now(),
                    primary key (chat_id, user_id)
                )
            """))

    @staticmethod
    def check_address(*, chat: Any = None, user: Any = None) -> tuple[Any, Any]:
        if chat is None and user is None:
            raise ValueError("Both chat and user can't be None")
        return chat if chat is not None else user, user if user is not None else chat

    @staticmethod
    def resolve_state(state: Any = None):
        return None if state is None else getattr(state, "state", state)

    @staticmethod
    def _ids(chat: Any, user: Any) -> tuple[str, str]:
        chat, user = PostgresFSMStorage.check_address(chat=chat, user=user)
        return str(chat), str(user)

    def _ensure_row(self, chat: Any, user: Any) -> None:
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("""
                insert into public.mafia_fsm_state(chat_id,user_id)
                values (:chat_id,:user_id) on conflict (chat_id,user_id) do nothing
            """), {"chat_id": chat_id, "user_id": user_id})

    async def get_state(self, *, chat=None, user=None, default=None):
        self._ensure_row(chat, user)
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            value = conn.execute(text("select state from public.mafia_fsm_state where chat_id=:chat_id and user_id=:user_id"), {"chat_id": chat_id, "user_id": user_id}).scalar()
        return self.resolve_state(default) if value is None else value

    async def set_state(self, *, chat=None, user=None, state=None):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("update public.mafia_fsm_state set state=:state,updated_at=now() where chat_id=:chat_id and user_id=:user_id"), {"chat_id": chat_id, "user_id": user_id, "state": self.resolve_state(state)})

    async def get_data(self, *, chat=None, user=None, default=None):
        self._ensure_row(chat, user)
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            value = conn.execute(text("select data from public.mafia_fsm_state where chat_id=:chat_id and user_id=:user_id"), {"chat_id": chat_id, "user_id": user_id}).scalar()
        return dict(value or (default or {}))

    async def set_data(self, *, chat=None, user=None, data=None):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("update public.mafia_fsm_state set data=CAST(:data AS jsonb),updated_at=now() where chat_id=:chat_id and user_id=:user_id"), {"chat_id": chat_id, "user_id": user_id, "data": json.dumps(data or {}, ensure_ascii=False)})

    async def update_data(self, *, chat=None, user=None, data=None, **kwargs):
        current = await self.get_data(chat=chat, user=user)
        current.update(data or {})
        current.update(kwargs)
        await self.set_data(chat=chat, user=user, data=current)
        return current

    async def reset_state(self, *, chat=None, user=None, with_data=True):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            sql = "update public.mafia_fsm_state set state=null,data='{}'::jsonb,updated_at=now() where chat_id=:chat_id and user_id=:user_id" if with_data else "update public.mafia_fsm_state set state=null,updated_at=now() where chat_id=:chat_id and user_id=:user_id"
            conn.execute(text(sql), {"chat_id": chat_id, "user_id": user_id})

    async def finish(self, *, chat=None, user=None):
        await self.reset_state(chat=chat, user=user, with_data=True)

    def has_bucket(self):
        return True

    async def get_bucket(self, *, chat=None, user=None, default=None):
        self._ensure_row(chat, user)
        chat_id, user_id = self._ids(chat, user)
        with self.engine.begin() as conn:
            value = conn.execute(text("select bucket from public.mafia_fsm_state where chat_id=:chat_id and user_id=:user_id"), {"chat_id": chat_id, "user_id": user_id}).scalar()
        return dict(value or (default or {}))

    async def set_bucket(self, *, chat=None, user=None, bucket=None):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat, user)
        with self.engine.begin() as conn:
            conn.execute(text("update public.mafia_fsm_state set bucket=CAST(:bucket AS jsonb),updated_at=now() where chat_id=:chat_id and user_id=:user_id"), {"chat_id": chat_id, "user_id": user_id, "bucket": json.dumps(bucket or {}, ensure_ascii=False)})

    async def update_bucket(self, *, chat=None, user=None, bucket=None, **kwargs):
        current = await self.get_bucket(chat=chat, user=user)
        current.update(bucket or {})
        current.update(kwargs)
        await self.set_bucket(chat=chat, user=user, bucket=current)
        return current

    async def reset_bucket(self, *, chat=None, user=None):
        await self.set_bucket(chat=chat, user=user, bucket={})

    async def close(self):
        self.engine.dispose()

    async def wait_closed(self):
        return None


def install(app) -> bool:
    if getattr(app, "_postgres_fsm_storage_installed", False):
        return False
    try:
        storage = PostgresFSMStorage()
    except Exception:
        logging.exception("PostgreSQL FSM storage could not be initialized; keeping existing storage")
        return False
    app.dp.storage = storage
    app._postgres_fsm_storage = storage
    app._postgres_fsm_storage_installed = True
    logging.info("PostgreSQL FSM storage installed")
    return True
