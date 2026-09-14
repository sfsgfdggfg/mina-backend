from __future__ import annotations

from datetime import datetime, timezone

from src.core.air_shadow_repository import AirShadowRepository
from src.core.air_unsupported_cost_semantics_review import AirUnsupportedCostSemanticsReview
from src.core.air_unsupported_cost_semantics_review_repository import (
    AirUnsupportedCostSemanticsReviewConflictError,
    AirUnsupportedCostSemanticsReviewRepository,
)


class AirUnsupportedCostSemanticsReviewNotFoundError(ValueError):
    pass


class AirUnsupportedCostSemanticsReviewTransitionError(ValueError):
    pass


def record_air_unsupported_cost_semantics_review(
    *, source_id: str, entry_id: str, inquiry_reference: str, requirements: list[dict],
    review_note: str, reviewed_by: str, source_repository: AirShadowRepository,
    repository: AirUnsupportedCostSemanticsReviewRepository, reviewed_at: datetime | None = None,
):
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirUnsupportedCostSemanticsReviewNotFoundError(f"Air rate source not found: {source_id}")
    try:
        item = AirUnsupportedCostSemanticsReview(
            entry_id=entry_id, inquiry_reference=inquiry_reference,
            source_id=source.source_id, source_sha256=source.sha256_hex,
            requirements=requirements, review_note=review_note, reviewed_by=reviewed_by,
            reviewed_at=reviewed_at or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise AirUnsupportedCostSemanticsReviewTransitionError(str(exc)) from exc
    try:
        return repository.create(item)
    except AirUnsupportedCostSemanticsReviewConflictError as exc:
        raise AirUnsupportedCostSemanticsReviewTransitionError(str(exc)) from exc


def build_air_unsupported_cost_semantics_review_view(*, repository):
    items = sorted(repository.list_all(), key=lambda item: (item.reviewed_at, item.review_id), reverse=True)
    reviews = []
    for item in items:
        payload = item.model_dump(mode="json")
        payload.update({
            "semantics_classification_complete": item.semantics_classification_complete,
            "applicable_unresolved_semantics": item.applicable_unresolved_semantics,
            "unresolved_semantics": item.unresolved_semantics,
            "unsupported_semantics_cleared": item.unsupported_semantics_cleared,
        })
        reviews.append(payload)
    return {
        "reviews": reviews,
        "cost_completeness_authority_enabled": False,
        "pricing_authority_enabled": False,
        "customer_quote_eligible": False,
        "runtime_authoritative": False,
    }
