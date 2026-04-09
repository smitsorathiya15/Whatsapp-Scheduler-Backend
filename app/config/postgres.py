"""Async PostgreSQL engine and session management."""

from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config.setting import settings
from app.model.base import Base


class DatabaseManager:
    """Singleton that owns the SQLAlchemy async engine and session factory."""

    _instance: Optional["DatabaseManager"] = None

    def __init__(self) -> None:
        self._engine = create_async_engine(settings.DB_URL, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    @classmethod
    def get_instance(cls) -> "DatabaseManager":
        """Return the process-wide singleton, creating it on the first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def engine(self):
        return self._engine

    @property
    def async_session_local(self):
        return self._session_factory

    async def init_db(self) -> None:
        """Create all ORM-mapped tables and apply safe column migrations."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Idempotent: add wa_linked column if it does not yet exist (for existing DBs)
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS wa_linked BOOLEAN NOT NULL DEFAULT FALSE;"
            ))


async def init_db() -> None:
    """Module-level helper — delegates to the singleton."""
    await DatabaseManager.get_instance().init_db()
