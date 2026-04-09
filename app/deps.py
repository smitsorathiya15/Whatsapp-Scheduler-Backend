"""Shared FastAPI dependency providers."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.config.postgres import DatabaseManager


class DatabaseDependency:
    """Provides an async database session for FastAPI dependency injection."""

    @staticmethod
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        """Yield an async session and ensure it is closed after the request."""
        db_manager = DatabaseManager.get_instance()
        async with db_manager.async_session_local() as session:
            try:
                yield session
            finally:
                await session.close()
