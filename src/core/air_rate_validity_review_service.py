from __future__ import annotations

from datetime import date, datetime, timezone

from src.core.air_rate_validity_review import AirRateValidityReview
from src.core.air_rate_validity_review_repository import (
    AirRateValidityReviewConflictError,
    AirRateValidityReviewRepository,
)
from src.core.air_shadow_repository import AirShadowRepository


class AirRateValidityReviewNotFoundError(ValueError):
    pass


class AirRateValidityReviewTransitionError(ValueError):
    pass


def review_air_rate_validity(
    *,
    source_id: str,
    valid_from: date,
    valid_to: date,
    review_note: str,
    reviewed_by: str,
    source_repository: AirShadowRepository,
    repository: AirRateValidityReviewRepository,
    reviewed_at: datetime | None = None,
) -> AirRateValidityReview:
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirRateValidityReviewNotFoundError(f"Air rate source not found: {source_id}")
    note = " ".join(str(review_note or "").strip().split())
    if not note:
        raise AirRateValidityReviewTransitionError("Air tariff validity review note is required.")
    if valid_to < valid_from:
        raise AirRateValidityReviewTransitionError("Air tariff validity valid_to cannot precede valid_from.")
    if source.valid_from is not None and source.valid_from != valid_from:
        raise AirRateValidityReviewTransitionError("Reviewed valid_from conflicts with immutable source metadata.")
    if source.valid_to is not None and source.valid_to != valid_to:
        raise AirRateValidityReviewTransitionError("Reviewed valid_to conflicts with immutable source metadata.")
    if repository.get_by_source(source_id) is not None:
        raise AirRateValidityReviewTransitionError("Air tariff source validity is already reviewed.")
    review = AirRateValidityReview(
        source_id=source.source_id,
        source_sha256=source.sha256_hex,
        valid_from=valid_from,
        valid_to=valid_to,
        reviewed_by=reviewed_by,
        reviewed_at=reviewed_at or datetime.now(timezone.utc),
        review_note=note,
    )
    try:
        return repository.create(review)
    except AirRateValidityReviewConflictError as exc:
        raise AirRateValidityReviewTransitionError(str(exc)) from exc


def build_air_rate_validity_review_view(*, repository: AirRateValidityReviewRepository) -> dict:
    reviews = sorted(repository.list_all(), key=lambda item: (item.reviewed_at, item.review_id), reverse=True)
    return {
        "reviews": [
            {
                **item.model_dump(mode="json"),
                "runtime_authoritative": False,
                "capacity_confirmed": False,
                "schedule_confirmed": False,
                "pricing_authority_enabled": False,
            }
            for item in reviews
        ],
        "pricing_authority_enabled": False,
        "capacity_authority_enabled": False,
        "schedule_authority_enabled": False,
    }
