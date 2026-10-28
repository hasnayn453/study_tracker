"""Module 4: Daily Reporting & Analytics.

Aggregates the day's monitoring data and produces:
  * a Markdown summary (human readable)
  * a JSON summary (machine readable)
  * a CSV of per-application usage

Reports are written to ``reports/``. Transmission (email / optional S3)
is handled here too.
"""

from __future__ import annotations

import csv
import io
import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from alert import AlertSender
from config import CONFIG
from storage import EncryptedStore


class DailyReporter:
    def __init__(
        self,
        store: EncryptedStore,
        alert_sender: AlertSender,
        cfg: Dict[str, Any],
    ) -> None:
        self.store = store
        self.alert = alert_sender
        self.cfg = cfg.get("reporting", {})
        self.storage_cfg = cfg.get("storage", {})
        self.alert_cfg = cfg.get("alerts", {})

        self.reports_dir = Path(self.storage_cfg.get("reports_dir", "reports"))
        if not self.reports_dir.is_absolute():
            from config import CONFIG as _cfg

            self.reports_dir = Path(_cfg["storage"]["reports_dir"])
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        self._last_report_date: Optional[str] = None
        self._thread: Optional[Any] = None
        self._stop = False

    # ------------------------------------------------------------------ #
    # Scheduler (runs daily at the configured hour:minute)
    # ------------------------------------------------------------------ #
    def start_scheduler(self) -> None:
        self._stop = False
        self._thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self._thread.start()

    def stop_scheduler(self, timeout: float = 5.0) -> None:
        self._stop = True
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _scheduler_loop(self) -> None:
        hour = int(self.cfg.get("daily_report_hour", 23))
        minute = int(self.cfg.get("daily_report_minute", 0))
        while not self._stop:
            now = datetime.now()
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now > target:
                target += timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            # Wake every 30s so stop is responsive.
            slept = 0.0
            while slept < wait_seconds and not self._stop:
                time.sleep(min(30, wait_seconds - slept))
                slept += 30
            if self._stop:
                return
            self.generate_report(now.strftime("%Y-%m-%d"), transmit=True)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def generate_report(self, date: Optional[str] = None, transmit: bool = False) -> Dict[str, str]:
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        self._last_report_date = date

        app_usage = self.store.get_app_usage(date)
        idle_seconds = self.store.get_idle_seconds(date)
        active_seconds = self.store.get_active_seconds(date)
        presence = self.store.get_presence_stats(date)
        screenshots = self.store.get_screenshots(date)
        alerts = self.store.get_alerts(date)

        total_monitored = active_seconds + idle_seconds
        active_pct = (active_seconds / total_monitored * 100) if total_monitored else 0.0
        idle_pct = (idle_seconds / total_monitored * 100) if total_monitored else 0.0

        productive_seconds = sum(row.get("productive_seconds", 0) or 0 for row in app_usage)
        non_productive_seconds = sum(
            (row.get("total_seconds", 0) or 0) - (row.get("productive_seconds", 0) or 0)
            for row in app_usage
        )

        summary = {
            "date": date,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_active_seconds": round(active_seconds, 2),
            "total_idle_seconds": round(idle_seconds, 2),
            "active_percentage": round(active_pct, 2),
            "idle_percentage": round(idle_pct, 2),
            "productive_seconds": round(productive_seconds, 2),
            "non_productive_seconds": round(non_productive_seconds, 2),
            "presence_compliance_rate": presence.get("compliance_rate", 100.0),
            "presence_absence_seconds": presence.get("total_absence_seconds", 0),
            "screenshot_count": len(screenshots),
            "alert_count": len(alerts),
            "app_usage": app_usage,
            "alerts": alerts,
        }

        # Upsert session rollup.
        self.store.upsert_session(
            date,
            start_time=summary["generated_at"],
            end_time=summary["generated_at"],
            total_active_seconds=round(active_seconds, 2),
            total_idle_seconds=round(idle_seconds, 2),
            presence_compliance_rate=presence.get("compliance_rate", 100.0),
        )

        paths: Dict[str, str] = {}
        paths["markdown"] = self._write_markdown(summary)
        paths["json"] = self._write_json(summary)
        paths["csv"] = self._write_csv(app_usage, date)

        print(f"[REPORT] Daily summary for {date}: {paths['markdown']}")

        if transmit:
            self._transmit(summary, paths)

        return paths

    def report_now(self) -> Dict[str, str]:
        """Immediately generate today's report (used by the tray menu)."""
        return self.generate_report(transmit=False)

    # ------------------------------------------------------------------ #
    # Writers
    # ------------------------------------------------------------------ #
    def _write_markdown(self, summary: Dict[str, Any]) -> str:
        date = summary["date"]
        path = self.reports_dir / f"report_{date}.md"
        lines = [
            f"# Study Session Report - {date}",
            "",
            f"Generated: {summary['generated_at']}",
            "",
            "## Summary",
            f"- Total active working time: {self._fmt(summary['total_active_seconds'])}",
            f"- Total idle time: {self._fmt(summary['total_idle_seconds'])}",
            f"- Active share: {summary['active_percentage']}%",
            f"- Idle share: {summary['idle_percentage']}%",
            f"- Productive time: {self._fmt(summary['productive_seconds'])}",
            f"- Non-productive time: {self._fmt(summary['non_productive_seconds'])}",
            f"- Presence compliance: {summary['presence_compliance_rate']}%",
            f"- Total absence: {self._fmt(summary['presence_absence_seconds'])}",
            f"- Screenshots captured: {summary['screenshot_count']}",
            f"- Alerts fired: {summary['alert_count']}",
            "",
        ]
        if summary["app_usage"]:
            lines += ["## Application Usage", "| App | Time (min) | Productive | Entries |", "|---|---|---|---|"]
            for row in summary["app_usage"]:
                mins = round((row.get("total_seconds") or 0) / 60, 1)
                prod = round((row.get("productive_seconds") or 0) / 60, 1)
                lines.append(
                    f"| {row['app_name']} | {mins} | {'Yes' if row['productive_seconds'] else 'No'} | {row['entries']} |"
                )
            lines.append("")
        if summary["alerts"]:
            lines += ["## Alerts", "| Time | Kind | Message |", "|---|---|---|"]
            for a in summary["alerts"]:
                lines.append(f"| {a['timestamp']} | {a['kind']} | {a['message']} |")
            lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return str(path)

    def _write_json(self, summary: Dict[str, Any]) -> str:
        report_date = summary["date"]
        path = self.reports_dir / f"report_{report_date}.json"
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return str(path)

    def _write_csv(self, app_usage: list, date: str) -> str:
        path = self.reports_dir / f"app_usage_{date}.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["app_name", "total_seconds", "productive_seconds", "entries"])
            for row in app_usage:
                writer.writerow(
                    [
                        row.get("app_name"),
                        row.get("total_seconds"),
                        row.get("productive_seconds"),
                        row.get("entries"),
                    ]
                )
        return str(path)

    # ------------------------------------------------------------------ #
    # Transmission
    # ------------------------------------------------------------------ #
    def _transmit(self, summary: Dict[str, Any], paths: Dict[str, str]) -> None:
        # Email the markdown report if configured.
        if self.alert_cfg.get("enabled") and self.cfg.get("email_report"):
            self._send_email_report(paths["markdown"], summary["date"])

        # Optional S3 upload (boto3). Best-effort; missing dep is not fatal.
        bucket = self.cfg.get("s3_bucket", "")
        if bucket:
            try:
                import boto3  # type: ignore

                s3 = boto3.client("s3", region_name=self.cfg.get("s3_region", "us-east-1"))
                for kind, local in paths.items():
                    key = f"study-reports/{summary['date']}/{Path(local).name}"
                    s3.upload_file(local, bucket, key)
                print(f"[REPORT] Uploaded to S3 bucket '{bucket}'.")
            except Exception as exc:  # pragma: no cover - network/cred
                print(f"[REPORT] S3 upload failed: {exc}")

    def _send_email_report(self, markdown_path: str, date: str) -> None:
        email = self.alert_cfg.get("email", {})
        if not (email.get("username") and email.get("password") and email.get("to_address")):
            return
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = f"Study Tracker - Daily Report ({date})"
        msg["From"] = email["username"]
        msg["To"] = email["to_address"]
        msg.set_content(Path(markdown_path).read_text(encoding="utf-8"))

        try:
            server = smtplib.SMTP(email.get("smtp_server", "smtp.gmail.com"), int(email.get("smtp_port", 587)))
            server.starttls()
            server.login(email["username"], email["password"])
            server.send_message(msg)
            server.quit()
            print(f"[REPORT] Emailed daily report to {email['to_address']}.")
        except Exception as exc:  # pragma: no cover - network
            print(f"[REPORT] Email send failed: {exc}")

    @staticmethod
    def _fmt(seconds: float) -> str:
        seconds = int(round(seconds))
        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)
        if h:
            return f"{h}h {m}m {s}s"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"
