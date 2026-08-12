from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

DEFAULT_PILOT_DB_PATH = Path("data/pilot/minai_pilot.sqlite3")

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class SQLitePilotStore:
    def __init__(self, db_path: str | Path | None = None, *, run_id: str | None = None) -> None:
        configured_path = db_path or os.getenv("MINAI_PILOT_DB_PATH")
        self.db_path = Path(configured_path or DEFAULT_PILOT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_id = run_id or str(uuid4())
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS state_records (
                    namespace TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, record_key)
                );

                CREATE TABLE IF NOT EXISTS pilot_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_pilot_events_entity
                    ON pilot_events(entity_type, entity_id);
                CREATE INDEX IF NOT EXISTS idx_pilot_events_run
                    ON pilot_events(run_id, event_id);
            """)

    @staticmethod
    def _encode(payload: Any) -> str:
        def default(value: Any):
            if isinstance(value, BaseModel):
                return value.model_dump(
                    mode="json",
                    exclude_computed_fields=True,
                )
            if isinstance(value, (datetime, date)):
                return value.isoformat()
            if isinstance(value, Path):
                return str(value)
            raise TypeError(
                f"Unsupported pilot evidence value: {type(value).__name__}"
            )

        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=default,
        )

    @staticmethod
    def _decode(payload_json: str) -> Any:
        return json.loads(payload_json)

    def upsert(self, *, namespace: str, record_key: str, payload: Any, event_type: str, entity_type: str) -> None:
        payload_json = self._encode(payload)
        timestamp = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO state_records(namespace, record_key, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(namespace, record_key)
                DO UPDATE SET payload_json = excluded.payload_json, updated_at = excluded.updated_at""",
                (namespace, record_key, payload_json, timestamp),
            )
            connection.execute(
                """INSERT INTO pilot_events(run_id, event_type, entity_type, entity_id, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (self.run_id, event_type, entity_type, record_key, payload_json, timestamp),
            )

    def record_event(
        self,
        *,
        event_type: str,
        entity_type: str,
        entity_id: str,
        payload: Any,
    ) -> None:
        payload_json = self._encode(payload)
        timestamp = utc_now_iso()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO pilot_events(run_id, event_type, entity_type, entity_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self.run_id,
                    event_type,
                    entity_type,
                    entity_id,
                    payload_json,
                    timestamp,
                ),
            )

    def insert_once(self, *, namespace: str, record_key: str, payload: Any, event_type: str, entity_type: str) -> bool:
        payload_json = self._encode(payload)
        timestamp = utc_now_iso()
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO state_records(namespace, record_key, payload_json, updated_at)
                VALUES (?, ?, ?, ?)""",
                (namespace, record_key, payload_json, timestamp),
            )
            inserted = cursor.rowcount == 1
            if inserted:
                connection.execute(
                    """INSERT INTO pilot_events(run_id, event_type, entity_type, entity_id, payload_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)""",
                    (self.run_id, event_type, entity_type, record_key, payload_json, timestamp),
                )
        return inserted

    def get(self, *, namespace: str, record_key: str) -> Any | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM state_records WHERE namespace = ? AND record_key = ?",
                (namespace, record_key),
            ).fetchone()
        return None if row is None else self._decode(row["payload_json"])

    def list_all(self, *, namespace: str) -> list[Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM state_records WHERE namespace = ? ORDER BY updated_at ASC, record_key ASC",
                (namespace,),
            ).fetchall()
        return [self._decode(row["payload_json"]) for row in rows]

    def exists(self, *, namespace: str, record_key: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM state_records WHERE namespace = ? AND record_key = ? LIMIT 1",
                (namespace, record_key),
            ).fetchone()
        return row is not None

    def list_events(self, *, entity_type: str | None = None, entity_id: str | None = None) -> list[dict[str, Any]]:
        clauses = []
        values = []
        if entity_type is not None:
            clauses.append("entity_type = ?")
            values.append(entity_type)
        if entity_id is not None:
            clauses.append("entity_id = ?")
            values.append(entity_id)
        where_sql = "" if not clauses else " WHERE " + " AND ".join(clauses)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT event_id, run_id, event_type, entity_type, entity_id, payload_json, created_at
                FROM pilot_events""" + where_sql + " ORDER BY event_id ASC",
                values,
            ).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "run_id": row["run_id"],
                "event_type": row["event_type"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "payload": self._decode(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]
