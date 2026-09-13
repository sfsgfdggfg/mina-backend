from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.air_service_availability import AirServiceAvailabilityConfirmation
from src.core.pilot_store import SQLitePilotStore


class AirServiceAvailabilityConflictError(ValueError):
    pass


def _creation_payload(item: AirServiceAvailabilityConfirmation) -> dict:
    return item.model_dump(mode="json", exclude={"confirmation_id", "confirmed_at"})


class AirServiceAvailabilityRepository(Protocol):
    def create(self, item: AirServiceAvailabilityConfirmation) -> tuple[AirServiceAvailabilityConfirmation, bool]: ...
    def get(self, confirmation_id: str) -> AirServiceAvailabilityConfirmation | None: ...
    def find_by_entry(self, entry_id: str) -> AirServiceAvailabilityConfirmation | None: ...
    def list_all(self) -> list[AirServiceAvailabilityConfirmation]: ...


class InMemoryAirServiceAvailabilityRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirServiceAvailabilityConfirmation] = {}
        self.by_entry: dict[str, str] = {}
        self._lock = Lock()

    def create(self, item):
        with self._lock:
            existing = self.find_by_entry(item.entry_id)
            if existing is not None:
                if _creation_payload(existing) != _creation_payload(item):
                    raise AirServiceAvailabilityConflictError(
                        "Air availability entry_id reused with different evidence."
                    )
                return existing, False
            self.items[item.confirmation_id] = item.model_copy(deep=True)
            self.by_entry[item.entry_id] = item.confirmation_id
            return item.model_copy(deep=True), True

    def get(self, confirmation_id):
        item = self.items.get(confirmation_id)
        return None if item is None else item.model_copy(deep=True)

    def find_by_entry(self, entry_id):
        confirmation_id = self.by_entry.get(entry_id)
        return None if confirmation_id is None else self.get(confirmation_id)

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirServiceAvailabilityRepository:
    ITEM_NS = "air_service_availability_confirmations"
    ENTRY_NS = "air_service_availability_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, item):
        existing = self.find_by_entry(item.entry_id)
        if existing is not None:
            if _creation_payload(existing) != _creation_payload(item):
                raise AirServiceAvailabilityConflictError(
                    "Air availability entry_id reused with different evidence."
                )
            return existing, False
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            if not self.store.insert_once(
                namespace=self.ITEM_NS,
                record_key=item.confirmation_id,
                payload=item.model_dump(mode="json"),
                event_type="air_service_availability_confirmation_created",
                entity_type="air_service_availability_confirmation",
            ):
                raise AirServiceAvailabilityConflictError("Air availability confirmation id collision.")
            if not self.store.insert_once(
                namespace=self.ENTRY_NS,
                record_key=item.entry_id,
                payload={"confirmation_id": item.confirmation_id},
                event_type="air_service_availability_confirmation_indexed",
                entity_type="air_service_availability_confirmation_index",
            ):
                raise AirServiceAvailabilityConflictError("Air availability entry identity collision.")
        return item.model_copy(deep=True), True
    def get(self, confirmation_id):
        payload = self.store.get(namespace=self.ITEM_NS, record_key=confirmation_id)
        return None if payload is None else AirServiceAvailabilityConfirmation.model_validate(payload)

    def find_by_entry(self, entry_id):
        payload = self.store.get(namespace=self.ENTRY_NS, record_key=entry_id)
        if payload is None:
            return None
        return self.get(str(payload.get("confirmation_id") or ""))

    def list_all(self):
        return [
            AirServiceAvailabilityConfirmation.model_validate(item)
            for item in self.store.list_all(namespace=self.ITEM_NS)
        ]
