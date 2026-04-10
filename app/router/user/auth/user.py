import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

from app.deps import DatabaseDependency
from app.model.user import User
from app.router.user.auth.user_access import UserAccess
from app.router.user.auth.user_validator import UserValidator
from app.schemas.response import ApiResponse
from app.schemas.user import UserCreate, UserLogin, UserRead, UserToken
from app.services.jwt.auth import AuthService
from app.services.jwt.passwords import PasswordManager
from app.services.jwt.token_service import TokenService
from app.utils.helper import ResponseHelper


class UserAuthRouter:
    """Registers and handles all /user/v1/auth routes."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/user/v1/auth", tags=["User — Auth"])
        self._register()

    def _register(self) -> None:
        self.router.add_api_route("/register", self.register, methods=["POST"], response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
        self.router.add_api_route("/login", self.login, methods=["POST"], response_model=ApiResponse)
        self.router.add_api_route("/logout", self.logout, methods=["POST"], response_model=ApiResponse, dependencies=[Depends(AuthService.get_current_user)])
        self.router.add_api_route("/me", self.me, methods=["GET"], response_model=ApiResponse, dependencies=[Depends(AuthService.get_current_user)])

    async def register(self, payload: UserCreate, db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = UserAccess(db)
            UserValidator.validate_unique_username(await access.get_by_username(payload.username), payload.username)
            UserValidator.validate_unique_email(await access.get_by_email(payload.email), payload.email)
            data = payload.model_dump(exclude={"password"})
            data["password_hash"] = PasswordManager.hash(payload.password)
            user = await access.create(data)
            await db.commit()
            await db.refresh(user)
            return ResponseHelper.success(UserRead.model_validate(user).model_dump(), key="user_register_success")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def login(self, credentials: UserLogin, db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = UserAccess(db)
            # Try to find by username first
            user = await access.get_by_username(credentials.username)
            
            # If not found, try by email
            if not user:
                user = await access.get_by_email(credentials.username)

            if not user or not user.is_active:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error_key": "unauthorized_error", "reason": "Invalid username or password."})

            if not PasswordManager.verify(credentials.password, user.password_hash):
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"error_key": "unauthorized_error", "reason": "Invalid username or password."})

            token = TokenService.create_access_token({"sub": str(user.id), "username": user.username, "role": "user"})
            return ResponseHelper.success(UserToken(access_token=token, user=UserRead.model_validate(user)).model_dump(), key="user_login_success")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def logout(self, current_user: User = Depends(AuthService.get_current_user)) -> ApiResponse:
        logger.info("User logged out: %s", current_user.username)
        return ResponseHelper.success(
            {"logged_out": True, "username": current_user.username},
            key="user_logout_success",
        )

    async def me(self, current_user: User = Depends(AuthService.get_current_user)) -> ApiResponse:
        return ResponseHelper.success(UserRead.model_validate(current_user).model_dump(), key="user_profile_success")


router = UserAuthRouter().router
