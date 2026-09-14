from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.air_additional_cost_evidence import AirAdditionalCostEvidence
from src.core.pilot_store import SQLitePilotStore


class AirAdditionalCostEvidenceConflictError(ValueError):
    pass


def _creation_payload(item: AirAdditionalCostEvidence) -> dict:
    return item.model_dump(mode="json", exclude={"evidence_id", "recorded_at"})


class AirAdditionalCostEvidenceRepository(Protocol):
    def create(self, item: AirAdditionalCostEvidence) -> tuple[AirAdditionalCostEvidence, bool]: ...
    def get(self, evidence_id: str) -> AirAdditionalCostEvidence | None: ...
    def find_by_entry(self, entry_id: str) -> AirAdditionalCostEvidence | None: ...
    def list_all(self) -> list[AirAdditionalCostEvidence]: ...


class InMemoryAirAdditionalCostEvidenceRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirAdditionalCostEvidence] = {}
        self.by_entry: dict[str, str] = {}
        self._lock = Lock()

    def create(self, item):
        with self._lock:
            existing = self.find_by_entry(item.entry_id)
            if existing is not None:
                if _creation_payload(existing) != _creation_payload(item):
                    raise AirAdditionalCostEvidenceConflictError(
                        "Air additional-cost evidence entry_id reused with different evidence."
                    )
                return existing, False
            self.items[item.evidence_id] = item.model_copy(deep=True)
            self.by_entry[item.entry_id] = item.evidence_id
            return item.model_copy(deep=True), True

    def get(self, evidence_id):
        item = self.items.get(evidence_id)
        return None if item is None else item.model_copy(deep=True)

    def find_by_entry(self, entry_id):
        evidence_id = self.by_entry.get(entry_id)
        return None if evidence_id is None else self.get(evidence_id)

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirAdditionalCostEvidenceRepository:
    ITEM_NS = "air_additional_cost_evidence"
    ENTRY_NS = "air_additional_cost_evidence_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, item):
        existing = self.find_by_entry(item.entry_id)
        if existing is not None:
            if _creation_payload(existing) != _creation_payload(item):
                raise AirAdditionalCostEvidenceConflictError(
                    "Air additional-cost evidence entry_id reused with different evidence."
                )
            return existing, False
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            if not self.store.insert_once(
                namespace=self.ITEM_NS,
                record_key=item.evidence_id,
                payload=item.model_dump(mode="json"),
                event_type="air_additional_cost_evidence_created",
                entity_type="air_additional_cost_evidence",
            ):
                raise AirAdditionalCostEvidenceConflictError(
                    "Air additional-cost evidence id collision."
                )
            if not self.store.insert_once(
                namespace=self.ENTRY_NS,
                record_key=item.entry_id,
                payload={"evidence_id": item.evidence_id},
                event_type="air_additional_cost_evidence_indexed",
                entity_type="air_additional_cost_evidence_index",
            ):
                raise AirAdditionalCostEvidenceConflictError(
                    "Air additional-cost evidence entry identity collision."
                )
        return item.model_copy(deep=True), True

    def get(self, evidence_id):
        payload = self.store.get(namespace=self.ITEM_NS, record_key=evidence_id)
        return None if payload is None else AirAdditionalCostEvidence.model_validate(payload)

    def find_by_entry(self, entry_id):
        payload = self.store.get(namespace=self.ENTRY_NS, record_key=entry_id)
        if payload is None:
            return None
        return self.get(str(payload.get("evidence_id") or ""))

    def list_all(self):
        return [
            AirAdditionalCostEvidence.model_validate(item)
            for item in self.store.list_all(namespace=self.ITEM_NS)
        ]
