"""FastAPI dependencies for JWT-protected routes."""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.setting import settings
from app.deps import DatabaseDependency
from app.model.user import User
from app.router.user.auth.user_access import UserAccess

_bearer = HTTPBearer()


class AuthService:
    """Provides FastAPI dependency callables for JWT authentication."""

    @staticmethod
    async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(_bearer),
        db: AsyncSession = Depends(DatabaseDependency.get_db),
    ) -> User:
        """Decode the bearer token and return the authenticated user or raise 401."""
        exc = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error_key": "unauthorized_error", "reason": "Invalid or expired token."},
            headers={"WWW-Authenticate": "Bearer"},
        )
        try:
            payload = jwt.decode(
                credentials.credentials,
                settings.JWT_SECRET,
                algorithms=[settings.JWT_ALGORITHM],
            )
            subject: str | None = payload.get("sub")
            role: str | None = payload.get("role")
            if not subject or role != "user":
                raise exc
            user_id = uuid.UUID(subject)
        except (JWTError, ValueError):
            raise exc

        user = await UserAccess(db).get_by_id(user_id)
        if not user or not user.is_active:
            raise exc
        return user
