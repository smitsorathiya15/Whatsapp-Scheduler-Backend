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


class BrowserUnavailableError(RuntimeError):
    """Raised when no Chrome/Chromium binary is available on the host."""


def _find_chrome_binary() -> Optional[str]:
    """
    Locate the Chrome binary.
    Checks common Linux paths first, then falls back to settings override.
    """
    candidates = [
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/snap/bin/chromium",
    ]
    override = getattr(settings, "WA_CHROME_BINARY", None) or os.getenv("CHROME_BIN")
    if override:
        candidates.insert(0, override)

    for path in candidates:
        if Path(path).exists():
            logger.info("Found Chrome binary at: %s", path)
            return path

    logger.warning("Could not find Chrome binary in any standard location.")
    return None


def _read_command_version(command: list[str]) -> Optional[str]:
    """Return the first line of `<cmd> --version` output when available."""
    try:
        result = subprocess.run(
            command + ["--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        logger.debug("Version check failed for %s: %s", command, exc)
        return None

    for stream in (result.stdout, result.stderr):
        text = (stream or "").strip()
        if text:
            return text.splitlines()[0].strip()
    return None


# ── Per-user driver wrapper ────────────────────────────────────────────────────


class _UserSession:
    """
    One Chrome instance dedicated to a single user.
    Holds the driver, login state, and a send lock for that user only.
    """

    def __init__(self, user_id: uuid.UUID) -> None:
        self.user_id = user_id
        self.is_logged_in = False
        self.last_error: Optional[str] = None
        self._driver: Optional[webdriver.Chrome] = None
        self._driver_lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._init_lock = asyncio.Lock()

    # ── Profile ───────────────────────────────────────────────────────────────

    @property
    def _profile_path(self) -> Path:
        return Path(settings.WA_PROFILE_DIR).resolve() / str(self.user_id)

    @property
    def _runtime_base_path(self) -> Path:
        return Path("/tmp/wa_runtime").resolve() / str(self.user_id)

    @staticmethod
    def _logged_in_selectors() -> list[str]:
        return [
            'div[data-testid="chat-list"]',
            'div#pane-side',
            'div[contenteditable="true"][data-tab="3"]',
            'input[data-tab="3"]',
            '[data-testid="intro-text"]',
        ]

    @staticmethod
    def _qr_selectors() -> list[str]:
        return [
            'canvas[aria-label="Scan me!"]',
            'canvas[aria-label="Scan this QR code to link a device"]',
            'div[data-testid="qrcode"] canvas',
            'div[data-ref] canvas',
            '.landing-main canvas',
            'canvas',
        ]

    def _has_any(self, selectors: list[str], min_size: int = 0) -> bool:
        with self._driver_lock:
            if self._driver is None:
                return False
            for sel in selectors:
                for el in self._driver.find_elements(By.CSS_SELECTOR, sel):
                    if min_size <= 0:
                        return True
                    if el.size.get("width", 0) >= min_size and el.size.get("height", 0) >= min_size:
                        return True
        return False

    def _save_debug_screenshot(self, prefix: str) -> None:
        with self._driver_lock:
            if self._driver is None:
                return
            try:
                dbg = Path(f"{prefix}_{self.user_id}_{int(time.time())}.png").resolve()
                self._driver.save_screenshot(str(dbg))
                logger.info("Saved debug screenshot for user %s: %s", self.user_id, dbg)
            except Exception as exc:
                logger.debug("Could not save screenshot for user %s: %s", self.user_id, exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def ensure_started(self) -> None:
        """Start Chrome for this user if not already running."""
        async with self._init_lock:
            if self._driver is not None:
                return
            await asyncio.to_thread(self._start)

    def _clear_locks(self, profile: Path) -> None:
        for name in ["SingletonLock", "DevToolsActivePort", "lock"]:
            p = profile / name
            if not p.exists():
                continue
            for i in range(5):
                try:
                    shutil.rmtree(p) if p.is_dir() else os.remove(p)
                    logger.debug("Removed lock file: %s", name)
                    break
                except Exception as exc:
                    if i == 4:
                        logger.warning("Could not remove lock %s: %s", name, exc)
                    time.sleep(0.2)

    def _kill_stale_chrome(self, profile: Path) -> None:
        """Kill stale Chrome processes using this profile (Linux + Windows)."""
        try:
            result = subprocess.run(
                ["wmic", "process", "where", "name='chrome.exe'", "get", "ProcessId,CommandLine"],
                capture_output=True, text=True, timeout=10,
            )
            profile_str = str(profile).replace("/", "\\")
            for line in result.stdout.splitlines():
                if profile_str.lower() in line.lower():
                    for part in line.strip().split():
                        if part.isdigit():
                            try:
                                subprocess.run(["taskkill", "/F", "/PID", part], capture_output=True, timeout=5)
                                logger.info("Killed stale Chrome PID %s (Windows)", part)
                            except Exception:
                                pass
        except FileNotFoundError:
            # wmic not available — likely Linux, try pkill
            try:
                profile_str = str(profile)
                subprocess.run(
                    ["pkill", "-f", f"user-data-dir={profile_str}"],
                    capture_output=True, timeout=5,
                )
                logger.debug("pkill ran for profile %s", profile_str)
            except Exception as exc:
                logger.debug("Stale chrome kill skipped: %s", exc)
        except Exception as exc:
            logger.debug("Stale chrome check skipped: %s", exc)

    def _build_options(self, profile: Path) -> Options:
        options = Options()
        options.add_argument(f"--user-data-dir={profile}")
        runtime_base = self._runtime_base_path
        runtime_base.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--data-path={runtime_base / 'data-path'}")
        options.add_argument(f"--disk-cache-dir={runtime_base / 'disk-cache'}")
        options.add_argument(f"--homedir={runtime_base / 'home'}")

        # Core stability
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--disable-extensions")
        options.add_argument("--no-zygote")

        # Prevent DevToolsActivePort crash without pipe issues
        options.add_argument("--remote-debugging-port=0")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-backgrounding-occluded-windows")
        options.add_argument("--disable-renderer-backgrounding")
        options.add_argument("--disable-features=VizDisplayCompositor,TranslateUI")
        options.add_argument("--disable-features=site-per-process,IsolateOrigins")
        options.add_argument("--disable-ipc-flooding-protection")
        options.add_argument("--disable-hang-monitor")
        options.add_argument("--disable-prompt-on-repost")
        options.add_argument("--disable-client-side-phishing-detection")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-sync")
        options.add_argument("--metrics-recording-only")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--password-store=basic")
        options.add_argument("--no-service-autorun")
        options.add_argument("--force-color-profile=srgb")

        # Anti-detection
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        # Always headless on server — set WA_HEADLESS=False only for local debugging
        if getattr(settings, "WA_HEADLESS", True):
            options.add_argument("--headless=new")
            options.add_argument("--window-size=1280,900")

        options.page_load_strategy = "eager"

        # Point Selenium to the correct Chrome binary
        chrome_binary = _find_chrome_binary()
        if chrome_binary:
            options.binary_location = chrome_binary

        return options

    def _start(self) -> None:
        profile = self._profile_path
        profile.mkdir(parents=True, exist_ok=True)

        chrome_binary = _find_chrome_binary()
        if not chrome_binary:
            self.last_error = "Chrome/Chromium browser is not installed on the server."
            logger.error("Cannot start WhatsApp session for user %s: %s", self.user_id, self.last_error)
            self._driver = None
            self.is_logged_in = False
            return

        self._kill_stale_chrome(profile)
        time.sleep(1)
        self._clear_locks(profile)

        max_attempts = 3
        last_exc = None
        chromedriver_path = shutil.which("chromedriver")
        chrome_version = _read_command_version([chrome_binary]) if chrome_binary else None
        driver_version = _read_command_version([chromedriver_path]) if chromedriver_path else None

        if chrome_version or driver_version:
            logger.info(
                "WhatsApp browser versions for user %s: chrome=%s driver=%s",
                self.user_id,
                chrome_version or "unknown",
                driver_version or "unknown",
            )

        for attempt in range(1, max_attempts + 1):
            try:
                options = self._build_options(profile)
                logger.info(
                    "Starting Chromium for user %s with binary=%s driver=%s profile=%s runtime=%s headless=%s",
                    self.user_id,
                    chrome_binary,
                    chromedriver_path or "webdriver-manager",
                    profile,
                    self._runtime_base_path,
                    getattr(settings, "WA_HEADLESS", True),
                )
                service = Service(chromedriver_path) if chromedriver_path else Service(ChromeDriverManager().install())
                with self._driver_lock:
                    self._driver = webdriver.Chrome(service=service, options=options)
                    self.last_error = None

                    handles = self._driver.window_handles
                    if len(handles) > 1:
                        self._driver.switch_to.window(handles[-1])

                    self._driver.get("https://web.whatsapp.com")
                    logger.info("Chrome started for user %s (attempt %d) and waiting for WhatsApp Web.", self.user_id, attempt)
                    WebDriverWait(self._driver, 75).until(
                        lambda d: self._has_any(self._logged_in_selectors()) or self._has_any(self._qr_selectors(), min_size=100)
                    )
                self._detect()
                return

            except Exception as exc:
                last_exc = exc
                self.last_error = str(exc)
                logger.warning("Chrome start attempt %d/%d failed for user %s: %s", attempt, max_attempts, self.user_id, exc)
                with self._driver_lock:
                    if self._driver:
                        try:
                            self._driver.quit()
                        except Exception:
                            pass
                        self._driver = None

                if attempt < max_attempts:
                    self._kill_stale_chrome(profile)
                    time.sleep(2)
                    self._clear_locks(profile)
                    time.sleep(1)

        logger.error("Chrome start failed for user %s after %d attempts: %s", self.user_id, max_attempts, last_exc, exc_info=True)
        self._driver = None
        self.is_logged_in = False

    def _detect(self) -> None:
        with self._driver_lock:
            if self._driver is None:
                return
            try:
                WebDriverWait(self._driver, 45).until(
                    lambda d: self._has_any(self._logged_in_selectors()) or self._has_any(self._qr_selectors(), min_size=100)
                )
                self.is_logged_in = self._has_any(self._logged_in_selectors())
                if self.is_logged_in:
                    logger.info("Session restored for user %s.", self.user_id)
                    time.sleep(5)
                    self.last_error = None
                else:
                    logger.info("QR visible for user %s.", self.user_id)
                    self.last_error = None
            except Exception as exc:
                logger.warning("Detect login failed for user %s: %s", self.user_id, exc)
                self.last_error = "WhatsApp Web loaded slowly or QR was not visible yet."
                self.is_logged_in = False
                self._save_debug_screenshot("detect_fail")
            finally:
                try:
                    self._driver.switch_to.default_content()
                except Exception:
                    pass

    async def stop(self) -> None:
        async with self._init_lock:
            await asyncio.to_thread(self._quit)
            self.is_logged_in = False
            self.last_error = None

    def _quit(self) -> None:
        with self._driver_lock:
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
                with self._driver_lock:
                    try:
                        WebDriverWait(self._driver, 30).until(
                            lambda d: self._has_any(self._qr_selectors(), min_size=100) or self._has_any(self._logged_in_selectors())
                        )
                    except Exception:
                        logger.debug("QR wait timed out for user %s before capture.", self.user_id)

                    for reload_sel in [
                        'button span[data-testid="refresh-l"]',
                        'div[data-testid="qrcode-reload-button"]',
                        'button[aria-label="Reload"]',
                    ]:
                        btns = self._driver.find_elements(By.CSS_SELECTOR, reload_sel)
                        if btns:
                            try:
                                btns[0].click()
                                time.sleep(2)
                                break
                            except Exception:
                                continue

                    for sel in self._qr_selectors():
                        for el in self._driver.find_elements(By.CSS_SELECTOR, sel):
                            if el.size.get("width", 0) > 100 and el.size.get("height", 0) > 100:
                                return el.screenshot_as_png

                    self._save_debug_screenshot("qr_missing")
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
                with self._driver_lock:
                    return self._has_any(self._logged_in_selectors())
            try:
                if await asyncio.to_thread(_check):
                    self.is_logged_in = True
                    self.last_error = None
                    logger.info("QR scanned — user %s linked.", self.user_id)
                    return True
            except Exception as exc:
                logger.warning("wait_for_scan check failed for user %s: %s", self.user_id, exc)
                self.last_error = "Lost connection to the browser. Please refresh the QR and try again."
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
            with self._driver_lock:
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
                        'div[contenteditable="true"][data-id="message-container"]',
                    ]:
                        els = self._driver.find_elements(By.CSS_SELECTOR, sel)
                        if els:
                            msg_box = els[0]
                            break

                    if not msg_box:
                        all_editables = self._driver.find_elements(By.CSS_SELECTOR, 'div[contenteditable="true"]')
                        msg_box = all_editables[-1] if all_editables else None

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
                        self._driver.save_screenshot(str(Path(f"send_fail_{self.user_id}_{int(time.time())}.png").resolve()))
                    except Exception:
                        pass
                    logger.error("send_message error for user %s / group '%s': %s", self.user_id, group_name, exc, exc_info=True)
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
