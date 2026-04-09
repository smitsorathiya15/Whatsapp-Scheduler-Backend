"""Validation guards for the templates router."""

import uuid

from fastapi import HTTPException, status

from app.model.message_template import MessageTemplate


class TemplateValidator:
    """Static validation rules applied to template data before database writes."""

    @staticmethod
    def template_exists(template: MessageTemplate | None, template_id: uuid.UUID | None = None) -> MessageTemplate:
        if template is None:
            detail = f"Template '{template_id}' not found." if template_id else "Template not found."
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_key": "not_found_error", "reason": detail},
            )
        return template
