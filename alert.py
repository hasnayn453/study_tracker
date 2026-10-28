"""Real-time alerting via Telegram, Discord webhook, and/or SMTP email."""

from __future__ import annotations

import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from typing import Any, Dict, Optional

import requests


class AlertSender:
    """Send desk-absence / inactivity alerts through configured channels."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg.get("alerts", {})
        self.enabled = bool(self.cfg.get("enabled", True))
        self.cooldown = float(self.cfg.get("cooldown_seconds", 60))
        self._last_alert: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def send(self, message: str, kind: str = "absence") -> None:
        """Send an alert across every enabled channel (with per-kind cooldown)."""
        if not self.enabled:
            return

        now = time.time()
        if now - self._last_alert.get(kind, 0) < self.cooldown:
            return
        self._last_alert[kind] = now

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = f"[{timestamp}] {kind.upper()}: {message}"

        errors: list[str] = []
        try:
            self._send_telegram(body)
        except Exception as exc:  # pragma: no cover - network
            errors.append(f"telegram: {exc}")
        try:
            self._send_discord(body)
        except Exception as exc:
            errors.append(f"discord: {exc}")
        try:
            self._send_email(kind, body)
        except Exception as exc:
            errors.append(f"email: {exc}")

        if errors:
            print(f"[ALERT ERROR] {'; '.join(errors)}")
        else:
            print(f"[ALERT] {body}")

    # ------------------------------------------------------------------ #
    # Channel implementations
    # ------------------------------------------------------------------ #
    def _send_telegram(self, body: str) -> None:
        tg = self.cfg.get("telegram", {})
        token = tg.get("bot_token", "")
        chat_id = tg.get("chat_id", "")
        if not token or not chat_id:
            return
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(
            url,
            json={"chat_id": chat_id, "text": body, "disable_notification": False},
            timeout=10,
        ).raise_for_status()

    def _send_discord(self, body: str) -> None:
        url = self.cfg.get("discord", {}).get("webhook_url", "")
        if not url:
            return
        requests.post(url, json={"content": body}, timeout=10).raise_for_status()

    def _send_email(self, kind: str, body: str) -> None:
        email = self.cfg.get("email", {})
        username = email.get("username", "")
        password = email.get("password", "")
        to_address = email.get("to_address", "")
        if not (username and password and to_address):
            return

        msg = EmailMessage()
        msg["Subject"] = f"Study Tracker Alert - {kind}"
        msg["From"] = username
        msg["To"] = to_address
        msg.set_content(body)

        server = smtplib.SMTP(email.get("smtp_server", "smtp.gmail.com"), int(email.get("smtp_port", 587)))
        server.starttls()
        server.login(username, password)
        server.send_message(msg)
        server.quit()
