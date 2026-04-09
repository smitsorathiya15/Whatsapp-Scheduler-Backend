"""Database access helpers for the groups router."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.group import Group


class GroupAccess:
    """Encapsulates all database operations for the Group model."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all_active(self, user_id: uuid.UUID) -> list[Group]:
        try:
            result = await self._db.execute(
                select(Group).where(Group.user_id == user_id, Group.is_active == True).order_by(Group.created_at)  # noqa: E712
            )
            return list(result.scalars().all())
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch groups: {exc}") from exc

    async def get_by_id(self, group_id: uuid.UUID, user_id: uuid.UUID) -> Group | None:
        try:
            result = await self._db.execute(
                select(Group).where(Group.id == group_id, Group.user_id == user_id)
            )
            return result.scalar_one_or_none()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch group '{group_id}': {exc}") from exc

    async def create(self, data: dict) -> Group:
        try:
            group = Group(**data)
            self._db.add(group)
            await self._db.flush()
            return group
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to create group: {exc}") from exc

    async def update(self, group: Group, data: dict) -> Group:
        try:
            for key, value in data.items():
                if value is not None:
                    setattr(group, key, value)
            await self._db.flush()
            return group
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to update group: {exc}") from exc

    async def soft_delete(self, group: Group) -> None:
        try:
            group.is_active = False
            await self._db.flush()
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to delete group: {exc}") from exc
