"""Validation guards for the groups router."""

import uuid

from fastapi import HTTPException, status

from app.model.group import Group


class GroupValidator:
    """Static validation rules applied to group data before database writes."""

    @staticmethod
    def group_exists(group: Group | None, group_id: uuid.UUID | None = None) -> Group:
        if group is None:
            detail = f"Group '{group_id}' not found." if group_id else "Group not found."
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_key": "not_found_error", "reason": detail},
            )
        return group
