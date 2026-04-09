"""Database access helpers for the schedules router."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.schedule import Schedule


class ScheduleAccess:
    """Encapsulates all database operations for the Schedule model."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self, user_id: uuid.UUID) -> list[Schedule]:
        try:
            result = await self._db.execute(
                select(Schedule).where(Schedule.user_id == user_id).order_by(Schedule.created_at)
            )
            return list(result.scalars().all())
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch schedules: {exc}") from exc

    async def get_by_id(self, schedule_id: uuid.UUID, user_id: uuid.UUID) -> Schedule | None:
        try:
            result = await self._db.execute(
                select(Schedule).where(Schedule.id == schedule_id, Schedule.user_id == user_id)
            )
            return result.scalar_one_or_none()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch schedule '{schedule_id}': {exc}") from exc

    async def create(self, data: dict) -> Schedule:
        try:
            schedule = Schedule(**data)
            self._db.add(schedule)
            await self._db.flush()
            return schedule
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to create schedule: {exc}") from exc

    async def update(self, schedule: Schedule, data: dict) -> Schedule:
        try:
            for key, value in data.items():
                if value is not None:
                    setattr(schedule, key, value)
            await self._db.flush()
            return schedule
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to update schedule: {exc}") from exc

    async def delete(self, schedule: Schedule) -> None:
        try:
            await self._db.delete(schedule)
            await self._db.flush()
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to delete schedule: {exc}") from exc
