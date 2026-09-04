from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from threading import local
from typing import Any
from uuid import uuid4

from pydantic import BaseModel
from src.paths import data_path

DEFAULT_PILOT_DB_PATH = data_path("pilot", "minai_pilot.sqlite3")
PERSISTENT_STATE_NAMESPACES = (
    "mina_jobs",
    "mina_job_sequences",
    "mina_job_by_proposal",
    "mina_job_by_manual_intake",
    "mina_job_by_code",
    "mina_job_timeline_events",
    "supplier_fixed_rates",
    "supplier_fixed_rate_by_entry",
    "supplier_price_offers",
    "supplier_price_offer_by_entry",
    "supplier_price_offer_by_job_fixed_rate",
    "customer_master_profiles",
    "customer_master_by_entry",
    "customer_master_by_name",
    "supplier_master_profiles",
    "supplier_master_by_entry",
    "supplier_master_by_name",
)


class SQLiteTransactionError(RuntimeError):
    pass


class SQLiteStorageSecurityError(RuntimeError):
    pass


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

class SQLitePilotStore:
    def __init__(
        self,
        db_path: str | Path | None = None,
        *,
        run_id: str | None = None,
        retention_days: int | None = None,
    ) -> None:
        configured_path = db_path or os.getenv("MINAI_PILOT_DB_PATH")
        self.db_path = Path(
            configured_path or DEFAULT_PILOT_DB_PATH
        )

        parent_existed = self.db_path.parent.exists()
        self.db_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.run_id = run_id or str(uuid4())
        self._transaction_state = local()

        self._prepare_storage_permissions(
            parent_was_created=not parent_existed
        )

        configured_retention = (
            retention_days
            if retention_days is not None
            else int(os.getenv("MINAI_PILOT_RETENTION_DAYS", "30"))
        )
        if configured_retention < 1 or configured_retention > 365:
            raise ValueError(
                "MINAI pilot retention must be between 1 and 365 days."
            )
        self.retention_days = configured_retention

        self._initialize()
        self.purge_expired()
        self._harden_storage_permissions()

    def _prepare_storage_permissions(
        self,
        *,
        parent_was_created: bool,
    ) -> None:
        if os.name != "posix":
            return

        if parent_was_created:
            os.chmod(
                self.db_path.parent,
                0o700,
            )

        if self.db_path.is_symlink():
            raise SQLiteStorageSecurityError(
                "Pilot SQLite path must not be a symlink."
            )

        if not self.db_path.exists():
            flags = (
                os.O_CREAT
                | os.O_EXCL
                | os.O_WRONLY
            )
            try:
                descriptor = os.open(
                    self.db_path,
                    flags,
                    0o600,
                )
            except FileExistsError:
                pass
            else:
                os.close(descriptor)

        self._harden_storage_permissions()

    def _harden_storage_permissions(self) -> None:
        if os.name != "posix":
            return

        candidates = (
            self.db_path,
            Path(str(self.db_path) + "-wal"),
            Path(str(self.db_path) + "-shm"),
        )

        for candidate in candidates:
            if not candidate.exists():
                continue

            if candidate.is_symlink():
                raise SQLiteStorageSecurityError(
                    "Pilot SQLite storage files "
                    "must not be symlinks."
                )

            try:
                os.chmod(candidate, 0o600)

                actual_mode = stat.S_IMODE(
                    candidate.stat().st_mode
                )
            except FileNotFoundError as exc:
                if candidate == self.db_path:
                    raise SQLiteStorageSecurityError(
                        "Pilot SQLite database disappeared "
                        "while securing permissions."
                    ) from exc

                # SQLite WAL/SHM sidecars are transient and may
                # legitimately disappear between exists() and chmod/stat.
                continue

            if actual_mode != 0o600:
                raise SQLiteStorageSecurityError(
                    "Pilot SQLite storage permissions "
                    "could not be restricted."
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA secure_delete = ON")
        self._harden_storage_permissions()
        return connection

    @property
    def transaction_active(self) -> bool:
        return getattr(self._transaction_state, "connection", None) is not None

    @contextmanager
    def transaction(self):
        if self.transaction_active:
            raise SQLiteTransactionError(
                "Nested SQLite pilot transactions are not supported."
            )
        connection = self._connect()
        self._transaction_state.connection = connection
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            self._transaction_state.connection = None
            connection.close()
            self._harden_storage_permissions()

    @contextmanager
    def _connection_scope(self):
        transaction_connection = getattr(
            self._transaction_state,
            "connection",
            None,
        )
        if transaction_connection is not None:
            yield transaction_connection
            return
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()
            self._harden_storage_permissions()

    def _initialize(self) -> None:
        with self._connection_scope() as connection:
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
        with self._connection_scope() as connection:
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
        with self._connection_scope() as connection:
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
        with self._connection_scope() as connection:
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

    def purge_expired(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, int]:
        reference_time = now or datetime.now(timezone.utc)
        cutoff = reference_time.timestamp() - (
            self.retention_days * 24 * 60 * 60
        )
        cutoff_iso = datetime.fromtimestamp(
            cutoff,
            tz=timezone.utc,
        ).isoformat()

        with self._connection_scope() as connection:
            placeholders = ",".join("?" for _ in PERSISTENT_STATE_NAMESPACES)
            state_cursor = connection.execute(
                "DELETE FROM state_records WHERE updated_at < ? "
                f"AND namespace NOT IN ({placeholders})",
                (cutoff_iso, *PERSISTENT_STATE_NAMESPACES),
            )
            event_cursor = connection.execute(
                "DELETE FROM pilot_events WHERE created_at < ?",
                (cutoff_iso,),
            )

        deleted = {
            "state_records_deleted": state_cursor.rowcount,
            "pilot_events_deleted": event_cursor.rowcount,
        }

        if any(deleted.values()):
            with self._connection_scope() as connection:
                checkpoint = connection.execute(
                    "PRAGMA wal_checkpoint(TRUNCATE)"
                ).fetchone()
            if checkpoint is not None and checkpoint[0] != 0:
                raise RuntimeError(
                    "Pilot retention purge could not truncate SQLite WAL."
                )

        return deleted

    def get(self, *, namespace: str, record_key: str) -> Any | None:
        with self._connection_scope() as connection:
            row = connection.execute(
                "SELECT payload_json FROM state_records WHERE namespace = ? AND record_key = ?",
                (namespace, record_key),
            ).fetchone()
        return None if row is None else self._decode(row["payload_json"])

    def list_all(self, *, namespace: str) -> list[Any]:
        with self._connection_scope() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM state_records WHERE namespace = ? ORDER BY updated_at ASC, record_key ASC",
                (namespace,),
            ).fetchall()
        return [self._decode(row["payload_json"]) for row in rows]

    def exists(self, *, namespace: str, record_key: str) -> bool:
        with self._connection_scope() as connection:
            row = connection.execute(
                "SELECT 1 FROM state_records WHERE namespace = ? AND record_key = ? LIMIT 1",
                (namespace, record_key),
            ).fetchone()
        return row is not None

    def latest_event_id(
        self,
        *,
        exclude_entity_type: str | None = None,
        exclude_entity_types: tuple[str, ...] | list[str] | None = None,
    ) -> int:
        excluded = list(exclude_entity_types or ())
        if exclude_entity_type is not None:
            excluded.append(exclude_entity_type)
        excluded = sorted(set(excluded))
        with self._connection_scope() as connection:
            if not excluded:
                row = connection.execute(
                    "SELECT COALESCE(MAX(event_id), 0) AS event_id FROM pilot_events"
                ).fetchone()
            else:
                placeholders = ",".join("?" for _ in excluded)
                row = connection.execute(
                    "SELECT COALESCE(MAX(event_id), 0) AS event_id FROM pilot_events "
                    f"WHERE entity_type NOT IN ({placeholders})",
                    excluded,
                ).fetchone()
        return 0 if row is None else int(row["event_id"])

    def summarize_events_after(
        self,
        after_event_id: int,
        *,
        exclude_entity_type: str | None = None,
        exclude_entity_types: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, Any]:
        if after_event_id < 0:
            raise ValueError("after_event_id must be non-negative.")
        clauses = ["event_id > ?"]
        values: list[Any] = [after_event_id]
        excluded = list(exclude_entity_types or ())
        if exclude_entity_type is not None:
            excluded.append(exclude_entity_type)
        excluded = sorted(set(excluded))
        if excluded:
            placeholders = ",".join("?" for _ in excluded)
            clauses.append(f"entity_type NOT IN ({placeholders})")
            values.extend(excluded)
        where_sql = " WHERE " + " AND ".join(clauses)
        with self._connection_scope() as connection:
            summary = connection.execute(
                "SELECT COUNT(*) AS event_count, MIN(created_at) AS first_created_at, "
                "MAX(created_at) AS last_created_at FROM pilot_events" + where_sql,
                values,
            ).fetchone()
            grouped = connection.execute(
                "SELECT entity_type, COUNT(*) AS event_count FROM pilot_events"
                + where_sql
                + " GROUP BY entity_type ORDER BY entity_type ASC",
                values,
            ).fetchall()
        return {
            "event_count": 0 if summary is None else int(summary["event_count"]),
            "first_created_at": None if summary is None else summary["first_created_at"],
            "last_created_at": None if summary is None else summary["last_created_at"],
            "entity_type_counts": {
                str(row["entity_type"]): int(row["event_count"])
                for row in grouped
            },
        }

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
        with self._connection_scope() as connection:
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
