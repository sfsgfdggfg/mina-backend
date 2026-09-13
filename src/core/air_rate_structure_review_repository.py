from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.air_rate_structure_review import AirRateStructureReview
from src.core.pilot_store import SQLitePilotStore


class AirRateStructureReviewConflictError(ValueError):
    pass


class AirRateStructureReviewRepository(Protocol):
    def create(self, review: AirRateStructureReview) -> tuple[AirRateStructureReview, bool]: ...
    def get(self, review_id: str) -> AirRateStructureReview | None: ...
    def find_by_source(self, source_id: str) -> AirRateStructureReview | None: ...
    def save(self, review: AirRateStructureReview) -> AirRateStructureReview: ...
    def list_all(self) -> list[AirRateStructureReview]: ...


class InMemoryAirRateStructureReviewRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirRateStructureReview] = {}
        self.by_source: dict[str, str] = {}
        self._lock = Lock()

    def create(self, review):
        with self._lock:
            existing = self.find_by_source(review.source_id)
            if existing is not None:
                if existing.source_sha256 != review.source_sha256 or existing.extractor_version != review.extractor_version:
                    raise AirRateStructureReviewConflictError("Air rate source already has a different structure review.")
                return existing, False
            self.items[review.review_id] = review.model_copy(deep=True)
            self.by_source[review.source_id] = review.review_id
            return review.model_copy(deep=True), True

    def get(self, review_id):
        item = self.items.get(review_id)
        return None if item is None else item.model_copy(deep=True)

    def find_by_source(self, source_id):
        review_id = self.by_source.get(source_id)
        return None if review_id is None else self.get(review_id)

    def save(self, review):
        with self._lock:
            if review.review_id not in self.items:
                raise KeyError(review.review_id)
            self.items[review.review_id] = review.model_copy(deep=True)
            return review.model_copy(deep=True)

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirRateStructureReviewRepository:
    REVIEW_NS = "air_rate_structure_reviews"
    SOURCE_NS = "air_rate_structure_review_by_source"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, review):
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            existing = self.find_by_source(review.source_id)
            if existing is not None:
                if existing.source_sha256 != review.source_sha256 or existing.extractor_version != review.extractor_version:
                    raise AirRateStructureReviewConflictError("Air rate source already has a different structure review.")
                return existing, False
            if not self.store.insert_once(
                namespace=self.REVIEW_NS,
                record_key=review.review_id,
                payload=review.model_dump(mode="json"),
                event_type="air_rate_structure_review_created",
                entity_type="air_rate_structure_review",
            ):
                raise AirRateStructureReviewConflictError("Air rate structure review identifier collision.")
            if not self.store.insert_once(
                namespace=self.SOURCE_NS,
                record_key=review.source_id,
                payload={"record_id": review.review_id},
                event_type="air_rate_structure_review_indexed",
                entity_type="air_rate_structure_review_index",
            ):
                raise AirRateStructureReviewConflictError("Air rate structure source identity collision.")
            return review, True

    def get(self, review_id):
        payload = self.store.get(namespace=self.REVIEW_NS, record_key=review_id)
        return None if payload is None else AirRateStructureReview.model_validate(payload)

    def find_by_source(self, source_id):
        payload = self.store.get(namespace=self.SOURCE_NS, record_key=source_id)
        return None if payload is None else self.get(str(payload.get("record_id") or ""))

    def save(self, review):
        if self.get(review.review_id) is None:
            raise KeyError(review.review_id)
        self.store.upsert(
            namespace=self.REVIEW_NS,
            record_key=review.review_id,
            payload=review.model_dump(mode="json"),
            event_type="air_rate_structure_review_saved",
            entity_type="air_rate_structure_review",
        )
        stored = self.get(review.review_id)
        if stored is None:
            raise AirRateStructureReviewConflictError("Air rate structure review persistence failed.")
        return stored

    def list_all(self):
        return [
            AirRateStructureReview.model_validate(item)
            for item in self.store.list_all(namespace=self.REVIEW_NS)
        ]
