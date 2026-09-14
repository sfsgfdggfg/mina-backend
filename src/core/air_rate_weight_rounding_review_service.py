from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.core.air_rate_weight_rounding_review import AirRateWeightRoundingReview
from src.core.air_rate_weight_rounding_review_repository import (
    AirRateWeightRoundingReviewConflictError,
    AirRateWeightRoundingReviewRepository,
)
from src.core.air_shadow_repository import AirShadowRepository


class AirRateWeightRoundingReviewNotFoundError(ValueError):
    pass


class AirRateWeightRoundingReviewTransitionError(ValueError):
    pass


def review_air_rate_weight_rounding(
    *,
    source_id: str,
    rounding_mode: str,
    increment_kg: Decimal | None,
    review_note: str,
    reviewed_by: str,
    source_repository: AirShadowRepository,
    repository: AirRateWeightRoundingReviewRepository,
    reviewed_at: datetime | None = None,
) -> AirRateWeightRoundingReview:
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirRateWeightRoundingReviewNotFoundError(
            f"Air rate source not found: {source_id}"
        )
    if repository.get_by_source(source_id) is not None:
        raise AirRateWeightRoundingReviewTransitionError(
            "Air tariff source weight rounding is already reviewed."
        )
    try:
        review = AirRateWeightRoundingReview(
            source_id=source.source_id,
            source_sha256=source.sha256_hex,
            rounding_mode=rounding_mode,
            increment_kg=increment_kg,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at or datetime.now(timezone.utc),
            review_note=review_note,
        )
    except ValueError as exc:
        raise AirRateWeightRoundingReviewTransitionError(str(exc)) from exc
    try:
        return repository.create(review)
    except AirRateWeightRoundingReviewConflictError as exc:
        raise AirRateWeightRoundingReviewTransitionError(str(exc)) from exc


def build_air_rate_weight_rounding_review_view(
    *, repository: AirRateWeightRoundingReviewRepository,
) -> dict:
    reviews = sorted(
        repository.list_all(),
        key=lambda item: (item.reviewed_at, item.review_id),
        reverse=True,
    )
    return {
        "reviews": [
            {
                **item.model_dump(mode="json"),
                "runtime_authoritative": False,
                "customer_pricing_authority_enabled": False,
                "booking_authority_enabled": False,
            }
            for item in reviews
        ],
        "freight_preview_consumption_enabled": True,
        "customer_pricing_authority_enabled": False,
        "booking_authority_enabled": False,
    }
