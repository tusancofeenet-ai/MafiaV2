import os
import socket
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


class DatabaseRepository:
    """Shared PostgreSQL connection policy for long-lived and Vercel workers.

    Vercel Python workers can serve multiple webhook requests before being
    recycled. Using NullPool here forced a brand-new PostgreSQL connection for
    practically every repository operation; together with pool_pre_ping this
    added an avoidable network round-trip (and made Telegram callback queries
    expire while the DB connection was being established). Keep a tiny pool
    alive inside the worker instead.
    """

    def __init__(self, database_url=None):
        database_url = database_url or os.getenv("DATABASE_URL")
        if not database_url:
            raise RuntimeError("DATABASE_URL تنظیم نشده است")

        if database_url.startswith("postgres://"):
            database_url = database_url.replace("postgres://", "postgresql+psycopg2://", 1)
        elif database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+psycopg2://", 1)

        connect_args = {
            "connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
        }
        try:
            host = urlparse(database_url).hostname
            if host:
                connect_args["hostaddr"] = socket.gethostbyname(host)
        except (OSError, ValueError):
            pass

        serverless = (
            os.getenv("VERCEL") == "1"
            or bool(os.getenv("VERCEL_ENV"))
            or os.getenv("DB_POOL_MODE", "").lower() in {"null", "serverless"}
        )

        # Reuse connections while the Python worker is warm. A one-connection
        # pool is enough for the webhook workload and prevents a burst of
        # Telegram callbacks from opening a large number of DB connections.
        pool_size = int(os.getenv("DB_POOL_SIZE", "1" if serverless else "2"))
        max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "0" if serverless else "1"))
        pool_recycle = int(os.getenv("DB_POOL_RECYCLE", "300"))

        engine_kwargs = {
            "pool_pre_ping": False,
            "pool_size": max(1, pool_size),
            "max_overflow": max(0, max_overflow),
            "pool_recycle": max(60, pool_recycle),
            "connect_args": connect_args,
        }

        self.engine = create_engine(database_url, **engine_kwargs)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
