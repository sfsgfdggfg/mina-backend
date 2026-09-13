from __future__ import annotations

from threading import Lock
from typing import Protocol

from src.core.air_rate_validity_review import AirRateValidityReview
from src.core.pilot_store import SQLitePilotStore


class AirRateValidityReviewConflictError(ValueError):
    pass


class AirRateValidityReviewRepository(Protocol):
    def create(self, review: AirRateValidityReview) -> AirRateValidityReview: ...
    def get_by_source(self, source_id: str) -> AirRateValidityReview | None: ...
    def list_all(self) -> list[AirRateValidityReview]: ...


class InMemoryAirRateValidityReviewRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirRateValidityReview] = {}
        self._lock = Lock()

    def create(self, review):
        with self._lock:
            if review.source_id in self.items:
                raise AirRateValidityReviewConflictError("Air tariff source validity is already reviewed.")
            self.items[review.source_id] = review.model_copy(deep=True)
            return review.model_copy(deep=True)

    def get_by_source(self, source_id):
        item = self.items.get(source_id)
        return None if item is None else item.model_copy(deep=True)

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirRateValidityReviewRepository:
    REVIEW_NS = "air_rate_validity_reviews"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, review):
        if not self.store.insert_once(
            namespace=self.REVIEW_NS,
            record_key=review.source_id,
            payload=review.model_dump(mode="json"),
            event_type="air_rate_validity_review_created",
            entity_type="air_rate_validity_review",
        ):
            raise AirRateValidityReviewConflictError("Air tariff source validity is already reviewed.")
        stored = self.get_by_source(review.source_id)
        if stored is None:
            raise AirRateValidityReviewConflictError("Air tariff validity review persistence failed.")
        return stored

    def get_by_source(self, source_id):
        payload = self.store.get(namespace=self.REVIEW_NS, record_key=source_id)
        return None if payload is None else AirRateValidityReview.model_validate(payload)

    def list_all(self):
        return [AirRateValidityReview.model_validate(item) for item in self.store.list_all(namespace=self.REVIEW_NS)]
