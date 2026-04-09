"""JWT token creation."""

from datetime import datetime, timedelta, timezone
from typing import Any

from jose import jwt

from app.config.setting import settings


class TokenService:
    """Handles JWT access token creation."""

    @staticmethod
    def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
        """Create and return a signed JWT access token."""
        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (
            expires_delta or timedelta(minutes=settings.JWT_EXPIRES_MINUTES)
        )
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
