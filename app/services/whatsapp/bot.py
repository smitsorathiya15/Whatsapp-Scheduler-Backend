"""WhatsApp Web automation — one Chrome instance per user, managed by a registry."""

import asyncio
import base64
import logging
import os
import shutil
import threading
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Optional

from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from app.config.setting import settings

logger = logging.getLogger(__name__)


# ── Per-user driver wrapper ────────────────────────────────────────────────────

class _UserSession:
    """
    One Chrome instance dedicated to a single user.
    Holds the driver, login state, and a send lock for that user only.
    """

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id      = user_id
        self.is_logged_in = False
        self._driver: Optional[webdriver.Chrome] = None
        self._send_lock   = threading.Lock()
        self._init_lock   = asyncio.Lock()

    # ── Profile ───────────────────────────────────────────────────────────────

    @property
    def _profile_path(self) -> Path:
        return Path(settings.WA_PROFILE_DIR).resolve() / str(self.user_id)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def ensure_started(self) -> None:
        """Start Chrome for this user if not already running."""
        async with self._init_lock:
            if self._driver is not None:
                return
            await asyncio.to_thread(self._start)

    def _start(self) -> None:
        profile = self._profile_path
        profile.mkdir(parents=True, exist_ok=True)

        for name in ["SingletonLock", "DevToolsActivePort", "lock"]:
            p = profile / name
            if p.exists():
                try:
                    shutil.rmtree(p) if p.is_dir() else os.remove(p)
                except Exception as exc:
                    logger.warning("Could not remove lock file %s: %s", name, exc)

        try:
            options = Options()
            options.add_argument(f"--user-data-dir={profile}")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument(
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            if settings.WA_HEADLESS:
                options.add_argument("--headless")
                options.add_argument("--window-size=1280,900")

            service = Service(ChromeDriverManager().install())
            self._driver = webdriver.Chrome(service=service, options=options)

            handles = self._driver.window_handles
            if len(handles) > 1:
                self._driver.switch_to.window(handles[-1])

            self._driver.get("https://web.whatsapp.com")
            logger.info("Chrome started for user %s — waiting 30s.", self.user_id)
            time.sleep(30)
            self._detect()
        except Exception as exc:
            logger.error("Chrome start failed for user %s: %s", self.user_id, exc, exc_info=True)
            self._driver = None
            self.is_logged_in = False

    def _detect(self) -> None:
        if self._driver is None:
            return
        try:
            WebDriverWait(self._driver, 20).until(
                lambda d: (
                    d.find_elements(By.CSS_SELECTOR, 'div[data-testid="chat-list"]') or
                    d.find_elements(By.CSS_SELECTOR, 'input[data-tab="3"]') or
                    d.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="3"]') or
                    d.find_elements(By.CSS_SELECTOR, 'div#pane-side') or
                    d.find_elements(By.CSS_SELECTOR, 'canvas')
                )
            )
            self.is_logged_in = bool(
                self._driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="chat-list"]') or
                self._driver.find_elements(By.CSS_SELECTOR, 'input[data-tab="3"]') or
                self._driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="3"]') or
                self._driver.find_elements(By.CSS_SELECTOR, 'div#pane-side')
            )
            if self.is_logged_in:
                logger.info("Session restored for user %s.", self.user_id)
                time.sleep(5)
            else:
                logger.info("QR visible for user %s.", self.user_id)
        except Exception as exc:
            logger.warning("Detect login failed for user %s: %s", self.user_id, exc)
            self.is_logged_in = False
        finally:
            try:
                self._driver.switch_to.default_content()
            except Exception:
                pass

    async def stop(self) -> None:
        async with self._init_lock:
            await asyncio.to_thread(self._quit)
            self.is_logged_in = False

    def _quit(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception as exc:
                logger.warning("Quit error for user %s: %s", self.user_id, exc)
            finally:
                self._driver = None

    # ── QR ────────────────────────────────────────────────────────────────────

    async def get_qr_base64(self) -> Optional[str]:
        if self._driver is None:
            return None
        try:
            def _cap():
                for sel in [
                    'canvas[aria-label="Scan this QR code to link a device"]',
                    '.landing-main canvas',
                    'canvas',
                ]:
                    for el in self._driver.find_elements(By.CSS_SELECTOR, sel):
                        if el.size.get("width", 0) > 100 and el.size.get("height", 0) > 100:
                            return el.screenshot_as_png
                dbg = Path("debug_screenshot.png").resolve()
                self._driver.save_screenshot(str(dbg))
                logger.info("QR not found for user %s. Screenshot: %s", self.user_id, dbg)
                return None

            png = await asyncio.to_thread(_cap)
            if png is None:
                await asyncio.to_thread(self._detect)
                return None
            img = Image.open(BytesIO(png))
            buf = BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as exc:
            logger.warning("QR capture error for user %s: %s", self.user_id, exc)
            await asyncio.to_thread(self._detect)
            return None

    async def wait_for_scan(self, timeout: int = 120) -> bool:
        if self._driver is None:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            def _check():
                return bool(
                    self._driver.find_elements(By.CSS_SELECTOR, 'div[data-testid="chat-list"]') or
                    self._driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"][data-tab="3"]') or
                    self._driver.find_elements(By.CSS_SELECTOR, 'div#pane-side')
                )
            if await asyncio.to_thread(_check):
                self.is_logged_in = True
                logger.info("QR scanned — user %s linked.", self.user_id)
                return True
            await asyncio.sleep(3)
        return False

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_message(self, group_name: str, message: str) -> bool:
        if not self.is_logged_in or self._driver is None:
            logger.warning("send_message: user %s not logged in.", self.user_id)
            return False
        return await asyncio.to_thread(self._sync_send, group_name, message)

    def _sync_send(self, group_name: str, message: str) -> bool:
        with self._send_lock:
            try:
                handles = self._driver.window_handles
                if len(handles) > 1:
                    self._driver.switch_to.window(handles[-1])

                try:
                    self._driver.execute_script(
                        "document.querySelectorAll('span[data-testid=\"x-alt\"]').forEach("
                        "b => { const c = b.closest('[role=\"alert\"]') || b.parentElement.parentElement;"
                        " if (c) c.remove(); });"
                    )
                except Exception:
                    pass
                time.sleep(1)

                search = None
                for sel in [
                    'input[data-tab="3"]',
                    'input[role="textbox"][type="text"]',
                    'div[contenteditable="true"][data-tab="3"]',
                    'div[data-testid="search-input"]',
                ]:
                    els = self._driver.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        search = els[0]
                        break

                if not search:
                    raise Exception("Search box not found.")

                search.click()
                time.sleep(0.5)
                search.clear()
                search.send_keys(group_name)
                time.sleep(4)

                matched = False
                for item in self._driver.find_elements(By.CSS_SELECTOR, 'span[title]'):
                    try:
                        if item.text.strip() == group_name:
                            item.click()
                            matched = True
                            break
                    except Exception:
                        continue

                if not matched:
                    for item in self._driver.find_elements(By.CSS_SELECTOR, 'span[title]'):
                        try:
                            if group_name.lower() in item.text.lower():
                                item.click()
                                matched = True
                                break
                        except Exception:
                            continue

                if not matched:
                    raise Exception(f"Group '{group_name}' not found.")

                time.sleep(2)

                msg_box = None
                for sel in [
                    'div[contenteditable="true"][data-tab="10"]',
                    'div[data-testid="conversation-compose-box-input"]',
                    'footer div[contenteditable="true"]',
                ]:
                    els = self._driver.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        msg_box = els[0]
                        break

                if not msg_box:
                    all_edit = self._driver.find_elements(
                        By.CSS_SELECTOR, 'div[contenteditable="true"]'
                    )
                    msg_box = all_edit[-1] if all_edit else None

                if not msg_box:
                    raise Exception("Message box not found.")

                msg_box.click()
                for line in message.split("\n"):
                    msg_box.send_keys(line)
                    msg_box.send_keys(Keys.SHIFT + Keys.ENTER)
                time.sleep(0.5)
                msg_box.send_keys(Keys.ENTER)
                time.sleep(1)
                logger.info("Message sent to '%s' for user %s.", group_name, self.user_id)
                return True
            except Exception as exc:
                try:
                    self._driver.save_screenshot(
                        str(Path(f"send_fail_{self.user_id}.png").resolve())
                    )
                except Exception:
                    pass
                logger.error("send_message error for user %s / group '%s': %s", self.user_id, group_name, exc)
                return False
            finally:
                try:
                    self._driver.switch_to.default_content()
                except Exception:
                    pass


# ── Registry ───────────────────────────────────────────────────────────────────

class WhatsAppBot:
    """
    Process-wide registry of per-user _UserSession instances.

    Each user gets their own dedicated Chrome instance that stays alive
    independently — users never share a browser, sessions never clash,
    and the scheduler can send for multiple users concurrently.

    Usage:
        session = await WhatsAppBot.get_instance().session_for(user_id)
        await session.send_message(group, text)
    """

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
        """Return the live session for this user, creating and starting it if needed."""
        async with self._registry_lock:
            if user_id not in self._sessions:
                self._sessions[user_id] = _UserSession(user_id)
        session = self._sessions[user_id]
        await session.ensure_started()
        return session

    async def remove_session(self, user_id: uuid.UUID) -> None:
        """Stop and remove the session for this user (called on unlink)."""
        async with self._registry_lock:
            session = self._sessions.pop(user_id, None)
        if session:
            await session.stop()
            logger.info("Session removed for user %s.", user_id)

    def get_existing_session(self, user_id: uuid.UUID) -> Optional[_UserSession]:
        """Return an existing session without creating one (non-blocking)."""
        return self._sessions.get(user_id)

    # ── Convenience passthrough (keeps old call-sites working) ────────────────

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
        for s in list(self._sessions.values()):
            s._quit()
        self._sessions.clear()
