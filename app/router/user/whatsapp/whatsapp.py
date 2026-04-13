"""WhatsApp session endpoints — status, QR code, wait-for-scan, unlink."""

import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import DatabaseDependency
from app.model.user import User
from app.schemas.response import ApiResponse
from app.services.jwt.auth import AuthService
from app.services.whatsapp.bot import WhatsAppBot
from app.utils.helper import ResponseHelper

IS_SERVERLESS = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))

_auth = [Depends(AuthService.get_current_user)]


class WhatsAppRouter:
    """Registers and handles all /user/v1/whatsapp routes."""

    def __init__(self) -> None:
        self.router = APIRouter(
            prefix="/user/v1/whatsapp",
            tags=["User — WhatsApp"],
            dependencies=_auth,
        )
        self._register()

    def _register(self) -> None:
        self.router.add_api_route("/status",    self.status,    methods=["GET"],  response_model=ApiResponse)
        self.router.add_api_route("/qr",        self.qr,        methods=["GET"],  response_model=ApiResponse)
        self.router.add_api_route("/wait-scan", self.wait_scan, methods=["POST"], response_model=ApiResponse)
        self.router.add_api_route("/unlink",    self.unlink,    methods=["POST"], response_model=ApiResponse)

    @staticmethod
    def _serverless_guard() -> None:
        """Raise 503 if running in serverless (Vercel) — WhatsApp needs persistent Chrome."""
        if IS_SERVERLESS:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error_key": "service_unavailable",
                    "reason": "WhatsApp features are not available in serverless mode. "
                              "Deploy on Railway, Render, or a VPS for full functionality.",
                },
            )

    # ── Status ─────────────────────────────────────────────────────────────────

    async def status(
        self,
        current_user: User = Depends(AuthService.get_current_user),
    ) -> ApiResponse:
        """
        Return the live WhatsApp session state for this user only.
        Uses the in-memory session registry — does NOT start Chrome.
        """
        self._serverless_guard()
        bot     = WhatsAppBot.get_instance()
        session = bot.get_existing_session(current_user.id)
        linked  = session is not None and session.is_logged_in
        return ResponseHelper.success({"linked": linked}, key="whatsapp_status_success")

    # ── QR ─────────────────────────────────────────────────────────────────────

    async def qr(
        self,
        current_user: User = Depends(AuthService.get_current_user),
        db: AsyncSession = Depends(DatabaseDependency.get_db),
    ) -> ApiResponse:
        """
        Ensure a Chrome session exists for this user and return the QR code.
        If the saved profile is still logged in, returns linked=True immediately.
        """
        self._serverless_guard()
        bot     = WhatsAppBot.get_instance()
        session = await bot.session_for(current_user.id)   # starts Chrome if needed

        if session.is_logged_in:
            await self._persist_linked(db, current_user, True)
            return ResponseHelper.success({"linked": True, "qr": None}, key="whatsapp_already_linked")

        if session._driver is None and session.last_error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error_key": "bad_request_error", "reason": session.last_error},
            )

        qr_b64 = await session.get_qr_base64()
        if qr_b64 is None:
            return ResponseHelper.success(
                {"linked": False, "qr": None, "info": "Generating QR… refresh in a moment."},
                key="whatsapp_status_success",
            )
        return ResponseHelper.success({"linked": False, "qr": qr_b64}, key="whatsapp_qr_success")

    # ── Wait-scan ──────────────────────────────────────────────────────────────

    async def wait_scan(
        self,
        current_user: User = Depends(AuthService.get_current_user),
        db: AsyncSession = Depends(DatabaseDependency.get_db),
    ) -> ApiResponse:
        """Long-poll until the user scans the QR (up to 120 s)."""
        self._serverless_guard()
        bot     = WhatsAppBot.get_instance()
        session = bot.get_existing_session(current_user.id)

        if session is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error_key": "bad_request_error", "reason": "Fetch the QR first before waiting for scan."},
            )

        if session.is_logged_in:
            return ResponseHelper.success({"linked": True}, key="whatsapp_already_linked")

        success = await session.wait_for_scan(timeout=120)
        if success:
            await self._persist_linked(db, current_user, True)
            return ResponseHelper.success({"linked": True}, key="whatsapp_linked_success")

        if session.last_error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"error_key": "bad_request_error", "reason": session.last_error},
            )

        raise HTTPException(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            detail={"error_key": "bad_request_error", "reason": "QR scan timed out. Refresh and try again."},
        )

    # ── Unlink ─────────────────────────────────────────────────────────────────

    async def unlink(
        self,
        current_user: User = Depends(AuthService.get_current_user),
        db: AsyncSession = Depends(DatabaseDependency.get_db),
    ) -> ApiResponse:
        """Close this user's Chrome session and mark them as unlinked in the DB."""
        self._serverless_guard()
        bot = WhatsAppBot.get_instance()
        await bot.remove_session(current_user.id)
        await self._persist_linked(db, current_user, False)
        return ResponseHelper.success({"linked": False}, key="whatsapp_unlink_success")

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    async def _persist_linked(db: AsyncSession, user: User, linked: bool) -> None:
        try:
            user.wa_linked = linked
            await db.commit()
        except Exception as exc:
            await db.rollback()
            raise RuntimeError(f"Failed to update wa_linked for user {user.id}: {exc}") from exc


router = WhatsAppRouter().router
