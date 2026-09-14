from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.air_additional_cost_evidence_repository import AirAdditionalCostEvidenceRepository
from src.core.air_cost_scope_review_repository import AirCostScopeReviewRepository
from src.core.air_fx_rate_evidence_repository import AirFxRateEvidenceRepository
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_surcharge_review_repository import AirRateSurchargeReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_rate_validity_review_repository import AirRateValidityReviewRepository
from src.core.air_rate_weight_rounding_review_repository import AirRateWeightRoundingReviewRepository
from src.core.air_reviewed_surcharge_cost_preview import (
    AirReviewedSurchargeCostPreview,
    AirReviewedSurchargeCostPreviewError,
    build_air_reviewed_surcharge_cost_preview,
)
from src.core.air_shadow_repository import AirShadowRepository


class AirCostScopeCoveragePreviewError(ValueError):
    pass


class AirCostScopeCoveragePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_preview: AirReviewedSurchargeCostPreview
    cost_scope_review_id: str
    inquiry_reference: str
    scope_classification_complete: bool
    required_categories: list[str] = Field(default_factory=list, max_length=9)
    covered_required_categories: list[str] = Field(default_factory=list, max_length=9)
    missing_required_categories: list[str] = Field(default_factory=list, max_length=9)
    not_applicable_categories: list[str] = Field(default_factory=list, max_length=9)
    unresolved_categories: list[str] = Field(default_factory=list, max_length=9)
    selected_additional_cost_categories: list[str] = Field(default_factory=list, max_length=9)
    conflicting_not_applicable_categories: list[str] = Field(default_factory=list, max_length=9)
    blockers: list[str] = Field(default_factory=list, max_length=20)
    required_flat_cost_coverage_complete: bool = False
    unsupported_cost_semantics_still_possible: bool = True
    all_in_cost: bool = False
    customer_quote_eligible: bool = False
    pricing_authority: bool = False
    runtime_authoritative: bool = False


def _normalize_inquiry(value: str) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized or len(normalized) > 300:
        raise AirCostScopeCoveragePreviewError("inquiry_reference_required")
    return normalized


def build_air_cost_scope_coverage_preview(
    *,
    review_id: str,
    candidate_id: str,
    cost_scope_review_id: str,
    inquiry_reference: str,
    actual_weight_kg,
    cargo_context: Literal["general_cargo", "special_cargo"],
    routing_context: Literal["direct", "connecting"],
    table_repository: AirRateTableReviewRepository,
    structure_repository: AirRateStructureReviewRepository,
    surcharge_repository: AirRateSurchargeReviewRepository,
    source_repository: AirShadowRepository,
    scope_repository: AirCostScopeReviewRepository,
    additional_cost_repository: AirAdditionalCostEvidenceRepository,
    validity_repository: AirRateValidityReviewRepository | None = None,
    fx_repository: AirFxRateEvidenceRepository | None = None,
    rounding_repository: AirRateWeightRoundingReviewRepository | None = None,
    volumetric_weight_kg=None,
    total_volume_cm3=None,
    via_airport: Optional[str] = None,
    shipment_count: Optional[int] = None,
    awb_count: Optional[int] = None,
    hawb_count: Optional[int] = None,
    mawb_count: Optional[int] = None,
    reference_date: Optional[date] = None,
    fx_evidence_ids: Optional[list[str]] = None,
    additional_cost_evidence_ids: Optional[list[str]] = None,
    fx_reference_at: Optional[datetime] = None,
) -> AirCostScopeCoveragePreview:
    inquiry = _normalize_inquiry(inquiry_reference)
    scope = scope_repository.get(cost_scope_review_id)
    if scope is None:
        raise AirCostScopeCoveragePreviewError("air_cost_scope_review_not_found")

    selected_fx_ids = list(fx_evidence_ids or [])
    selected_additional_ids = list(additional_cost_evidence_ids or [])
    preview_inquiry = inquiry if (selected_fx_ids or selected_additional_ids) else None
    try:
        cost_preview = build_air_reviewed_surcharge_cost_preview(
            review_id=review_id,
            candidate_id=candidate_id,
            actual_weight_kg=actual_weight_kg,
            volumetric_weight_kg=volumetric_weight_kg,
            total_volume_cm3=total_volume_cm3,
            cargo_context=cargo_context,
            routing_context=routing_context,
            via_airport=via_airport,
            shipment_count=shipment_count,
            awb_count=awb_count,
            hawb_count=hawb_count,
            mawb_count=mawb_count,
            reference_date=reference_date,
            inquiry_reference=preview_inquiry,
            fx_evidence_ids=selected_fx_ids,
            additional_cost_evidence_ids=selected_additional_ids,
            fx_reference_at=fx_reference_at,
            table_repository=table_repository,
            structure_repository=structure_repository,
            surcharge_repository=surcharge_repository,
            source_repository=source_repository,
            validity_repository=validity_repository,
            fx_repository=fx_repository,
            additional_cost_repository=additional_cost_repository,
            rounding_repository=rounding_repository,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        raise AirCostScopeCoveragePreviewError(str(exc)) from exc

    source = source_repository.get_rate_source(cost_preview.freight.source_id)
    if source is None:
        raise AirCostScopeCoveragePreviewError("air_rate_source_not_found")
    if scope.source_id != source.source_id or scope.source_sha256 != source.sha256_hex:
        raise AirCostScopeCoveragePreviewError("air_cost_scope_review_source_mismatch")
    if scope.inquiry_reference != inquiry:
        raise AirCostScopeCoveragePreviewError("air_cost_scope_review_inquiry_mismatch")

    required = sorted(scope.required_categories)
    not_applicable = sorted(scope.not_applicable_categories)
    unresolved = sorted(scope.unresolved_categories)
    selected_categories = sorted({item.cost_category for item in cost_preview.included_additional_costs})
    covered_required = sorted(set(required).intersection(selected_categories))
    missing_required = sorted(set(required).difference(selected_categories))
    conflicts = sorted(set(not_applicable).intersection(selected_categories))

    blockers: list[str] = []
    if unresolved:
        blockers.append("scope_classification_incomplete")
    blockers.extend(f"required_cost_missing:{category}" for category in missing_required)
    blockers.extend(f"selected_cost_conflicts_with_not_applicable:{category}" for category in conflicts)

    coverage_complete = (
        scope.scope_classification_complete
        and not missing_required
        and not conflicts
    )
    return AirCostScopeCoveragePreview(
        cost_preview=cost_preview,
        cost_scope_review_id=scope.review_id,
        inquiry_reference=inquiry,
        scope_classification_complete=scope.scope_classification_complete,
        required_categories=required,
        covered_required_categories=covered_required,
        missing_required_categories=missing_required,
        not_applicable_categories=not_applicable,
        unresolved_categories=unresolved,
        selected_additional_cost_categories=selected_categories,
        conflicting_not_applicable_categories=conflicts,
        blockers=blockers,
        required_flat_cost_coverage_complete=coverage_complete,
    )
