import os
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class DatabaseRepository:
    """Shared PostgreSQL connection policy for long-lived workers.

    The connection policy is intentionally conservative:
    - Do not resolve PostgreSQL DNS manually with socket.gethostbyname().
    - Let psycopg2/PostgreSQL resolve the hostname directly.
    - Reuse a very small connection pool.
    - Enable pool_pre_ping to detect stale connections.
    - Use SSL for Supabase PostgreSQL unless explicitly disabled.
    """

    def __init__(self, database_url=None):
        database_url = database_url or os.getenv("DATABASE_URL")

        if not database_url:
            raise RuntimeError("DATABASE_URL تنظیم نشده است")

        # Normalize PostgreSQL URLs for SQLAlchemy + psycopg2.
        if database_url.startswith("postgres://"):
            database_url = database_url.replace(
                "postgres://",
                "postgresql+psycopg2://",
                1,
            )
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace(
                "postgresql://",
                "postgresql+psycopg2://",
                1,
            )

        parsed = urlparse(database_url)
        hostname = parsed.hostname or ""

        connect_timeout = max(
            5,
            int(os.getenv("DB_CONNECT_TIMEOUT", "10")),
        )

        connect_args = {
            "connect_timeout": connect_timeout,
        }

        # Supabase PostgreSQL requires/recommends SSL.
        # Allow explicit override through DB_SSLMODE.
        sslmode = os.getenv("DB_SSLMODE")

        if not sslmode and hostname.endswith(".supabase.co"):
            sslmode = "require"

        if sslmode:
            connect_args["sslmode"] = sslmode

        serverless = (
            os.getenv("VERCEL") == "1"
            or bool(os.getenv("VERCEL_ENV"))
            or os.getenv("DB_POOL_MODE", "").lower()
            in {"null", "serverless"}
        )

        # Keep the pool deliberately small.
        #
        # Defaults:
        #   normal worker:  pool_size=2, max_overflow=1
        #   serverless:     pool_size=1, max_overflow=0
        #
        # Values can be overridden with environment variables.
        default_pool_size = 1 if serverless else 2
        default_max_overflow = 0 if serverless else 1

        pool_size = int(
            os.getenv("DB_POOL_SIZE", str(default_pool_size))
        )
        max_overflow = int(
            os.getenv("DB_MAX_OVERFLOW", str(default_max_overflow))
        )
        pool_recycle = int(
            os.getenv("DB_POOL_RECYCLE", "300")
        )

        pool_size = max(1, pool_size)
        max_overflow = max(0, max_overflow)
        pool_recycle = max(60, pool_recycle)

        engine_kwargs = {
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_recycle": pool_recycle,
            "pool_pre_ping": True,
            "pool_timeout": max(
                5,
                int(os.getenv("DB_POOL_TIMEOUT", "10")),
            ),
            "connect_args": connect_args,
        }

        self.engine = create_engine(
            database_url,
            **engine_kwargs,
        )

        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )

    def get_session(self):
        """Return a new SQLAlchemy session.

        The caller is responsible for closing the returned session.
        """
        return self.SessionLocal()
