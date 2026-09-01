from __future__ import annotations

from typing import Protocol

from src.core.attachment_interpretation_review import AttachmentInterpretationReview


class AttachmentInterpretationReviewRepository(Protocol):
    def save(self, review: AttachmentInterpretationReview) -> AttachmentInterpretationReview: ...
    def get(self, review_id: str) -> AttachmentInterpretationReview | None: ...
    def list_all(self) -> list[AttachmentInterpretationReview]: ...
    def find_by_source_fingerprint(self, fingerprint: str) -> AttachmentInterpretationReview | None: ...
    def find_by_message_key(self, message_key: str) -> AttachmentInterpretationReview | None: ...


class InMemoryAttachmentInterpretationReviewRepository:
    def __init__(self) -> None:
        self._reviews: dict[str, AttachmentInterpretationReview] = {}

    def save(self, review: AttachmentInterpretationReview) -> AttachmentInterpretationReview:
        stored = review.model_copy(deep=True)
        self._reviews[review.review_id] = stored
        return stored.model_copy(deep=True)

    def get(self, review_id: str) -> AttachmentInterpretationReview | None:
        review = self._reviews.get(review_id)
        return None if review is None else review.model_copy(deep=True)

    def list_all(self) -> list[AttachmentInterpretationReview]:
        return [item.model_copy(deep=True) for item in self._reviews.values()]

    def find_by_source_fingerprint(self, fingerprint: str) -> AttachmentInterpretationReview | None:
        for review in self._reviews.values():
            if review.source_fingerprint_sha256 == fingerprint:
                return review.model_copy(deep=True)
        return None

    def find_by_message_key(self, message_key: str) -> AttachmentInterpretationReview | None:
        for review in self._reviews.values():
            if review.source_message_key == message_key:
                return review.model_copy(deep=True)
        return None
