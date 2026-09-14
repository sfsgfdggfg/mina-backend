from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.air_cost_scope_review import AirCostScopeReview
from src.core.pilot_store import SQLitePilotStore


class AirCostScopeReviewConflictError(ValueError):
    pass


def _creation_payload(item: AirCostScopeReview) -> dict:
    return item.model_dump(mode="json", exclude={"review_id", "reviewed_at"})


class AirCostScopeReviewRepository(Protocol):
    def create(self, item: AirCostScopeReview) -> tuple[AirCostScopeReview, bool]: ...
    def get(self, review_id: str) -> AirCostScopeReview | None: ...
    def find_by_entry(self, entry_id: str) -> AirCostScopeReview | None: ...
    def list_all(self) -> list[AirCostScopeReview]: ...


class InMemoryAirCostScopeReviewRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirCostScopeReview] = {}
        self.by_entry: dict[str, str] = {}
        self._lock = Lock()

    def create(self, item):
        with self._lock:
            existing = self.find_by_entry(item.entry_id)
            if existing is not None:
                if _creation_payload(existing) != _creation_payload(item):
                    raise AirCostScopeReviewConflictError(
                        "Air cost-scope review entry_id reused with different evidence."
                    )
                return existing, False
            self.items[item.review_id] = item.model_copy(deep=True)
            self.by_entry[item.entry_id] = item.review_id
            return item.model_copy(deep=True), True

    def get(self, review_id):
        item = self.items.get(review_id)
        return None if item is None else item.model_copy(deep=True)

    def find_by_entry(self, entry_id):
        review_id = self.by_entry.get(entry_id)
        return None if review_id is None else self.get(review_id)

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirCostScopeReviewRepository:
    ITEM_NS = "air_cost_scope_reviews"
    ENTRY_NS = "air_cost_scope_review_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, item):
        existing = self.find_by_entry(item.entry_id)
        if existing is not None:
            if _creation_payload(existing) != _creation_payload(item):
                raise AirCostScopeReviewConflictError(
                    "Air cost-scope review entry_id reused with different evidence."
                )
            return existing, False
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            if not self.store.insert_once(
                namespace=self.ITEM_NS,
                record_key=item.review_id,
                payload=item.model_dump(mode="json"),
                event_type="air_cost_scope_review_created",
                entity_type="air_cost_scope_review",
            ):
                raise AirCostScopeReviewConflictError("Air cost-scope review id collision.")
            if not self.store.insert_once(
                namespace=self.ENTRY_NS,
                record_key=item.entry_id,
                payload={"review_id": item.review_id},
                event_type="air_cost_scope_review_indexed",
                entity_type="air_cost_scope_review_index",
            ):
                raise AirCostScopeReviewConflictError("Air cost-scope review entry identity collision.")
        return item.model_copy(deep=True), True

    def get(self, review_id):
        payload = self.store.get(namespace=self.ITEM_NS, record_key=review_id)
        return None if payload is None else AirCostScopeReview.model_validate(payload)

    def find_by_entry(self, entry_id):
        payload = self.store.get(namespace=self.ENTRY_NS, record_key=entry_id)
        if payload is None:
            return None
        return self.get(str(payload.get("review_id") or ""))

    def list_all(self):
        return [
            AirCostScopeReview.model_validate(item)
            for item in self.store.list_all(namespace=self.ITEM_NS)
        ]
