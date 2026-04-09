"""Message template CRUD endpoints."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DatabaseDependency
from app.model.user import User
from app.router.user.templates.template_access import TemplateAccess
from app.router.user.templates.template_validator import TemplateValidator
from app.schemas.response import ApiResponse
from app.schemas.template import TemplateCreate, TemplateRead, TemplateUpdate
from app.services.jwt.auth import AuthService
from app.utils.helper import ResponseHelper

_auth = [Depends(AuthService.get_current_user)]


class TemplateRouter:
    """Registers and handles all /user/v1/templates routes."""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/user/v1/templates", tags=["User — Templates"], dependencies=_auth)
        self._register()

    def _register(self) -> None:
        self.router.add_api_route("", self.list_templates, methods=["GET"], response_model=ApiResponse)
        self.router.add_api_route("", self.create_template, methods=["POST"], response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
        self.router.add_api_route("/{template_id}", self.get_template, methods=["GET"], response_model=ApiResponse)
        self.router.add_api_route("/{template_id}", self.update_template, methods=["PUT"], response_model=ApiResponse)
        self.router.add_api_route("/{template_id}", self.delete_template, methods=["DELETE"], response_model=ApiResponse)

    async def list_templates(self, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            templates = await TemplateAccess(db).get_all(current_user.id)
            return ResponseHelper.success([TemplateRead.model_validate(t).model_dump() for t in templates], key="template_list_success")
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def create_template(self, payload: TemplateCreate, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            data = payload.model_dump()
            data["user_id"] = current_user.id
            template = await TemplateAccess(db).create(data)
            await db.commit()
            await db.refresh(template)
            return ResponseHelper.success(TemplateRead.model_validate(template).model_dump(), key="template_create_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def get_template(self, template_id: uuid.UUID, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            template = await TemplateAccess(db).get_by_id(template_id, current_user.id)
            TemplateValidator.template_exists(template, template_id)
            return ResponseHelper.success(TemplateRead.model_validate(template).model_dump(), key="template_retrieve_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def update_template(self, template_id: uuid.UUID, payload: TemplateUpdate, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = TemplateAccess(db)
            template = TemplateValidator.template_exists(await access.get_by_id(template_id, current_user.id), template_id)
            template = await access.update(template, payload.model_dump(exclude_unset=True))
            await db.commit()
            await db.refresh(template)
            return ResponseHelper.success(TemplateRead.model_validate(template).model_dump(), key="template_update_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    async def delete_template(self, template_id: uuid.UUID, current_user: User = Depends(AuthService.get_current_user), db: AsyncSession = Depends(DatabaseDependency.get_db)) -> ApiResponse:
        try:
            access = TemplateAccess(db)
            template = TemplateValidator.template_exists(await access.get_by_id(template_id, current_user.id), template_id)
            await access.delete(template)
            await db.commit()
            return ResponseHelper.success(key="template_delete_success")
        except HTTPException:
            raise
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


router = TemplateRouter().router
