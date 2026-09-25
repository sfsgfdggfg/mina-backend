from __future__ import annotations

from typing import Protocol

from src.core.inbound_sender_review import InboundSenderReview
from src.core.pilot_store import SQLitePilotStore


class InboundSenderReviewRepository(Protocol):
    def save(self, review: InboundSenderReview) -> InboundSenderReview: ...
    def get(self, review_id: str) -> InboundSenderReview | None: ...
    def list_all(self) -> list[InboundSenderReview]: ...
    def find_by_message_hash(self, message_hash: str) -> InboundSenderReview | None: ...


class InMemoryInboundSenderReviewRepository:
    def __init__(self) -> None:
        self._items: dict[str, InboundSenderReview] = {}

    def save(self, review: InboundSenderReview) -> InboundSenderReview:
        self._items[review.review_id] = review.model_copy(deep=True)
        return review.model_copy(deep=True)

    def get(self, review_id: str) -> InboundSenderReview | None:
        item = self._items.get(review_id)
        return None if item is None else item.model_copy(deep=True)

    def list_all(self) -> list[InboundSenderReview]:
        return [item.model_copy(deep=True) for item in self._items.values()]

    def find_by_message_hash(self, message_hash: str) -> InboundSenderReview | None:
        for item in self._items.values():
            if item.message_key_sha256 == message_hash:
                return item.model_copy(deep=True)
        return None


class SQLiteInboundSenderReviewRepository:
    NAMESPACE = "inbound_sender_reviews"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def save(self, review: InboundSenderReview) -> InboundSenderReview:
        self.store.upsert(
            namespace=self.NAMESPACE,
            record_key=review.review_id,
            payload=review.model_dump(mode="json"),
            event_type="inbound_sender_review_changed",
            entity_type="inbound_sender_review",
        )
        return review

    def get(self, review_id: str) -> InboundSenderReview | None:
        raw = self.store.get(namespace=self.NAMESPACE, record_key=review_id)
        return None if raw is None else InboundSenderReview.model_validate(raw)

    def list_all(self) -> list[InboundSenderReview]:
        return [
            InboundSenderReview.model_validate(row)
            for row in self.store.list_all(namespace=self.NAMESPACE)
        ]

    def find_by_message_hash(self, message_hash: str) -> InboundSenderReview | None:
        for item in self.list_all():
            if item.message_key_sha256 == message_hash:
                return item
        return None
