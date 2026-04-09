"""Schedule CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DatabaseDependency
from app.model.user import User
from app.router.user.schedules.schedule_access import ScheduleAccess
from app.router.user.schedules.schedule_validator import ScheduleValidator
from app.router.user.templates.template_access import TemplateAccess
from app.schemas.response import ApiResponse
from app.schemas.schedule import ScheduleCreate, ScheduleRead, ScheduleUpdate
from app.services.jwt.auth import AuthService
from app.utils.helper import ResponseHelper

_auth = [Depends(AuthService.get_current_user)]


class ScheduleRouter:
    """Registers and handles all /user/v1/schedules routes."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/user/v1/schedules", tags=["User — Schedules"], dependencies=_auth)
        self._register()

    def _register(self) -> None:
        self.router.add_api_route("", self.list_schedules, methods=["GET"], response_model=ApiResponse)
        self.router.add_api_route("", self.create_schedule, methods=["POST"], response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
        self.router.add_api_route("/{schedule_id}", self.get_schedule, methods=["GET"], response_model=ApiResponse)
        self.router.add_api_route("/{schedule_id}", self.update_schedule, methods=["PUT"], response_model=ApiResponse)
        self.router.add_api_route("/{schedule_id}", self.delete_schedule, methods=["DELETE"], response_model=ApiResponse)

    async def list_schedules(self, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            schedules = await ScheduleAccess(db).get_all(current_user.id)
            return ResponseHelper.success([ScheduleRead.model_validate(s).model_dump() for s in schedules], key="schedule_list_success")
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def create_schedule(self, payload: ScheduleCreate, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            template = await TemplateAccess(db).get_by_id(payload.message_template_id, current_user.id)
            ScheduleValidator.validate_template_ownership(template, payload.message_template_id)
            data = payload.model_dump()
            data["user_id"] = current_user.id
            schedule = await ScheduleAccess(db).create(data)
            await db.commit()
            await db.refresh(schedule)
            return ResponseHelper.success(ScheduleRead.model_validate(schedule).model_dump(), key="schedule_create_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def get_schedule(self, schedule_id: uuid.UUID, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            schedule = await ScheduleAccess(db).get_by_id(schedule_id, current_user.id)
            ScheduleValidator.schedule_exists(schedule, schedule_id)
            return ResponseHelper.success(ScheduleRead.model_validate(schedule).model_dump(), key="schedule_retrieve_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def update_schedule(self, schedule_id: uuid.UUID, payload: ScheduleUpdate, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = ScheduleAccess(db)
            schedule = ScheduleValidator.schedule_exists(await access.get_by_id(schedule_id, current_user.id), schedule_id)
            update_data = payload.model_dump(exclude_unset=True)
            if "message_template_id" in update_data:
                template = await TemplateAccess(db).get_by_id(update_data["message_template_id"], current_user.id)
                ScheduleValidator.validate_template_ownership(template, update_data["message_template_id"])
            schedule = await access.update(schedule, update_data)
            await db.commit()
            await db.refresh(schedule)
            return ResponseHelper.success(ScheduleRead.model_validate(schedule).model_dump(), key="schedule_update_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def delete_schedule(self, schedule_id: uuid.UUID, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = ScheduleAccess(db)
            schedule = ScheduleValidator.schedule_exists(await access.get_by_id(schedule_id, current_user.id), schedule_id)
            await access.delete(schedule)
            await db.commit()
            return ResponseHelper.success(key="schedule_delete_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


router = ScheduleRouter().router
