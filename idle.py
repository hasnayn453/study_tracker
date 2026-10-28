"""Cross-platform idle-time detection.

Returns the number of seconds since the last keyboard/mouse input.

Strategies (in order of preference):
  * Windows   - GetLastInputInfo via ctypes (accurate, no extra deps)
  * macOS     - CGEventSourceSecondsSinceLastEventType via Quartz/pyobjc
  * Fallback  - cursor-position polling using pyautogui (already a dep of
                pygetwindow); less accurate but works everywhere.
"""

from __future__ import annotations

import sys
import time

try:  # pyautogui is pulled in by pygetwindow; used only as a fallback.
    import pyautogui  # type: ignore

    _HAS_PYAUTOGUI = True
except Exception:  # pragma: no cover
    _HAS_PYAUTOGUI = False


class IdleMonitor:
    """Track system idle time with a stable, cross-platform interface."""

    def __init__(self) -> None:
        self._platform = sys.platform
        self._pos_poller = _PositionPoller() if _HAS_PYAUTOGUI else None
        self._last_time = time.time()
        self._idle = 0.0

    def get_idle_time(self) -> float:
        """Seconds since the last user input."""
        if self._platform.startswith("win"):
            return _idle_windows()
        if self._platform == "darwin":
            value = _idle_macos()
            if value is not None:
                return value
        # Polling fallback (all platforms).
        return self._pos_poller.get_idle_time() if self._pos_poller else 0.0


class _PositionPoller:
    """Approximate idle time by watching cursor movement."""

    def __init__(self) -> None:
        self._last_pos = pyautogui.position()
        self._last_time = time.time()
        self._idle = 0.0

    def get_idle_time(self) -> float:
        pos = pyautogui.position()
        now = time.time()
        if pos != self._last_pos:
            self._idle = 0.0
            self._last_pos = pos
            self._last_time = now
        else:
            self._idle += now - self._last_time
            self._last_time = now
        return self._idle


# --------------------------------------------------------------------------- #
# Platform-specific implementations
# --------------------------------------------------------------------------- #
def _idle_windows() -> float:
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]

    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    tick = ctypes.windll.kernel32.GetTickCount()
    return max(0.0, (tick - lii.dwTime) / 1000.0)


def _idle_macos():
    """Seconds since last input on macOS, or None if Quartz unavailable."""
    try:
        from Quartz import (  # type: ignore
            CGEventSourceSecondsSinceLastEventType,
            kCGEventAny,
            kCGEventSourceStateHIDSystemState,
        )

        return float(
            CGEventSourceSecondsSinceLastEventType(
                kCGEventSourceStateHIDSystemState, kCGEventAny
            )
        )
    except Exception:
        return None
