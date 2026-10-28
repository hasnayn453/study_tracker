"""Study Tracker - entry point.

Starts the encrypted store, alert sender, screen & webcam monitors, daily
report scheduler, and the system tray UI. Designed to run as a low-overhead
background tray application on Windows and macOS.
"""

from __future__ import annotations

import signal
import sys

from alert import AlertSender
from config import CONFIG, load_config
from monitor_screen import ScreenMonitor
from monitor_webcam import WebcamMonitor
from reporter import DailyReporter
from storage import EncryptedStore
from tray_app import TrayApp


def main() -> int:
    cfg = load_config()

    # Ensure directories exist.
    from pathlib import Path

    for key in ("db_path", "screenshot_dir", "reports_dir"):
        Path(cfg["storage"][key]).parent.mkdir(parents=True, exist_ok=True)

    store = EncryptedStore(cfg["storage"]["db_path"], cfg["encryption"]["key"])
    alert_sender = AlertSender(cfg)

    screen = ScreenMonitor(store, alert_sender, cfg)
    webcam = WebcamMonitor(store, alert_sender, cfg)
    reporter = DailyReporter(store, alert_sender, cfg)

    tray = TrayApp(screen, webcam, reporter, store)

    def handle_signal(signum, frame):  # pragma: no cover - console scripts
        tray._exit_app(tray.icon, None) if tray.icon else None
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        tray.run()
    except KeyboardInterrupt:
        pass
    finally:
        screen.stop()
        webcam.stop()
        reporter.stop_scheduler()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
