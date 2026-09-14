from __future__ import annotations

from datetime import datetime, timezone

from src.core.air_cost_scope_review import AirCostScopeReview
from src.core.air_cost_scope_review_repository import (
    AirCostScopeReviewConflictError,
    AirCostScopeReviewRepository,
)
from src.core.air_shadow_repository import AirShadowRepository


class AirCostScopeReviewNotFoundError(ValueError):
    pass


class AirCostScopeReviewTransitionError(ValueError):
    pass


def record_air_cost_scope_review(
    *,
    source_id: str,
    entry_id: str,
    inquiry_reference: str,
    requirements: list,
    review_note: str,
    reviewed_by: str,
    source_repository: AirShadowRepository,
    repository: AirCostScopeReviewRepository,
    reviewed_at: datetime | None = None,
) -> tuple[AirCostScopeReview, bool]:
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirCostScopeReviewNotFoundError(f"Air rate source not found: {source_id}")
    try:
        item = AirCostScopeReview(
            entry_id=entry_id,
            inquiry_reference=inquiry_reference,
            source_id=source.source_id,
            source_sha256=source.sha256_hex,
            requirements=requirements,
            review_note=review_note,
            reviewed_by=reviewed_by,
            reviewed_at=reviewed_at or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise AirCostScopeReviewTransitionError(str(exc)) from exc
    try:
        return repository.create(item)
    except AirCostScopeReviewConflictError as exc:
        raise AirCostScopeReviewTransitionError(str(exc)) from exc


def _serialize(item: AirCostScopeReview) -> dict:
    payload = item.model_dump(mode="json")
    payload.update({
        "scope_classification_complete": item.scope_classification_complete,
        "required_categories": item.required_categories,
        "not_applicable_categories": item.not_applicable_categories,
        "unresolved_categories": item.unresolved_categories,
        "runtime_authoritative": False,
        "pricing_authority": False,
        "cost_completeness_authority": False,
    })
    return payload


def build_air_cost_scope_review_view(*, repository: AirCostScopeReviewRepository) -> dict:
    items = sorted(
        repository.list_all(),
        key=lambda item: (item.reviewed_at, item.review_id),
        reverse=True,
    )
    return {
        "reviews": [_serialize(item) for item in items],
        "runtime_authoritative": False,
        "pricing_authority_enabled": False,
        "cost_completeness_authority_enabled": False,
        "cost_preview_consumption_enabled": False,
        "customer_quote_eligible": False,
    }
