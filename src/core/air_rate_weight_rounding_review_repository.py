from __future__ import annotations

from threading import Lock
from typing import Protocol

from src.core.air_rate_weight_rounding_review import AirRateWeightRoundingReview
from src.core.pilot_store import SQLitePilotStore


class AirRateWeightRoundingReviewConflictError(ValueError):
    pass


class AirRateWeightRoundingReviewRepository(Protocol):
    def create(self, review: AirRateWeightRoundingReview) -> AirRateWeightRoundingReview: ...
    def get_by_source(self, source_id: str) -> AirRateWeightRoundingReview | None: ...
    def list_all(self) -> list[AirRateWeightRoundingReview]: ...


class InMemoryAirRateWeightRoundingReviewRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirRateWeightRoundingReview] = {}
        self._lock = Lock()

    def create(self, review):
        with self._lock:
            if review.source_id in self.items:
                raise AirRateWeightRoundingReviewConflictError(
                    "Air tariff source weight rounding is already reviewed."
                )
            self.items[review.source_id] = review.model_copy(deep=True)
            return review.model_copy(deep=True)

    def get_by_source(self, source_id):
        item = self.items.get(source_id)
        return None if item is None else item.model_copy(deep=True)

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirRateWeightRoundingReviewRepository:
    REVIEW_NS = "air_rate_weight_rounding_reviews"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, review):
        if not self.store.insert_once(
            namespace=self.REVIEW_NS,
            record_key=review.source_id,
            payload=review.model_dump(mode="json"),
            event_type="air_rate_weight_rounding_review_created",
            entity_type="air_rate_weight_rounding_review",
        ):
            raise AirRateWeightRoundingReviewConflictError(
                "Air tariff source weight rounding is already reviewed."
            )
        stored = self.get_by_source(review.source_id)
        if stored is None:
            raise AirRateWeightRoundingReviewConflictError(
                "Air weight-rounding review persistence failed."
            )
        return stored

    def get_by_source(self, source_id):
        payload = self.store.get(namespace=self.REVIEW_NS, record_key=source_id)
        return None if payload is None else AirRateWeightRoundingReview.model_validate(payload)

    def list_all(self):
        return [
            AirRateWeightRoundingReview.model_validate(item)
            for item in self.store.list_all(namespace=self.REVIEW_NS)
        ]
