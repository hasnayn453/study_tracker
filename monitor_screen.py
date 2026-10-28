"""Module 1: Activity & Screen Monitoring.

Tracks:
  * active window title / application name
  * per-application usage duration (productive vs. non-productive)
  * system idle time (keyboard/mouse inactivity)
  * low-resolution, compressed screenshots at a fixed interval while active

Runs as a daemon thread polling at a configurable interval. All data is
written to the encrypted store.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import mss
from PIL import Image

try:
    import pygetwindow as gw
except Exception:  # pragma: no cover - platform-specific import
    gw = None

from alert import AlertSender
from config import CONFIG
from idle import IdleMonitor
from storage import EncryptedStore


def _classify_productive(app_name: str, cfg: Dict[str, Any]) -> bool:
    """Heuristic: productive if in the allow-list or matching a keyword."""
    screen_cfg = cfg.get("screen_monitoring", {})
    allow_list = {a.lower() for a in screen_cfg.get("productive_apps", [])}
    keywords = [k.lower() for k in screen_cfg.get("productive_keywords", [])]
    name = (app_name or "").lower()
    if name in allow_list:
        return True
    return any(k in name for k in keywords)


class ScreenMonitor:
    def __init__(
        self,
        store: EncryptedStore,
        alert_sender: AlertSender,
        cfg: Dict[str, Any],
    ) -> None:
        self.store = store
        self.alert = alert_sender
        self.cfg = cfg.get("screen_monitoring", {})
        self.idle_cfg = cfg.get("idle_detection", {})

        self.running = False
        self.thread: Optional[Any] = None

        self.poll_interval = float(self.cfg.get("poll_interval", 5))
        self.screenshot_interval = float(self.cfg.get("screenshot_interval", 300))
        self.screenshot_enabled = bool(self.cfg.get("screenshot_enabled", True))
        self.idle_threshold = float(self.idle_cfg.get("threshold_seconds", 300))

        self.idle_monitor = IdleMonitor()
        self.sct = mss.mss() if self.screenshot_enabled else None

        # Runtime state.
        self.current_app: Optional[str] = None
        self.current_title: Optional[str] = None
        self.app_start: Optional[float] = None
        self.idle_start: Optional[float] = None
        self.last_screenshot: float = 0.0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self.thread = __import__("threading").Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        if not self.running:
            return
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=timeout)
        self._flush_current_app()
        if self.idle_start is not None:
            self.store.record_idle(self.idle_start, time.time())
            self.idle_start = None

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def _loop(self) -> None:
        while self.running:
            now = time.time()
            title, app = self._get_active_window()
            idle = self.idle_monitor.get_idle_time()
            is_idle = idle > self.idle_threshold

            # --- App switching: flush previous app usage -------------- #
            if app != self.current_app:
                self._flush_current_app()
                self.current_app = app
                self.current_title = title
                self.app_start = now

            # --- Idle tracking --------------------------------------- #
            if is_idle and self.idle_start is None:
                self.idle_start = now
            elif not is_idle and self.idle_start is not None:
                self.store.record_idle(self.idle_start, now)
                self.idle_start = None

            # --- Screenshots ---------------------------------------- #
            if (
                self.screenshot_enabled
                and not is_idle
                and self.sct is not None
                and now - self.last_screenshot > self.screenshot_interval
            ):
                self._capture_screenshot()
                self.last_screenshot = now

            time.sleep(self.poll_interval)

        # Final flush on exit.
        self._flush_current_app()
        if self.idle_start is not None:
            self.store.record_idle(self.idle_start, time.time())

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _get_active_window(self) -> tuple[str, str]:
        """Return (window_title, app_name). Falls back gracefully."""
        if gw is None:
            return "unknown", "unknown"
        try:
            win = gw.getActiveWindow()
            if win is None:
                return "unknown", "unknown"
            title = win.title or ""
            app = self._app_name(win, title)
            return title, app
        except Exception:
            return "unknown", "unknown"

    @staticmethod
    def _app_name(win: Any, title: str) -> str:
        """Best-effort application name from the window object/title."""
        # Optional: process name via psutil if available.
        try:
            pid = getattr(win, "process", None)
            if pid is not None:
                import psutil  # type: ignore

                return psutil.Process(int(pid)).name()
        except Exception:
            pass
        # Fallback: derive from window title.
        if title:
            return title.split("-")[-1].strip() or title
        return "unknown"

    def _flush_current_app(self) -> None:
        if self.current_app and self.app_start is not None:
            duration = time.time() - self.app_start
            if duration > 1.0:
                productive = _classify_productive(self.current_app, self.cfg)
                self.store.record_app_usage(
                    datetime.now().strftime("%Y-%m-%d"),
                    self.current_app,
                    self.current_title,
                    duration,
                    productive,
                )
        self.app_start = None

    def _capture_screenshot(self) -> None:
        try:
            assert self.sct is not None
            monitor = self.sct.monitors[1]
            shot = self.sct.grab(monitor)
            image = Image.frombytes("RGBA", shot.size, shot.bgra, "raw", "BGRX").convert("RGB")
            image.thumbnail((640, 360))  # low resolution

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_dir = Path(CONFIG["storage"]["screenshot_dir"])
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            path = screenshot_dir / f"shot_{ts}.jpg"
            image.save(path, quality=50, optimize=True)

            self.store.record_screenshot(ts, str(path), path.stat().st_size)
        except Exception as exc:  # pragma: no cover - hardware/permissions
            print(f"[SCREENSHOT ERROR] {exc}")
