"""
WhatsApp Web automation — one Chrome instance per user, managed by a registry.
"""

import asyncio
import base64
import logging
import os
import shutil
import subprocess
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


def _find_chrome_binary() -> Optional[str]:
    """Locate the Chrome/Chromium binary."""
    candidates = [
        os.getenv("WA_CHROME_BINARY", ""),
        os.getenv("CHROME_BIN", ""),
        getattr(settings, "WA_CHROME_BINARY", None) or "",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/snap/bin/chromium",
    ]
    for path in candidates:
        if path and Path(path).exists():
            logger.info("Found Chrome binary at: %s", path)
            return path
    logger.warning("No Chrome binary found.")
    return None


def _find_chromedriver() -> Optional[str]:
    """Find system chromedriver (pre-installed in Docker image)."""
    # Check env override first
    env_path = os.getenv("CHROMEDRIVER_PATH", "")
    if env_path and Path(env_path).exists():
        logger.info("Found chromedriver via env at: %s", env_path)
        return env_path
    path = shutil.which("chromedriver")
    if path:
        logger.info("Found chromedriver at: %s", path)
    return path


# ── Per-user driver wrapper ────────────────────────────────────────────────────

class _UserSession:
    """One Chrome instance dedicated to a single user."""

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id      = user_id
        self.is_logged_in = False
        self.last_error: Optional[str] = None
        self._driver: Optional[webdriver.Chrome] = None
        self._send_lock = threading.Lock()
        self._init_lock = asyncio.Lock()

    @property
    def _profile_path(self) -> Path:
        return Path(settings.WA_PROFILE_DIR).resolve() / str(self.user_id)

    _LOGGED_IN = [
        'div[data-testid="chat-list"]',
        'div#pane-side',
        'div[contenteditable="true"][data-tab="3"]',
        'input[data-tab="3"]',
        '[data-testid="intro-text"]',
    ]

    _QR = [
        'canvas[aria-label="Scan me!"]',
        'canvas[aria-label="Scan this QR code to link a device"]',
        'div[data-testid="qrcode"] canvas',
        'div[data-ref] canvas',
        '.landing-main canvas',
        'canvas',
    ]

    def _has_any(self, selectors: list, min_size: int = 0) -> bool:
        if self._driver is None:
            return False
        for sel in selectors:
            try:
                for el in self._driver.find_elements(By.CSS_SELECTOR, sel):
                    if min_size <= 0:
                        return True
                    if el.size.get("width", 0) >= min_size and el.size.get("height", 0) >= min_size:
                        return True
            except Exception:
                continue
        return False

    async def ensure_started(self) -> None:
        async with self._init_lock:
            if self._driver is not None:
                return
            await asyncio.to_thread(self._start)

    def _clear_locks(self, profile: Path) -> None:
        for name in ["SingletonLock", "DevToolsActivePort", "lock"]:
            p = profile / name
            if not p.exists():
                continue
            for _ in range(5):
                try:
                    shutil.rmtree(p) if p.is_dir() else os.remove(p)
                    break
                except Exception:
                    time.sleep(0.2)

    def _kill_stale_chrome(self, profile: Path) -> None:
        # Linux
        try:
            subprocess.run(["pkill", "-f", f"user-data-dir={profile}"],
                           capture_output=True, timeout=5)
        except Exception:
            pass
        # Windows (local dev)
        try:
            result = subprocess.run(
                ["wmic", "process", "where", "name='chrome.exe'",
                 "get", "ProcessId,CommandLine"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if str(profile).lower() in line.lower():
                    for part in line.strip().split():
                        if part.isdigit():
                            try:
                                subprocess.run(["taskkill", "/F", "/PID", part],
                                               capture_output=True, timeout=5)
                            except Exception:
                                pass
        except Exception:
            pass

    def _build_options(self, profile: Path) -> Options:
        """
        Chrome options for Debian Chromium inside a Docker container.

        Key decisions:
        - --headless (legacy flag, NOT --headless=new) — more stable on Debian chromium
        - --single-process + --no-zygote — avoid renderer/zygote crashes in containers
        - --disable-dev-shm-usage — /dev/shm is too small in containers (64 MB)
        - --no-sandbox + --disable-setuid-sandbox — required without root namespace
        - profile under /tmp — /app is read-only at runtime on Railway
        """
        options = Options()

        options.add_argument(f"--user-data-dir={profile}")

        # Required in containers — no user namespace / setuid
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-setuid-sandbox")

        # Shared memory — redirect to /tmp because /dev/shm is tiny
        options.add_argument("--disable-dev-shm-usage")

        # Process model — avoids zygote/renderer crash in constrained containers
        options.add_argument("--single-process")
        options.add_argument("--no-zygote")

        # No GPU in containers
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-gpu-sandbox")

        # General stability
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-sync")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--mute-audio")
        options.add_argument("--password-store=basic")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--safebrowsing-disable-auto-update")
        options.add_argument("--ignore-certificate-errors")
        options.add_argument("--ignore-ssl-errors")

        # Anti-detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Headless — use LEGACY --headless flag, NOT --headless=new
        # Debian chromium package has stability issues with --headless=new in containers
        if getattr(settings, "WA_HEADLESS", True):
            options.add_argument("--headless")          # legacy headless — stable on Debian
            options.add_argument("--window-size=1280,900")
            options.add_argument("--hide-scrollbars")

        options.page_load_strategy = "eager"

        binary = _find_chrome_binary()
        if binary:
            options.binary_location = binary

        return options

    def _start(self) -> None:
        chrome_binary = _find_chrome_binary()
        if not chrome_binary:
            self.last_error = "Chrome/Chromium not installed on server."
            logger.error("No Chrome binary for user %s.", self.user_id)
            return

        profile = self._profile_path
        profile.mkdir(parents=True, exist_ok=True)

        self._kill_stale_chrome(profile)
        time.sleep(1)
        self._clear_locks(profile)

        chromedriver = _find_chromedriver()
        max_attempts = 3
        last_exc: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                options  = self._build_options(profile)
                log_path = f"/tmp/chromedriver_{self.user_id}.log"

                if chromedriver:
                    service = Service(chromedriver, log_path=log_path)
                else:
                    service = Service(ChromeDriverManager().install(), log_path=log_path)

                logger.info(
                    "Chrome start attempt %d/%d | user=%s | binary=%s | driver=%s | profile=%s",
                    attempt, max_attempts, self.user_id,
                    chrome_binary, chromedriver or "webdriver-manager", profile,
                )

                self._driver = webdriver.Chrome(service=service, options=options)
                self.last_error = None

                handles = self._driver.window_handles
                if len(handles) > 1:
                    self._driver.switch_to.window(handles[-1])

                self._driver.get("https://web.whatsapp.com")
                logger.info("WhatsApp Web loading for user %s — waiting up to 75s.", self.user_id)

                WebDriverWait(self._driver, 75).until(
                    lambda d: self._has_any(self._LOGGED_IN) or
                              self._has_any(self._QR, min_size=100)
                )
                self._detect()
                return  # success

            except Exception as exc:
                last_exc = exc
                self.last_error = str(exc)
                logger.warning(
                    "Chrome start attempt %d/%d failed for user %s: %s",
                    attempt, max_attempts, self.user_id, exc,
                )
                if self._driver:
                    try:
                        self._driver.quit()
                    except Exception:
                        pass
                    self._driver = None
                if attempt < max_attempts:
                    self._kill_stale_chrome(profile)
                    time.sleep(3)
                    self._clear_locks(profile)
                    time.sleep(1)

        logger.error(
            "Chrome start failed for user %s after %d attempts: %s",
            self.user_id, max_attempts, last_exc, exc_info=True,
        )
        self._driver = None
        self.is_logged_in = False

    def _detect(self) -> None:
        if self._driver is None:
            return
        try:
            self.is_logged_in = self._has_any(self._LOGGED_IN)
            if self.is_logged_in:
                logger.info("WhatsApp session restored for user %s.", self.user_id)
                time.sleep(5)
                self.last_error = None
            else:
                logger.info("WhatsApp QR visible for user %s.", self.user_id)
                self.last_error = None
        except Exception as exc:
            logger.warning("Detect state failed for user %s: %s", self.user_id, exc)
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
                    'button span[data-testid="refresh-l"]',
                    'div[data-testid="qrcode-reload-button"]',
                    'button[aria-label="Reload"]',
                ]:
                    for btn in self._driver.find_elements(By.CSS_SELECTOR, sel):
                        try:
                            btn.click()
                            time.sleep(2)
                            break
                        except Exception:
                            continue

                for sel in self._QR:
                    for el in self._driver.find_elements(By.CSS_SELECTOR, sel):
                        if el.size.get("width", 0) > 100 and el.size.get("height", 0) > 100:
                            return el.screenshot_as_png

                try:
                    dbg = f"/tmp/qr_miss_{self.user_id}.png"
                    self._driver.save_screenshot(dbg)
                    logger.info("QR not found for user %s — screenshot: %s", self.user_id, dbg)
                except Exception:
                    pass
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
            return None

    async def wait_for_scan(self, timeout: int = 120) -> bool:
        if self._driver is None:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if await asyncio.to_thread(lambda: self._has_any(self._LOGGED_IN)):
                    self.is_logged_in = True
                    self.last_error = None
                    logger.info("QR scanned — user %s linked.", self.user_id)
                    return True
            except Exception as exc:
                logger.warning("wait_for_scan error for user %s: %s", self.user_id, exc)
                return False
            await asyncio.sleep(1)
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
                        "document.querySelectorAll('span[data-testid=\"x-alt\"]')"
                        ".forEach(b => { const c = b.closest('[role=\"alert\"]') || "
                        "b.parentElement.parentElement; if (c) c.remove(); });"
                    )
                except Exception:
                    pass
                time.sleep(1)

                search = None
                for sel in [
                    'input[data-tab="3"]',
                    'input[title="Search or start new chat"]',
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

                time.sleep(3)

                msg_box = None
                for sel in [
                    'div[contenteditable="true"][data-tab="10"]',
                    'div[data-testid="conversation-compose-box-input"]',
                ]:
                    els = self._driver.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        msg_box = els[0]
                        break
                if not msg_box:
                    all_ed = self._driver.find_elements(
                        By.CSS_SELECTOR, 'div[contenteditable="true"]')
                    msg_box = all_ed[-1] if all_ed else None
                if not msg_box:
                    raise Exception("Message box not found.")

                msg_box.click()
                time.sleep(0.5)
                for line in message.split("\n"):
                    msg_box.send_keys(line)
                    msg_box.send_keys(Keys.SHIFT + Keys.ENTER)
                time.sleep(0.5)
                msg_box.send_keys(Keys.ENTER)
                time.sleep(2)
                logger.info("Message sent to '%s' for user %s.", group_name, self.user_id)
                return True

            except Exception as exc:
                try:
                    self._driver.save_screenshot(
                        f"/tmp/send_fail_{self.user_id}_{int(time.time())}.png")
                except Exception:
                    pass
                logger.error("send_message error user=%s group='%s': %s",
                             self.user_id, group_name, exc)
                return False
            finally:
                try:
                    self._driver.switch_to.default_content()
                except Exception:
                    pass


# ── Registry ───────────────────────────────────────────────────────────────────

class WhatsAppBot:
    """Registry of per-user _UserSession instances — each user has their own Chrome."""

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
        for session in list(self._sessions.values()):
            session._quit()
        self._sessions.clear()
        logger.info("All WhatsApp sessions closed.")
