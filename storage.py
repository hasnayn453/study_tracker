"""Encrypted local storage backend.

Study data is kept in a SQLite database. At rest the database file is
encrypted with Fernet (symmetric AES) using a key stored in config.json.
The plaintext DB only exists while the process is running; on shutdown it
is re-encrypted to ``<db>.enc`` and the plaintext is removed.

Tables:
  sessions        - daily rollup of active/idle/presence
  app_usage       - per-application usage duration
  idle_events     - contiguous idle periods
  presence_events - webcam presence / absence events
  screenshots     - captured screenshot metadata
  alerts          - alerts that were fired
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from cryptography.fernet import Fernet


class EncryptedStore:
    def __init__(self, db_path: str, key: Any):
        self.db_path = Path(db_path)
        self.enc_path = Path(str(db_path) + ".enc")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        fernet_key = key.encode() if isinstance(key, str) else key
        self._fernet = Fernet(fernet_key)

        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None
        self._load()

    # ------------------------------------------------------------------ #
    # Lifecycle / encryption
    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        # If an encrypted at-rest file exists but no plaintext, decrypt it.
        if self.enc_path.exists() and not self.db_path.exists():
            plaintext = self._fernet.decrypt(self.enc_path.read_bytes())
            self.db_path.write_bytes(plaintext)
            self.enc_path.unlink()

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._init_schema()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.commit()
                self._conn.close()
                self._conn = None
        # Encrypt the database at rest.
        if self.db_path.exists():
            plaintext = self.db_path.read_bytes()
            self.enc_path.write_bytes(self._fernet.encrypt(plaintext))
            self.db_path.unlink()

    # ------------------------------------------------------------------ #
    # Schema
    # ------------------------------------------------------------------ #
    def _init_schema(self) -> None:
        assert self._conn is not None
        cur = self._conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                total_active_seconds REAL DEFAULT 0,
                total_idle_seconds REAL DEFAULT 0,
                presence_compliance_rate REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS app_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                app_name TEXT NOT NULL,
                window_title TEXT,
                duration_seconds REAL NOT NULL,
                productive INTEGER NOT NULL DEFAULT 0,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS idle_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                duration_seconds REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS presence_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                present INTEGER NOT NULL,
                absence_duration_seconds REAL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS screenshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                file_path TEXT NOT NULL,
                file_size INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_app_usage_date ON app_usage(date);
            CREATE INDEX IF NOT EXISTS idx_idle_date ON idle_events(date);
            CREATE INDEX IF NOT EXISTS idx_presence_date ON presence_events(date);
            CREATE INDEX IF NOT EXISTS idx_screenshots_date ON screenshots(date);
            CREATE INDEX IF NOT EXISTS idx_alerts_date ON alerts(date);
        """
        )
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _now_iso() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _today() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _execute(self, sql: str, params=()) -> sqlite3.Cursor:
        assert self._conn is not None
        with self._lock:
            return self._conn.execute(sql, params)

    def _commit(self) -> None:
        assert self._conn is not None
        with self._lock:
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Write APIs used by the monitors
    # ------------------------------------------------------------------ #
    def record_app_usage(
        self,
        date: str,
        app_name: str,
        window_title: Optional[str],
        duration_seconds: float,
        productive: bool,
    ) -> None:
        if duration_seconds <= 0:
            return
        self._execute(
            """
            INSERT INTO app_usage
                (date, app_name, window_title, duration_seconds, productive, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                date,
                app_name,
                window_title,
                round(duration_seconds, 2),
                1 if productive else 0,
                self._now_iso(),
            ),
        )
        self._commit()

    def record_idle(self, start_time: float, end_time: float) -> None:
        duration = end_time - start_time
        if duration <= 0:
            return
        date = self._today()
        self._execute(
            """
            INSERT INTO idle_events (date, start_time, end_time, duration_seconds)
            VALUES (?, ?, ?, ?)
            """,
            (
                date,
                datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M:%S"),
                datetime.fromtimestamp(end_time).strftime("%Y-%m-%d %H:%M:%S"),
                round(duration, 2),
            ),
        )
        self._commit()

    def record_presence(
        self,
        timestamp: float,
        present: bool,
        absence_duration: float = 0.0,
    ) -> None:
        date = self._today()
        self._execute(
            """
            INSERT INTO presence_events (date, timestamp, present, absence_duration_seconds)
            VALUES (?, ?, ?, ?)
            """,
            (
                date,
                datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                1 if present else 0,
                round(absence_duration, 2),
            ),
        )
        self._commit()

    def record_screenshot(self, timestamp: str, file_path: str, file_size: int) -> None:
        date = datetime.now().strftime("%Y-%m-%d")
        self._execute(
            """
            INSERT INTO screenshots (date, timestamp, file_path, file_size)
            VALUES (?, ?, ?, ?)
            """,
            (date, timestamp, file_path, file_size),
        )
        self._commit()

    def record_alert(self, kind: str, message: str) -> None:
        date = self._today()
        self._execute(
            """
            INSERT INTO alerts (date, timestamp, kind, message)
            VALUES (?, ?, ?, ?)
            """,
            (date, self._now_iso(), kind, message),
        )
        self._commit()

    def upsert_session(self, date: str, **fields: Any) -> None:
        """Insert or update a daily session rollup row."""
        assert self._conn is not None
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "SELECT id FROM sessions WHERE date = ?", (date,)
            )
            row = cur.fetchone()
            if row is None:
                cols = ", ".join(fields.keys())
                placeholders = ", ".join("?" for _ in fields)
                values = [date] + list(fields.values())
                cur.execute(
                    f"INSERT INTO sessions (date, {cols}) VALUES (?, {placeholders})",
                    values,
                )
            else:
                assignments = ", ".join(f"{k} = ?" for k in fields)
                values = list(fields.values()) + [date]
                cur.execute(
                    f"UPDATE sessions SET {assignments} WHERE date = ?", values
                )
            self._conn.commit()

    # ------------------------------------------------------------------ #
    # Read / aggregate APIs used by the reporter
    # ------------------------------------------------------------------ #
    def get_app_usage(self, date: str) -> List[Dict[str, Any]]:
        assert self._conn is not None
        cur = self._conn.execute(
            """
            SELECT app_name, window_title,
                   SUM(duration_seconds) as total_seconds,
                   SUM(CASE WHEN productive = 1 THEN duration_seconds ELSE 0 END) as productive_seconds,
                   COUNT(*) as entries
            FROM app_usage
            WHERE date = ?
            GROUP BY app_name
            ORDER BY total_seconds DESC
            """,
            (date,),
        )
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_idle_seconds(self, date: str) -> float:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) FROM idle_events WHERE date = ?",
            (date,),
        )
        return float(cur.fetchone()[0])

    def get_active_seconds(self, date: str) -> float:
        cur = self._conn.execute(
            "SELECT COALESCE(SUM(duration_seconds), 0) FROM app_usage WHERE date = ?",
            (date,),
        )
        return float(cur.fetchone()[0])

    def get_presence_stats(self, date: str) -> Dict[str, Any]:
        cur = self._conn.execute(
            """
            SELECT
                COUNT(*) as total_checks,
                SUM(CASE WHEN present = 1 THEN 1 ELSE 0 END) as present_checks,
                SUM(absence_duration_seconds) as total_absence_seconds
            FROM presence_events
            WHERE date = ?
            """,
            (date,),
        )
        row = cur.fetchone()
        total, present, absence = row[0], row[1], row[2] or 0
        compliance = (present / total * 100) if total else 100.0
        return {
            "total_checks": total or 0,
            "present_checks": present or 0,
            "total_absence_seconds": round(absence, 2),
            "compliance_rate": round(compliance, 2),
        }

    def get_screenshots(self, date: str) -> List[Dict[str, Any]]:
        cur = self._conn.execute(
            """
            SELECT timestamp, file_path, file_size
            FROM screenshots
            WHERE date = ?
            ORDER BY timestamp
            """,
            (date,),
        )
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_alerts(self, date: str) -> List[Dict[str, Any]]:
        cur = self._conn.execute(
            """
            SELECT timestamp, kind, message
            FROM alerts
            WHERE date = ?
            ORDER BY timestamp
            """,
            (date,),
        )
        columns = [d[0] for d in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]

    def get_session(self, date: str) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT * FROM sessions WHERE date = ?", (date,)
        )
        row = cur.fetchone()
        if not row:
            return None
        columns = [d[0] for d in cur.description]
        return dict(zip(columns, row))
