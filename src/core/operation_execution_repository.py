from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.operation_execution import OperationException, OperationExecutionSnapshot
from src.core.pilot_store import SQLitePilotStore


class OperationExecutionConflictError(ValueError):
    pass


class OperationExecutionRepository(Protocol):
    def get_snapshot(self, job_id: str) -> OperationExecutionSnapshot | None: ...
    def save_snapshot(self, snapshot: OperationExecutionSnapshot) -> OperationExecutionSnapshot: ...
    def create_exception(self, exception: OperationException) -> tuple[OperationException, bool]: ...
    def get_exception(self, exception_id: str) -> OperationException | None: ...
    def find_exception_by_entry_id(self, entry_id: str) -> OperationException | None: ...
    def save_exception(self, exception: OperationException) -> OperationException: ...
    def list_exceptions(self, job_id: str | None = None) -> list[OperationException]: ...


def _exception_idempotency_payload(item: OperationException) -> dict:
    return item.model_dump(
        mode="json",
        exclude={"exception_id", "created_at", "updated_at", "updated_by"},
        exclude_computed_fields=True,
    )


class InMemoryOperationExecutionRepository:
    def __init__(self) -> None:
        self.snapshots: dict[str, OperationExecutionSnapshot] = {}
        self.exceptions: dict[str, OperationException] = {}
        self.exception_by_entry: dict[str, str] = {}
        self._lock = Lock()

    def get_snapshot(self, job_id): return self.snapshots.get(job_id)
    def save_snapshot(self, snapshot):
        self.snapshots[snapshot.job_id] = snapshot
        return snapshot
    def create_exception(self, exception):
        with self._lock:
            existing_id = self.exception_by_entry.get(exception.entry_id)
            if existing_id:
                existing = self.exceptions[existing_id]
                if _exception_idempotency_payload(existing) != _exception_idempotency_payload(exception):
                    raise OperationExecutionConflictError(
                        "Operation exception entry_id reused with different incident data."
                    )
                return existing, False
            self.exceptions[exception.exception_id] = exception
            self.exception_by_entry[exception.entry_id] = exception.exception_id
            return exception, True
    def get_exception(self, exception_id): return self.exceptions.get(exception_id)
    def find_exception_by_entry_id(self, entry_id):
        key = self.exception_by_entry.get(entry_id)
        return None if key is None else self.exceptions.get(key)
    def save_exception(self, exception):
        if exception.exception_id not in self.exceptions:
            raise KeyError(exception.exception_id)
        self.exceptions[exception.exception_id] = exception
        self.exception_by_entry[exception.entry_id] = exception.exception_id
        return exception
    def list_exceptions(self, job_id=None):
        items = list(self.exceptions.values())
        if job_id is not None:
            items = [item for item in items if item.job_id == job_id]
        return sorted(items, key=lambda item: (item.reported_at, item.exception_id))


class SQLiteOperationExecutionRepository:
    SNAPSHOT_NS = "operation_execution_snapshots"
    EXCEPTION_NS = "operation_exceptions"
    EXCEPTION_ENTRY_NS = "operation_exception_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get_snapshot(self, job_id):
        payload = self.store.get(namespace=self.SNAPSHOT_NS, record_key=job_id)
        return None if payload is None else OperationExecutionSnapshot.model_validate(payload)

    def save_snapshot(self, snapshot):
        self.store.upsert(
            namespace=self.SNAPSHOT_NS, record_key=snapshot.job_id,
            payload=snapshot.model_dump(mode="json"),
            event_type="operation_execution_snapshot_saved", entity_type="operation_execution_snapshot",
        )
        return self.get_snapshot(snapshot.job_id)

    def create_exception(self, exception):
        transaction_scope = (
            nullcontext() if self.store.transaction_active else self.store.transaction()
        )
        with transaction_scope:
            existing = self.find_exception_by_entry_id(exception.entry_id)
            if existing is not None:
                if _exception_idempotency_payload(existing) != _exception_idempotency_payload(exception):
                    raise OperationExecutionConflictError(
                        "Operation exception entry_id reused with different incident data."
                    )
                return existing, False
            if not self.store.insert_once(
                namespace=self.EXCEPTION_NS, record_key=exception.exception_id,
                payload=exception.model_dump(mode="json"), event_type="operation_exception_created",
                entity_type="operation_exception",
            ):
                raise RuntimeError("Operation exception identifier collision.")
            if not self.store.insert_once(
                namespace=self.EXCEPTION_ENTRY_NS, record_key=exception.entry_id,
                payload={"record_id": exception.exception_id}, event_type="operation_exception_indexed",
                entity_type="operation_exception_index",
            ):
                raise RuntimeError("Operation exception entry identity collision.")
            return exception, True

    def get_exception(self, exception_id):
        payload = self.store.get(namespace=self.EXCEPTION_NS, record_key=exception_id)
        return None if payload is None else OperationException.model_validate(payload)

    def find_exception_by_entry_id(self, entry_id):
        payload = self.store.get(namespace=self.EXCEPTION_ENTRY_NS, record_key=entry_id)
        if payload is None:
            return None
        return self.get_exception(str(payload.get("record_id") or ""))

    def save_exception(self, exception):
        if self.get_exception(exception.exception_id) is None:
            raise KeyError(exception.exception_id)
        self.store.upsert(
            namespace=self.EXCEPTION_NS, record_key=exception.exception_id,
            payload=exception.model_dump(mode="json"), event_type="operation_exception_saved",
            entity_type="operation_exception",
        )
        return self.get_exception(exception.exception_id)

    def list_exceptions(self, job_id=None):
        items = [
            OperationException.model_validate(payload)
            for payload in self.store.list_all(namespace=self.EXCEPTION_NS)
        ]
        if job_id is not None:
            items = [item for item in items if item.job_id == job_id]
        return sorted(items, key=lambda item: (item.reported_at, item.exception_id))
