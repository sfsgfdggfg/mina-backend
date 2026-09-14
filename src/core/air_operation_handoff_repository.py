from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.air_operation_handoff import AirOperationHandoff
from src.core.pilot_store import SQLitePilotStore


class AirOperationHandoffConflictError(ValueError):
    pass


def _semantic_payload(item: AirOperationHandoff) -> dict:
    return item.model_dump(mode="json", exclude={"handoff_id", "handed_off_at"})


class AirOperationHandoffRepository(Protocol):
    def create(self, item: AirOperationHandoff) -> tuple[AirOperationHandoff, bool]: ...
    def get(self, handoff_id: str) -> AirOperationHandoff | None: ...
    def find_by_job(self, job_id: str) -> AirOperationHandoff | None: ...
    def list_all(self) -> list[AirOperationHandoff]: ...


class InMemoryAirOperationHandoffRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirOperationHandoff] = {}
        self.by_job: dict[str, str] = {}
        self._lock = Lock()

    def create(self, item):
        with self._lock:
            existing = self.find_by_job(item.job_id)
            if existing is not None:
                if _semantic_payload(existing) != _semantic_payload(item):
                    raise AirOperationHandoffConflictError(
                        "Air operation handoff job already exists with different evidence."
                    )
                return existing, False
            self.items[item.handoff_id] = item.model_copy(deep=True)
            self.by_job[item.job_id] = item.handoff_id
            return item.model_copy(deep=True), True

    def get(self, handoff_id):
        item = self.items.get(handoff_id)
        return None if item is None else item.model_copy(deep=True)

    def find_by_job(self, job_id):
        handoff_id = self.by_job.get(job_id)
        return None if handoff_id is None else self.get(handoff_id)

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirOperationHandoffRepository:
    ITEM_NS = "air_operation_handoffs"
    JOB_NS = "air_operation_handoff_by_job"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, item):
        existing = self.find_by_job(item.job_id)
        if existing is not None:
            if _semantic_payload(existing) != _semantic_payload(item):
                raise AirOperationHandoffConflictError(
                    "Air operation handoff job already exists with different evidence."
                )
            return existing, False
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            if not self.store.insert_once(
                namespace=self.ITEM_NS, record_key=item.handoff_id,
                payload=item.model_dump(mode="json"),
                event_type="air_operation_handoff_created", entity_type="air_operation_handoff",
            ):
                raise AirOperationHandoffConflictError("Air operation handoff id collision.")
            if not self.store.insert_once(
                namespace=self.JOB_NS, record_key=item.job_id,
                payload={"handoff_id": item.handoff_id},
                event_type="air_operation_handoff_indexed", entity_type="air_operation_handoff_index",
            ):
                raise AirOperationHandoffConflictError("Air operation handoff job identity collision.")
        return item.model_copy(deep=True), True

    def get(self, handoff_id):
        payload = self.store.get(namespace=self.ITEM_NS, record_key=handoff_id)
        return None if payload is None else AirOperationHandoff.model_validate(payload)

    def find_by_job(self, job_id):
        payload = self.store.get(namespace=self.JOB_NS, record_key=job_id)
        if payload is None:
            return None
        return self.get(str(payload.get("handoff_id") or ""))

    def list_all(self):
        return [AirOperationHandoff.model_validate(item) for item in self.store.list_all(namespace=self.ITEM_NS)]
