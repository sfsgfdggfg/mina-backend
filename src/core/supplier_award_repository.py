from __future__ import annotations

from threading import Lock

from src.core.pilot_store import SQLitePilotStore
from src.core.supplier_award import SupplierAwardSelection


class InMemorySupplierAwardRepository:
    def __init__(self) -> None:
        self._items: dict[str, SupplierAwardSelection] = {}
        self._lock = Lock()

    def append(self, item: SupplierAwardSelection) -> SupplierAwardSelection:
        with self._lock:
            if item.selection_id in self._items:
                raise ValueError("Supplier award selection identifier collision.")
            self._items[item.selection_id] = item
        return item

    def list_for_job(self, job_id: str) -> list[SupplierAwardSelection]:
        return sorted(
            (item for item in self._items.values() if item.job_id == job_id),
            key=lambda item: (item.selected_at, item.selection_id),
        )

    def current_for_job(self, job_id: str) -> SupplierAwardSelection | None:
        items = self.list_for_job(job_id)
        return items[-1] if items else None


class SQLiteSupplierAwardRepository:
    NAMESPACE = "approved_job_supplier_awards"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def append(self, item: SupplierAwardSelection) -> SupplierAwardSelection:
        created = self.store.insert_once(
            namespace=self.NAMESPACE, record_key=item.selection_id,
            payload=item.model_dump(mode="json"),
            event_type="approved_job_supplier_award_selected",
            entity_type="approved_job_supplier_award",
        )
        if not created:
            raise ValueError("Supplier award selection identifier collision.")
        return item

    def list_for_job(self, job_id: str) -> list[SupplierAwardSelection]:
        return sorted(
            (
                SupplierAwardSelection.model_validate(payload)
                for payload in self.store.list_all(namespace=self.NAMESPACE)
                if payload.get("job_id") == job_id
            ),
            key=lambda item: (item.selected_at, item.selection_id),
        )

    def current_for_job(self, job_id: str) -> SupplierAwardSelection | None:
        items = self.list_for_job(job_id)
        return items[-1] if items else None
