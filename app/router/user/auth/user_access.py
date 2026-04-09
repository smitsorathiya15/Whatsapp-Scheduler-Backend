"""Database access helpers for the users router."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.user import User


class UserAccess:
    """Encapsulates all database operations for the User model."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        try:
            result = await self._db.execute(select(User).where(User.id == user_id))
            return result.scalar_one_or_none()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch user '{user_id}': {exc}") from exc

    async def get_by_username(self, username: str) -> User | None:
        try:
            result = await self._db.execute(select(User).where(User.username == username))
            return result.scalar_one_or_none()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch user '{username}': {exc}") from exc

    async def get_by_email(self, email: str) -> User | None:
        try:
            result = await self._db.execute(select(User).where(User.email == email))
            return result.scalar_one_or_none()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch user '{email}': {exc}") from exc

    async def create(self, data: dict) -> User:
        try:
            user = User(**data)
            self._db.add(user)
            await self._db.flush()
            return user
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to create user: {exc}") from exc
