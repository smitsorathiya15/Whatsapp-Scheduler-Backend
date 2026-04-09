"""Validation guards for the users router."""

import uuid

from fastapi import HTTPException, status

from app.model.user import User


class UserValidator:
    """Static validation rules applied to user data before database writes."""

    @staticmethod
    def validate_unique_username(existing: User | None, username: str) -> None:
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_key": "bad_request_error", "reason": f"Username '{username}' is already taken."},
            )

    @staticmethod
    def validate_unique_email(existing: User | None, email: str) -> None:
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_key": "bad_request_error", "reason": f"Email '{email}' is already registered."},
            )

    @staticmethod
    def user_exists(user: User | None, user_id: uuid.UUID | None = None) -> User:
        if user is None:
            detail = f"User '{user_id}' not found." if user_id else "User not found."
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_key": "not_found_error", "reason": detail},
            )
        return user
