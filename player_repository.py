from sqlalchemy import text
from repositories.base import DatabaseRepository


class PlayerRepository(DatabaseRepository):
    """دسترسی متمرکز به جدول mafia_players."""

    def upsert(self, user_id, full_name=None, username=None):
        user_id = int(user_id)
        full_name = (full_name or "").strip() or None
        username = (username or "").strip() or None
        first_name = None
        last_name = None
        if full_name:
            parts = full_name.split(None, 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else None

        with self.SessionLocal() as session:
            session.execute(
                text("""
                    insert into public.mafia_players
                        (user_id, id, username, first_name, last_name, updated_at)
                    values
                        (:user_id, :id, :username, :first_name, :last_name, now())
                    on conflict (user_id) do update set
                        username = coalesce(excluded.username, public.mafia_players.username),
                        first_name = coalesce(excluded.first_name, public.mafia_players.first_name),
                        last_name = coalesce(excluded.last_name, public.mafia_players.last_name),
                        updated_at = now()
                """),
                {
                    "user_id": user_id,
                    "id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                },
            )
            session.commit()

    def get(self, user_id):
        with self.SessionLocal() as session:
            row = session.execute(
                text("""
                    select user_id, id, username, first_name, last_name, nickname
                    from public.mafia_players
                    where user_id = :user_id
                """), {"user_id": int(user_id)}
            ).mappings().first()
            return dict(row) if row else None

    def get_display_name(self, user_id, fallback="❓"):
        row = self.get(user_id)
        if not row:
            return fallback
        nickname = (row.get("nickname") or "").strip()
        if nickname:
            return nickname
        real_name = " ".join(
            p for p in ((row.get("first_name") or "").strip(), (row.get("last_name") or "").strip()) if p
        )
        return real_name or (row.get("username") or fallback)

    def set_nickname(self, user_id, nickname):
        nickname = (nickname or "").strip()
        if not nickname:
            return False
        with self.SessionLocal() as session:
            result = session.execute(
                text("update public.mafia_players set nickname=:nickname, updated_at=now() where user_id=:user_id"),
                {"user_id": int(user_id), "nickname": nickname},
            )
            session.commit()
            return result.rowcount > 0

    def delete_nickname(self, user_id):
        with self.SessionLocal() as session:
            result = session.execute(
                text("update public.mafia_players set nickname=null, updated_at=now() where user_id=:user_id"),
                {"user_id": int(user_id)},
            )
            session.commit()
            return result.rowcount > 0

    def all_nicknames(self):
        with self.SessionLocal() as session:
            rows = session.execute(
                text("""
                    select user_id, nickname from public.mafia_players
                    where nickname is not null and trim(nickname) <> ''
                    order by lower(nickname)
                """)
            ).mappings().all()
            return {int(row["user_id"]): row["nickname"] for row in rows}
