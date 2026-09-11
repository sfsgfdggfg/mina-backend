from __future__ import annotations

from threading import Lock
from typing import Protocol

from src.core.pilot_store import SQLitePilotStore
from src.core.supplier_selection_feedback import SupplierSelectionFeedbackEvidence


class SupplierSelectionFeedbackIdempotencyConflictError(ValueError):
    pass


def _idempotency_payload(item: SupplierSelectionFeedbackEvidence) -> dict:
    return item.model_dump(mode="json", exclude={"feedback_id", "recorded_at"})


class SupplierSelectionFeedbackRepository(Protocol):
    def create(self, item: SupplierSelectionFeedbackEvidence) -> tuple[SupplierSelectionFeedbackEvidence, bool]: ...
    def find_by_entry_id(self, entry_id: str) -> SupplierSelectionFeedbackEvidence | None: ...
    def list_all(self, job_id: str | None = None) -> list[SupplierSelectionFeedbackEvidence]: ...


class InMemorySupplierSelectionFeedbackRepository:
    def __init__(self) -> None:
        self._items: dict[str, SupplierSelectionFeedbackEvidence] = {}
        self._by_entry: dict[str, str] = {}
        self._lock = Lock()

    def create(self, item: SupplierSelectionFeedbackEvidence) -> tuple[SupplierSelectionFeedbackEvidence, bool]:
        with self._lock:
            existing_id = self._by_entry.get(item.entry_id)
            if existing_id is not None:
                existing = self._items[existing_id]
                if _idempotency_payload(existing) != _idempotency_payload(item):
                    raise SupplierSelectionFeedbackIdempotencyConflictError(
                        "Selection feedback entry_id was reused with different evidence."
                    )
                return existing, False
            self._items[item.feedback_id] = item
            self._by_entry[item.entry_id] = item.feedback_id
            return item, True

    def find_by_entry_id(self, entry_id: str) -> SupplierSelectionFeedbackEvidence | None:
        feedback_id = self._by_entry.get(entry_id)
        return None if feedback_id is None else self._items.get(feedback_id)

    def list_all(self, job_id: str | None = None) -> list[SupplierSelectionFeedbackEvidence]:
        items = list(self._items.values())
        if job_id is not None:
            items = [item for item in items if item.mina_job_id == job_id]
        return sorted(items, key=lambda item: (item.recorded_at, item.feedback_id))


class SQLiteSupplierSelectionFeedbackRepository:
    NAMESPACE = "supplier_selection_feedback"
    ENTRY_INDEX_NAMESPACE = "supplier_selection_feedback_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def find_by_entry_id(self, entry_id: str) -> SupplierSelectionFeedbackEvidence | None:
        index = self.store.get(namespace=self.ENTRY_INDEX_NAMESPACE, record_key=entry_id)
        if index is None:
            return None
        payload = self.store.get(namespace=self.NAMESPACE, record_key=str(index.get("feedback_id") or ""))
        return None if payload is None else SupplierSelectionFeedbackEvidence.model_validate(payload)

    def create(self, item: SupplierSelectionFeedbackEvidence) -> tuple[SupplierSelectionFeedbackEvidence, bool]:
        existing = self.find_by_entry_id(item.entry_id)
        if existing is not None:
            if _idempotency_payload(existing) != _idempotency_payload(item):
                raise SupplierSelectionFeedbackIdempotencyConflictError(
                    "Selection feedback entry_id was reused with different evidence."
                )
            return existing, False
        self.store.insert_once(
            namespace=self.NAMESPACE, record_key=item.feedback_id,
            payload=item.model_dump(mode="json"), event_type="supplier_selection_feedback_recorded",
            entity_type="supplier_selection_feedback",
        )
        self.store.insert_once(
            namespace=self.ENTRY_INDEX_NAMESPACE, record_key=item.entry_id,
            payload={"feedback_id": item.feedback_id}, event_type="supplier_selection_feedback_indexed",
            entity_type="supplier_selection_feedback_index",
        )
        return item, True

    def list_all(self, job_id: str | None = None) -> list[SupplierSelectionFeedbackEvidence]:
        items = [
            SupplierSelectionFeedbackEvidence.model_validate(payload)
            for payload in self.store.list_all(namespace=self.NAMESPACE)
        ]
        if job_id is not None:
            items = [item for item in items if item.mina_job_id == job_id]
        return sorted(items, key=lambda item: (item.recorded_at, item.feedback_id))
