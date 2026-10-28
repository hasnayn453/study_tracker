"""System-tray application wrapper.

Provides a lightweight background presence (no main window) with a context
menu to show/hide the console, toggle monitoring, generate a report on
demand, and exit cleanly.
"""

from __future__ import annotations

import threading
from typing import Any, Optional

import pystray
from PIL import Image, ImageDraw

from reporter import DailyReporter
from storage import EncryptedStore


def _make_icon_image() -> Image.Image:
    """Draw a simple tray icon (no external image asset required)."""
    image = Image.new("RGB", (64, 64), color=(30, 130, 220))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([8, 8, 56, 56], radius=14, fill=(255, 255, 255))
    draw.text((22, 22), "ST", fill=(30, 130, 220))
    return image


class TrayApp:
    def __init__(
        self,
        screen_monitor: Any,
        webcam_monitor: Any,
        reporter: DailyReporter,
        store: EncryptedStore,
    ) -> None:
        self.screen = screen_monitor
        self.webcam = webcam_monitor
        self.reporter = reporter
        self.store = store
        self.icon: Optional[pystray.Icon] = None
        self._visible = True

    # ------------------------------------------------------------------ #
    # Menu actions
    # ------------------------------------------------------------------ #
    def _toggle_monitoring(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        if self.screen.running or self.webcam.running:
            self.screen.stop()
            self.webcam.stop()
            item.text = "Start Monitoring"
            print("[TRAY] Monitoring stopped.")
        else:
            self.screen.start()
            self.webcam.start()
            item.text = "Stop Monitoring"
            print("[TRAY] Monitoring started.")
        icon.title = (
            "Study Tracker - Monitoring" if item.text == "Stop Monitoring" else "Study Tracker - Stopped"
        )
        icon.update_menu()

    def _report_now(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        def _run() -> None:
            paths = self.reporter.report_now()
            print(f"[TRAY] Report generated: {paths['markdown']}")

        threading.Thread(target=_run, daemon=True).start()

    def _exit_app(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        self.screen.stop()
        self.webcam.stop()
        self.reporter.stop_scheduler()
        self.store.close()
        icon.stop()

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        def make_menu() -> pystray.Menu:
            monitor_text = (
                "Stop Monitoring"
                if (self.screen.running or self.webcam.running)
                else "Start Monitoring"
            )
            return pystray.Menu(
                pystray.MenuItem(monitor_text, self._toggle_monitoring),
                pystray.MenuItem("Generate Report Now", self._report_now),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit", self._exit_app),
            )

        self.icon = pystray.Icon(
            "study_tracker",
            _make_icon_image(),
            title="Study Tracker - Stopped",
            menu=make_menu(),
        )

        # Start background monitors + scheduler before showing the tray.
        self.screen.start()
        self.webcam.start()
        self.reporter.start_scheduler()
        self.icon.title = "Study Tracker - Monitoring"

        self.icon.run(setup=self._setup_icon)

    @staticmethod
    def _setup_icon(icon: pystray.Icon) -> None:
        """Called once the icon is visible; keeps the menu updated."""
        icon.visible = True
