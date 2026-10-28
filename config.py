"""Configuration loader for Study Tracker.

Loads configuration from config.json (next to the executable/script) with
sensible defaults. All storage paths are resolved relative to the app
directory so the program works both as a script and as a PyInstaller
frozen executable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict


def app_dir() -> Path:
    """Directory where config/data live (next to exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_DIR = app_dir()
CONFIG_PATH = APP_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "encryption": {"key": None},
    "storage": {
        "db_path": "data/study_tracker.db",
        "screenshot_dir": "data/screenshots",
        "reports_dir": "reports",
    },
    "screen_monitoring": {
        "poll_interval": 5,
        "screenshot_interval": 300,
        "screenshot_enabled": True,
        "productive_apps": [],
        "productive_keywords": [
            "code",
            "dev",
            "study",
            "learn",
            "document",
            "pdf",
            "notion",
            "obsidian",
        ],
    },
    "idle_detection": {"threshold_seconds": 300},
    "webcam": {
        "enabled": True,
        "camera_index": 0,
        "check_interval": 5,
        "face_detector": "haar",
        "absence_threshold_seconds": 180,
        "alert_cooldown_seconds": 300,
    },
    "alerts": {
        "enabled": True,
        "cooldown_seconds": 60,
        "telegram": {"bot_token": "", "chat_id": ""},
        "discord": {"webhook_url": ""},
        "email": {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "username": "",
            "password": "",
            "to_address": "",
        },
    },
    "reporting": {
        "daily_report_hour": 23,
        "daily_report_minute": 0,
        "email_report": False,
        "s3_bucket": "",
        "s3_region": "us-east-1",
    },
    "stealth": {"tray_only": True, "show_console": False},
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def load_config() -> Dict[str, Any]:
    """Load config.json, merge with defaults, and persist any new keys."""
    cfg: Dict[str, Any] = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy

    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                _deep_merge(cfg, user_cfg)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[WARN] Failed to read config.json: {exc}. Using defaults.")

    # Resolve storage paths relative to APP_DIR.
    for key in ("db_path", "screenshot_dir", "reports_dir"):
        path = Path(cfg["storage"][key])
        if not path.is_absolute():
            cfg["storage"][key] = str(APP_DIR / path)

    # Ensure an encryption key exists (generate + persist if missing).
    if not cfg["encryption"].get("key"):
        from cryptography.fernet import Fernet

        cfg["encryption"]["key"] = Fernet.generate_key().decode()
        save_config(cfg)

    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """Persist the full configuration to config.json."""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


# Module-level config (loaded once at import time).
CONFIG = load_config()
