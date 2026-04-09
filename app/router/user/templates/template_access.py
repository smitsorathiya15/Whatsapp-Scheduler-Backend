"""Database access helpers for the templates router."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.model.message_template import MessageTemplate


class TemplateAccess:
    """Encapsulates all database operations for the MessageTemplate model."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_all(self, user_id: uuid.UUID) -> list[MessageTemplate]:
        try:
            result = await self._db.execute(
                select(MessageTemplate).where(MessageTemplate.user_id == user_id).order_by(MessageTemplate.created_at)
            )
            return list(result.scalars().all())
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch templates: {exc}") from exc

    async def get_by_id(self, template_id: uuid.UUID, user_id: uuid.UUID) -> MessageTemplate | None:
        try:
            result = await self._db.execute(
                select(MessageTemplate).where(MessageTemplate.id == template_id, MessageTemplate.user_id == user_id)
            )
            return result.scalar_one_or_none()
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch template '{template_id}': {exc}") from exc

    async def create(self, data: dict) -> MessageTemplate:
        try:
            template = MessageTemplate(**data)
            self._db.add(template)
            await self._db.flush()
            return template
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to create template: {exc}") from exc

    async def update(self, template: MessageTemplate, data: dict) -> MessageTemplate:
        try:
            for key, value in data.items():
                if value is not None:
                    setattr(template, key, value)
            await self._db.flush()
            return template
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to update template: {exc}") from exc

    async def delete(self, template: MessageTemplate) -> None:
        try:
            await self._db.delete(template)
            await self._db.flush()
        except Exception as exc:
            await self._db.rollback()
            raise RuntimeError(f"Failed to delete template: {exc}") from exc
