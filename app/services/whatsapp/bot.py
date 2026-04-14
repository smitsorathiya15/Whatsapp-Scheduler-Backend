"""
WhatsApp automation — thin HTTP client that talks to the Node.js
whatsapp-web.js sidecar running on localhost:3001.

Replaces the old Selenium/Chrome-based driver entirely.
The public API of WhatsAppBot and _UserSession is kept identical
so that the router and scheduler need zero changes.
"""

import asyncio
import logging
import os
import threading
import uuid
from typing import Optional

import httpx

from app.config.setting import settings

logger = logging.getLogger(__name__)

# Base URL of the Node sidecar
WA_SERVICE_URL = os.getenv("WA_SERVICE_URL", "http://localhost:3001")

# Shared async client — reused across the lifetime of the app
_http: Optional[httpx.AsyncClient] = None


def _client() -> httpx.AsyncClient:
    """Lazy-init a module-level async httpx client."""
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(base_url=WA_SERVICE_URL, timeout=120.0)
    return _http


# ── Per-user session wrapper ─────────────────────────────────────────────────

class _UserSession:
    """Tracks one user's WhatsApp session state and delegates to the Node sidecar."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.is_logged_in = False
        self.is_started = False
        self.last_error: Optional[str] = None
        self._init_lock = asyncio.Lock()

    async def ensure_started(self) -> None:
        """Tell the sidecar to initialise a wwebjs Client for this user."""
        async with self._init_lock:
            if self.is_started:
                # Refresh status from sidecar
                await self._refresh_status()
                return
            try:
                resp = await _client().post(
                    "/session/init",
                    json={"userId": str(self.user_id)},
                )
                data = resp.json()
                self.is_started = True
                self.is_logged_in = data.get("ready", False)
                self.last_error = data.get("error")
                if self.is_logged_in:
                    logger.info("WhatsApp session restored for user %s", self.user_id)
                else:
                    logger.info("WhatsApp session initialising for user %s (QR pending)", self.user_id)
            except Exception as exc:
                self.last_error = f"Sidecar connection error: {exc}"
                logger.error("Failed to init session for user %s: %s", self.user_id, exc)

    async def _refresh_status(self) -> None:
        """Poll the sidecar for current session status."""
        try:
            resp = await _client().get(f"/session/{self.user_id}/status")
            data = resp.json()
            self.is_logged_in = data.get("ready", False)
            err = data.get("error")
            if err:
                self.last_error = err
        except Exception as exc:
            logger.warning("Status refresh failed for user %s: %s", self.user_id, exc)

    # ── QR ────────────────────────────────────────────────────────────────────

    async def get_qr_base64(self) -> Optional[str]:
        """Return the latest QR code as a base64 PNG string, or None."""
        try:
            resp = await _client().get(f"/session/{self.user_id}/qr")
            data = resp.json()

            # Session may have become ready between calls
            if data.get("ready"):
                self.is_logged_in = True
                return None

            return data.get("qr")
        except Exception as exc:
            logger.warning("QR fetch error for user %s: %s", self.user_id, exc)
            return None

    async def wait_for_scan(self, timeout: int = 120) -> bool:
        """Poll the sidecar until the user scans the QR (up to timeout seconds)."""
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                resp = await _client().get(f"/session/{self.user_id}/status")
                data = resp.json()
                if data.get("ready"):
                    self.is_logged_in = True
                    self.last_error = None
                    logger.info("QR scanned — user %s linked.", self.user_id)
                    return True
                err = data.get("error")
                if err:
                    self.last_error = err
                    logger.warning("wait_for_scan error for user %s: %s", self.user_id, err)
                    return False
            except Exception as exc:
                logger.warning("wait_for_scan poll error for user %s: %s", self.user_id, exc)
                return False
            await asyncio.sleep(2)
        return False

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, group_name: str, message: str) -> bool:
        """Send a message to a WhatsApp group via the sidecar."""
        if not self.is_logged_in:
            logger.warning("send_message: user %s not logged in.", self.user_id)
            return False
        try:
            resp = await _client().post(
                f"/session/{self.user_id}/send",
                json={"groupName": group_name, "message": message},
            )
            data = resp.json()
            if data.get("success"):
                logger.info("Message sent to '%s' for user %s.", group_name, self.user_id)
                return True
            else:
                logger.error(
                    "send_message failed user=%s group='%s': %s",
                    self.user_id, group_name, data.get("error"),
                )
                return False
        except Exception as exc:
            logger.error("send_message error user=%s group='%s': %s", self.user_id, group_name, exc)
            return False

    # ── Stop ──────────────────────────────────────────────────────────────────

    async def stop(self) -> None:
        """Destroy the sidecar session for this user."""
        async with self._init_lock:
            try:
                await _client().post(f"/session/{self.user_id}/destroy")
            except Exception as exc:
                logger.warning("Destroy error for user %s: %s", self.user_id, exc)
            finally:
                self.is_logged_in = False
                self.is_started = False


# ── Registry (identical public API to the old Selenium version) ──────────────

class WhatsAppBot:
    """Registry of per-user _UserSession instances."""

    _instance: Optional["WhatsAppBot"] = None
    _class_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, _UserSession] = {}
        self._registry_lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "WhatsAppBot":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    async def session_for(self, user_id: uuid.UUID) -> _UserSession:
        async with self._registry_lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = _UserSession(user_id)
        session = self._sessions[user_id]
        await session.ensure_started()
        return session

    async def remove_session(self, user_id: uuid.UUID) -> None:
        async with self._registry_lock:
            session = self._sessions.pop(user_id, None)
        if session:
            await session.stop()
            logger.info("Session removed for user %s.", user_id)

    def get_existing_session(self, user_id: uuid.UUID) -> Optional[_UserSession]:
        return self._sessions.get(user_id)

    def is_linked_for_user(self, user_id: uuid.UUID) -> bool:
        s = self._sessions.get(user_id)
        return s is not None and s.is_logged_in

    async def initialize_for_user(self, user_id: uuid.UUID) -> None:
        await self.session_for(user_id)

    async def get_qr_base64(self, user_id: uuid.UUID) -> Optional[str]:
        s = await self.session_for(user_id)
        return await s.get_qr_base64()

    async def wait_for_scan(self, user_id: uuid.UUID, timeout: int = 120) -> bool:
        s = self._sessions.get(user_id)
        if s is None:
            return False
        return await s.wait_for_scan(timeout)

    async def unlink_user(self, user_id: uuid.UUID) -> None:
        await self.remove_session(user_id)

    async def send_message(self, user_id: uuid.UUID, group_name: str, message: str) -> bool:
        s = self._sessions.get(user_id)
        if s is None or not s.is_logged_in:
            return False
        return await s.send_message(group_name, message)

    def close_all(self) -> None:
        """Synchronous cleanup — best effort destroy all sessions."""
        for session in list(self._sessions.values()):
            try:
                # Fire-and-forget HTTP call
                httpx.post(
                    f"{WA_SERVICE_URL}/session/{session.user_id}/destroy",
                    timeout=5.0,
                )
            except Exception:
                pass
        self._sessions.clear()
        logger.info("All WhatsApp sessions closed.")
