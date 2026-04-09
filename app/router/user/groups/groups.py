"""Group CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DatabaseDependency
from app.model.user import User
from app.router.user.groups.group_access import GroupAccess
from app.router.user.groups.group_validator import GroupValidator
from app.schemas.group import GroupCreate, GroupRead, GroupUpdate
from app.schemas.response import ApiResponse
from app.services.jwt.auth import AuthService
from app.utils.helper import ResponseHelper

_auth = [Depends(AuthService.get_current_user)]


class GroupRouter:
    """Registers and handles all /user/v1/groups routes."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/user/v1/groups", tags=["User — Groups"], dependencies=_auth)
        self._register()

    def _register(self) -> None:
        self.router.add_api_route("", self.list_groups, methods=["GET"], response_model=ApiResponse)
        self.router.add_api_route("", self.create_group, methods=["POST"], response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
        self.router.add_api_route("/{group_id}", self.get_group, methods=["GET"], response_model=ApiResponse)
        self.router.add_api_route("/{group_id}", self.update_group, methods=["PUT"], response_model=ApiResponse)
        self.router.add_api_route("/{group_id}", self.delete_group, methods=["DELETE"], response_model=ApiResponse)

    async def list_groups(self, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            groups = await GroupAccess(db).get_all_active(current_user.id)
            return ResponseHelper.success([GroupRead.model_validate(g).model_dump() for g in groups], key="group_list_success")
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def create_group(self, payload: GroupCreate, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            data = payload.model_dump()
            data["user_id"] = current_user.id
            group = await GroupAccess(db).create(data)
            await db.commit()
            await db.refresh(group)
            return ResponseHelper.success(GroupRead.model_validate(group).model_dump(), key="group_create_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def get_group(self, group_id: uuid.UUID, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            group = await GroupAccess(db).get_by_id(group_id, current_user.id)
            GroupValidator.group_exists(group, group_id)
            return ResponseHelper.success(GroupRead.model_validate(group).model_dump(), key="group_retrieve_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def update_group(self, group_id: uuid.UUID, payload: GroupUpdate, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = GroupAccess(db)
            group = GroupValidator.group_exists(await access.get_by_id(group_id, current_user.id), group_id)
            group = await access.update(group, payload.model_dump(exclude_unset=True))
            await db.commit()
            await db.refresh(group)
            return ResponseHelper.success(GroupRead.model_validate(group).model_dump(), key="group_update_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def delete_group(self, group_id: uuid.UUID, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = GroupAccess(db)
            group = GroupValidator.group_exists(await access.get_by_id(group_id, current_user.id), group_id)
            await access.soft_delete(group)
            await db.commit()
            return ResponseHelper.success(key="group_delete_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


router = GroupRouter().router
