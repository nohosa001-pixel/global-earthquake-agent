"""
SQLite Persistent State Store for Trade-Enabling Seismic Hazard Oracle
Persists:
- Registered alert webhooks
- Dispatched warning alert history
- Security Gate audit trail & circuit breaker state
"""

import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional


class OracleStateStore:
    """Thread-safe SQLite store for oracle alerts, webhooks, and security gate state."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            db_path = os.path.join(data_dir, "seismic_oracle.db")
        elif db_path != ":memory:":
            parent = os.path.dirname(os.path.abspath(db_path))
            if parent:
                os.makedirs(parent, exist_ok=True)

        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS webhooks (
                    url TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT NOT NULL,
                    trade_action TEXT NOT NULL,
                    severity_score REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    is_approved INTEGER NOT NULL,
                    risk_score REAL NOT NULL,
                    verdict TEXT NOT NULL,
                    details_json TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS circuit_breaker_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    active INTEGER NOT NULL DEFAULT 0,
                    reason TEXT NOT NULL DEFAULT '',
                    tripped_at TEXT
                )
                """
            )
            cur.execute(
                "INSERT OR IGNORE INTO circuit_breaker_state (id, active, reason, tripped_at) VALUES (1, 0, '', NULL)"
            )
            self._conn.commit()

    # --- Webhooks ---
    def add_webhook(self, url: str) -> List[str]:
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO webhooks (url) VALUES (?)", (url,))
            self._conn.commit()
            rows = self._conn.execute("SELECT url FROM webhooks ORDER BY created_at ASC").fetchall()
            return [r["url"] for r in rows]

    def list_webhooks(self) -> List[str]:
        with self._lock:
            rows = self._conn.execute("SELECT url FROM webhooks ORDER BY created_at ASC").fetchall()
            return [r["url"] for r in rows]

    # --- Alerts ---
    def save_alert(self, alert: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO alert_history (asset_id, trade_action, severity_score, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    alert["asset_id"],
                    alert["trade_action"],
                    float(alert["severity_score"]),
                    json.dumps(alert, ensure_ascii=False),
                    alert["timestamp"],
                ),
            )
            self._conn.commit()

    def list_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM alert_history ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [json.loads(r["payload_json"]) for r in rows]

    # --- Security Gate Audit & Circuit Breaker ---
    def save_audit(self, record: Dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO audit_logs (audit_id, timestamp, action_type, is_approved, risk_score, verdict, details_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["audit_id"],
                    record["timestamp"],
                    record["action_type"],
                    1 if record["is_approved"] else 0,
                    float(record["risk_score"]),
                    record["verdict"],
                    json.dumps(record.get("details", {}), ensure_ascii=False),
                ),
            )
            self._conn.commit()

    def list_audits(self, limit: int = 12) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT audit_id, timestamp, action_type, is_approved, risk_score, verdict, details_json
                FROM audit_logs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "audit_id": r["audit_id"],
                    "timestamp": r["timestamp"],
                    "action_type": r["action_type"],
                    "is_approved": bool(r["is_approved"]),
                    "risk_score": r["risk_score"],
                    "verdict": r["verdict"],
                    "details": json.loads(r["details_json"]),
                }
                for r in rows
            ]

    def set_circuit_breaker(self, active: bool, reason: str, tripped_at: Optional[str]) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE circuit_breaker_state SET active = ?, reason = ?, tripped_at = ? WHERE id = 1",
                (1 if active else 0, reason, tripped_at),
            )
            self._conn.commit()

    def get_circuit_breaker(self) -> Dict[str, Any]:
        with self._lock:
            row = self._conn.execute(
                "SELECT active, reason, tripped_at FROM circuit_breaker_state WHERE id = 1"
            ).fetchone()
            return {
                "active": bool(row["active"]) if row else False,
                "reason": row["reason"] if row else "",
                "tripped_at": row["tripped_at"] if row else None,
            }
