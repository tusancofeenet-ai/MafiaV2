"""PostgreSQL-backed aiogram 2 FSM storage for webhook/serverless runtimes."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import text

from repositories.base import DatabaseRepository


logger = logging.getLogger(__name__)


class PostgresFSMStorage(DatabaseRepository):
    """aiogram 2.25-compatible persistent FSM storage backed by PostgreSQL."""

    TABLE_NAME = "public.mafia_fsm_state"

    def __init__(self, database_url: str | None = None):
        super().__init__(database_url)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create the FSM table if it does not already exist."""

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS public.mafia_fsm_state (
                        chat_id TEXT NOT NULL,
                        user_id TEXT NOT NULL,
                        state TEXT,
                        data JSONB NOT NULL DEFAULT '{}'::jsonb,
                        bucket JSONB NOT NULL DEFAULT '{}'::jsonb,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (chat_id, user_id)
                    )
                    """
                )
            )

    @staticmethod
    def check_address(
        *,
        chat: Any = None,
        user: Any = None,
    ) -> tuple[Any, Any]:
        """Resolve aiogram FSM chat/user identifiers."""

        if chat is None and user is None:
            raise ValueError("Both chat and user can't be None")

        resolved_chat = chat if chat is not None else user
        resolved_user = user if user is not None else chat

        return resolved_chat, resolved_user

    @staticmethod
    def resolve_state(state: Any = None) -> Any:
        """Normalize aiogram state objects into their string value."""

        if state is None:
            return None

        return getattr(state, "state", state)

    @staticmethod
    def _ids(chat: Any, user: Any) -> tuple[str, str]:
        chat, user = PostgresFSMStorage.check_address(
            chat=chat,
            user=user,
        )

        return str(chat), str(user)

    def _ensure_row(self, chat: Any, user: Any) -> None:
        """Ensure that an FSM row exists for the requested user."""

        chat_id, user_id = self._ids(chat, user)

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO public.mafia_fsm_state (
                        chat_id,
                        user_id
                    )
                    VALUES (
                        :chat_id,
                        :user_id
                    )
                    ON CONFLICT (chat_id, user_id)
                    DO NOTHING
                    """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                },
            )

    async def get_state(
        self,
        *,
        chat=None,
        user=None,
        default=None,
    ):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat_id, user_id)

        with self.engine.connect() as conn:
            value = conn.execute(
                text(
                    """
                    SELECT state
                    FROM public.mafia_fsm_state
                    WHERE chat_id = :chat_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                },
            ).scalar()

        return self.resolve_state(default) if value is None else value

    async def set_state(
        self,
        *,
        chat=None,
        user=None,
        state=None,
    ):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat_id, user_id)

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.mafia_fsm_state
                    SET
                        state = :state,
                        updated_at = now()
                    WHERE chat_id = :chat_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "state": self.resolve_state(state),
                },
            )

    async def get_data(
        self,
        *,
        chat=None,
        user=None,
        default=None,
    ):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat_id, user_id)

        with self.engine.connect() as conn:
            value = conn.execute(
                text(
                    """
                    SELECT data
                    FROM public.mafia_fsm_state
                    WHERE chat_id = :chat_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                },
            ).scalar()

        return dict(value or (default or {}))

    async def set_data(
        self,
        *,
        chat=None,
        user=None,
        data=None,
    ):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat_id, user_id)

        payload = json.dumps(
            data or {},
            ensure_ascii=False,
        )

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.mafia_fsm_state
                    SET
                        data = CAST(:data AS jsonb),
                        updated_at = now()
                    WHERE chat_id = :chat_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "data": payload,
                },
            )

    async def update_data(
        self,
        *,
        chat=None,
        user=None,
        data=None,
        **kwargs,
    ):
        current = await self.get_data(
            chat=chat,
            user=user,
        )

        current.update(data or {})
        current.update(kwargs)

        await self.set_data(
            chat=chat,
            user=user,
            data=current,
        )

        return current

    async def reset_state(
        self,
        *,
        chat=None,
        user=None,
        with_data=True,
    ):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat_id, user_id)

        if with_data:
            sql = """
                UPDATE public.mafia_fsm_state
                SET
                    state = NULL,
                    data = '{}'::jsonb,
                    updated_at = now()
                WHERE chat_id = :chat_id
                  AND user_id = :user_id
            """
        else:
            sql = """
                UPDATE public.mafia_fsm_state
                SET
                    state = NULL,
                    updated_at = now()
                WHERE chat_id = :chat_id
                  AND user_id = :user_id
            """

        with self.engine.begin() as conn:
            conn.execute(
                text(sql),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                },
            )

    async def finish(
        self,
        *,
        chat=None,
        user=None,
    ):
        await self.reset_state(
            chat=chat,
            user=user,
            with_data=True,
        )

    def has_bucket(self):
        return True

    async def get_bucket(
        self,
        *,
        chat=None,
        user=None,
        default=None,
    ):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat_id, user_id)

        with self.engine.connect() as conn:
            value = conn.execute(
                text(
                    """
                    SELECT bucket
                    FROM public.mafia_fsm_state
                    WHERE chat_id = :chat_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                },
            ).scalar()

        return dict(value or (default or {}))

    async def set_bucket(
        self,
        *,
        chat=None,
        user=None,
        bucket=None,
    ):
        chat_id, user_id = self._ids(chat, user)
        self._ensure_row(chat_id, user_id)

        payload = json.dumps(
            bucket or {},
            ensure_ascii=False,
        )

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.mafia_fsm_state
                    SET
                        bucket = CAST(:bucket AS jsonb),
                        updated_at = now()
                    WHERE chat_id = :chat_id
                      AND user_id = :user_id
                    """
                ),
                {
                    "chat_id": chat_id,
                    "user_id": user_id,
                    "bucket": payload,
                },
            )

    async def update_bucket(
        self,
        *,
        chat=None,
        user=None,
        bucket=None,
        **kwargs,
    ):
        current = await self.get_bucket(
            chat=chat,
            user=user,
        )

        current.update(bucket or {})
        current.update(kwargs)

        await self.set_bucket(
            chat=chat,
            user=user,
            bucket=current,
        )

        return current

    async def reset_bucket(
        self,
        *,
        chat=None,
        user=None,
    ):
        await self.set_bucket(
            chat=chat,
            user=user,
            bucket={},
        )

    async def close(self):
        """Dispose SQLAlchemy connections."""

        self.engine.dispose()

    async def wait_closed(self):
        return None


def install(app) -> bool:
    """Install PostgreSQL FSM storage on the application.

    A failed PostgreSQL initialization is considered fatal for production
    because silently falling back to in-memory FSM storage can cause state
    corruption or unexpected game behaviour after worker restarts.
    """

    if getattr(
        app,
        "_postgres_fsm_storage_installed",
        False,
    ):
        return False

    storage = PostgresFSMStorage()

    app.dp.storage = storage
    app._postgres_fsm_storage = storage
    app._postgres_fsm_storage_installed = True

    logger.info("PostgreSQL FSM storage installed")

    return True
