"""P2-16.4 regressions for pilot persistence and housekeeping."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src import paths
from src.core.operational_shift_close_receipt import OperationalShiftCloseReceipt
from src.core.operational_shift_open_acceptance_receipt import (
    OperationalShiftOpenAcceptanceReceipt,
)
from src.core.operational_work_assignment import OperationalWorkAssignment
from src.core.pilot_store import (
    STATE_RECORD_SCHEMA_VERSION,
    SQLitePilotStore,
    SQLiteStateSchemaError,
    SQLiteStorageSecurityError,
)
from src.core.sqlite_repositories import (
    SQLiteOperationalShiftCloseReceiptRepository,
    SQLiteOperationalShiftOpenAcceptanceReceiptRepository,
    SQLiteOperationalWorkAssignmentRepository,
)
from src.simulation.physical_temp import physical_temporary_directory


NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)

def _expect_storage_error(failures: list[str], env: dict[str, str], label: str) -> None:
    with patch.dict(os.environ, env, clear=True):
        try:
            SQLitePilotStore()
        except SQLiteStorageSecurityError:
            return
        failures.append(label)


def _check_pilot_db_path_guards(failures: list[str]) -> None:
    _expect_storage_error(
        failures,
        {"MINAI_PILOT_MODE": "true"},
        "pilot mode accepted a missing MINAI_PILOT_DB_PATH",
    )
    _expect_storage_error(
        failures,
        {"MINAI_PILOT_MODE": "true", "MINAI_PILOT_DB_PATH": "relative/pilot.sqlite3"},
        "pilot mode accepted a relative SQLite path",
    )
    _expect_storage_error(
        failures,
        {
            "MINAI_PILOT_MODE": "true",
            "MINAI_PILOT_DB_PATH": str(paths.REPO_ROOT / "data" / "pilot" / "unsafe.sqlite3"),
        },
        "pilot mode accepted a repository-contained SQLite path",
    )

    with physical_temporary_directory() as temporary:
        safe_path = Path(temporary) / "pilot.sqlite3"
        with patch.dict(
            os.environ,
            {"MINAI_PILOT_MODE": "true", "MINAI_PILOT_DB_PATH": str(safe_path)},
            clear=True,
        ):
            store = SQLitePilotStore()
        if store.db_path != safe_path or not safe_path.exists():
            failures.append("pilot mode rejected an absolute external SQLite path")

def _check_legacy_state_schema(failures: list[str]) -> None:
    with physical_temporary_directory() as temporary:
        db_path = Path(temporary) / "legacy.sqlite3"
        legacy_payload = {"legacy": True, "value": 7}
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                """CREATE TABLE state_records (
                    namespace TEXT NOT NULL,
                    record_key TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (namespace, record_key)
                )"""
            )
            connection.execute(
                "INSERT INTO state_records VALUES (?, ?, ?, ?)",
                ("compat", "legacy", json.dumps(legacy_payload), NOW.isoformat()),
            )

        store = SQLitePilotStore(db_path, retention_days=365)
        if store.get(namespace="compat", record_key="legacy") != legacy_payload:
            failures.append("pre-version state record did not survive schema migration")

        store.upsert(
            namespace="compat", record_key="current", payload={"current": True},
            event_type="compat_saved", entity_type="compat",
        )
        with sqlite3.connect(db_path) as connection:
            versions = dict(
                connection.execute(
                    "SELECT record_key, schema_version FROM state_records WHERE namespace='compat'"
                ).fetchall()
            )
        if versions.get("legacy") != 0 or versions.get("current") != STATE_RECORD_SCHEMA_VERSION:
            failures.append("legacy/current state schema versions were not distinguished")

        with sqlite3.connect(db_path) as connection:
            connection.execute(
                "UPDATE state_records SET schema_version=? WHERE namespace='compat' AND record_key='current'",
                (STATE_RECORD_SCHEMA_VERSION + 1,),
            )
        try:
            store.get(namespace="compat", record_key="current")
        except SQLiteStateSchemaError:
            pass
        else:
            failures.append("unsupported future state schema did not fail closed")

def _check_retention_classes(failures: list[str]) -> None:
    with physical_temporary_directory() as temporary:
        store = SQLitePilotStore(Path(temporary) / "retention.sqlite3", retention_days=1)
        assignments = SQLiteOperationalWorkAssignmentRepository(store)
        close_receipts = SQLiteOperationalShiftCloseReceiptRepository(store)
        open_receipts = SQLiteOperationalShiftOpenAcceptanceReceiptRepository(store)

        assignment = OperationalWorkAssignment(
            work_id="quote:housekeeping",
            assigned_to="Operator One",
            assigned_by="Manager One",
            assigned_at=NOW,
            work_state_sha256="a" * 64,
        )
        assignments.save(assignment)
        close_receipt = OperationalShiftCloseReceipt(
            receipt_id="shift-close-" + "b" * 32,
            attested_by="Operator One",
            attested_at=NOW,
            readiness_generated_at=NOW,
            pending_work_count=0,
            critical_pending_count=0,
            active_assignment_count=0,
            expired_assignment_count=0,
            incomplete_handoff_count=0,
            critical_uncovered_count=0,
            close_state_sha256="c" * 64,
        )
        close_receipts.save_if_absent(close_receipt)
        open_receipt = OperationalShiftOpenAcceptanceReceipt(
            receipt_id="shift-open-" + "d" * 32,
            accepted_by="Operator Two",
            accepted_at=NOW,
            reconciliation_generated_at=NOW,
            source_close_receipt_id=close_receipt.receipt_id,
            pending_work_count=0,
            critical_pending_count=0,
            incomplete_handoff_count=0,
            critical_uncovered_count=0,
            acceptance_state_sha256="e" * 64,
        )
        open_receipts.save_if_absent(open_receipt)

        store.upsert(
            namespace="temporary_housekeeping_state", record_key="old",
            payload={"temporary": True}, event_type="temporary_saved",
            entity_type="temporary_housekeeping",
        )
        result = store.purge_expired(now=NOW + timedelta(days=2))
        if assignments.get(assignment.work_id) is None or not assignments.list_history():
            failures.append("work assignment state/history did not survive ordinary retention")
        if not close_receipts.list_all() or not open_receipts.list_all():
            failures.append("shift continuity receipts did not survive ordinary retention")
        if store.get(namespace="temporary_housekeeping_state", record_key="old") is not None:
            failures.append("temporary state incorrectly survived ordinary retention")
        if any(
            event["entity_type"] == "temporary_housekeeping"
            for event in store.list_events()
        ):
            failures.append("temporary audit event incorrectly survived ordinary retention")
        if result["state_records_deleted"] < 1 or result["pilot_events_deleted"] < 1:
            failures.append("ordinary retention did not delete transient state/evidence")


def _check_timestamp_source_and_repo_housekeeping(failures: list[str]) -> None:
    source_roots = (paths.REPO_ROOT / "src" / "core", paths.REPO_ROOT / "src" / "workflow")
    for root in source_roots:
        for source in root.rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            if "datetime.utcnow()" in text and source.name != "reporting_read_model.py":
                failures.append(f"naive UTC timestamp source remains: {source.relative_to(paths.REPO_ROOT)}")

    tracked_backup_dir = paths.REPO_ROOT / "data" / "backups"
    if tracked_backup_dir.exists() and any(tracked_backup_dir.iterdir()):
        failures.append("repository backup artifacts remain after housekeeping")
    ignored = (paths.REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    for required in ("data/backups/", "*.sqlite3", "*.sqlite", "*.db"):
        if required not in ignored.splitlines():
            failures.append(f"gitignore lacks storage housekeeping rule: {required}")


def evaluate_persistence_housekeeping_regressions() -> dict[str, object]:
    failures: list[str] = []
    _check_pilot_db_path_guards(failures)
    _check_legacy_state_schema(failures)
    _check_retention_classes(failures)
    _check_timestamp_source_and_repo_housekeeping(failures)
    return {"name": "P2-16.4 persistence housekeeping", "passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_persistence_housekeeping_regressions()
    print(result)
    raise SystemExit(0 if result["passed"] else 1)
