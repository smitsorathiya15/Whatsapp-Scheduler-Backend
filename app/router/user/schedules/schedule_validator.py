"""Validation guards for the schedules router."""

import uuid

from fastapi import HTTPException, status

from app.model.schedule import Schedule


class ScheduleValidator:
    """Static validation rules applied to schedule data before database writes."""

    @staticmethod
    def schedule_exists(schedule: Schedule | None, schedule_id: uuid.UUID | None = None) -> Schedule:
        if schedule is None:
            detail = f"Schedule '{schedule_id}' not found." if schedule_id else "Schedule not found."
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_key": "not_found_error", "reason": detail},
            )
        return schedule

    @staticmethod
    def validate_template_ownership(template: object | None, template_id: uuid.UUID) -> None:
        if template is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_key": "not_found_error", "reason": f"Template '{template_id}' not found or does not belong to you."},
            )
