from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.air_additional_cost_evidence_repository import AirAdditionalCostEvidenceRepository
from src.core.air_cost_scope_coverage_preview import (
    AirCostScopeCoveragePreview,
    AirCostScopeCoveragePreviewError,
    build_air_cost_scope_coverage_preview,
)
from src.core.air_cost_scope_review_repository import AirCostScopeReviewRepository
from src.core.air_fx_rate_evidence_repository import AirFxRateEvidenceRepository
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_surcharge_review_repository import AirRateSurchargeReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_rate_validity_review_repository import AirRateValidityReviewRepository
from src.core.air_rate_weight_rounding_review_repository import AirRateWeightRoundingReviewRepository
from src.core.air_shadow_repository import AirShadowRepository
from src.core.air_unsupported_cost_semantics_review_repository import (
    AirUnsupportedCostSemanticsReviewRepository,
)


class AirCostCompletenessPreviewError(ValueError):
    pass


class AirCostCompletenessSurchargeBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    surcharge_code: str
    currency: str
    reason: str


class AirCostCompletenessPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coverage_preview: AirCostScopeCoveragePreview
    unsupported_cost_semantics_review_id: str
    inquiry_reference: str
    semantics_classification_complete: bool
    unsupported_semantics_cleared: bool
    unresolved_semantics: list[str] = Field(default_factory=list, max_length=5)
    applicable_unresolved_semantics: list[str] = Field(default_factory=list, max_length=5)
    blocking_surcharge_exclusions: list[AirCostCompletenessSurchargeBlocker] = Field(default_factory=list, max_length=100)
    non_applicable_surcharge_exclusions: list[AirCostCompletenessSurchargeBlocker] = Field(default_factory=list, max_length=100)
    airline_weight_rounding_reviewed: bool = False
    blockers: list[str] = Field(default_factory=list, max_length=120)
    cost_completeness_confirmed: bool = False
    confirmed_cost_basis_amount: Decimal | None = None
    confirmed_cost_basis_currency: str | None = None
    customer_quote_eligible: bool = False
    pricing_authority: bool = False
    quote_send_authority: bool = False
    booking_authority: bool = False
    outbound_authority: bool = False
    runtime_authoritative: bool = False
    all_in_cost: bool = False


_NON_APPLICABLE_EXCLUSION_REASONS = {
    "destination_not_applicable",
    "cargo_not_applicable",
    "routing_not_applicable",
}


def build_air_cost_completeness_preview(
    *,
    review_id: str,
    candidate_id: str,
    cost_scope_review_id: str,
    unsupported_cost_semantics_review_id: str,
    inquiry_reference: str,
    actual_weight_kg,
    cargo_context: Literal["general_cargo", "special_cargo"],
    routing_context: Literal["direct", "connecting"],
    table_repository: AirRateTableReviewRepository,
    structure_repository: AirRateStructureReviewRepository,
    surcharge_repository: AirRateSurchargeReviewRepository,
    source_repository: AirShadowRepository,
    scope_repository: AirCostScopeReviewRepository,
    unsupported_semantics_repository: AirUnsupportedCostSemanticsReviewRepository,
    additional_cost_repository: AirAdditionalCostEvidenceRepository,
    rounding_repository: AirRateWeightRoundingReviewRepository,
    validity_repository: AirRateValidityReviewRepository | None = None,
    fx_repository: AirFxRateEvidenceRepository | None = None,
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
) -> AirCostCompletenessPreview:
    try:
        coverage = build_air_cost_scope_coverage_preview(
            review_id=review_id,
            candidate_id=candidate_id,
            cost_scope_review_id=cost_scope_review_id,
            inquiry_reference=inquiry_reference,
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
            fx_evidence_ids=fx_evidence_ids,
            additional_cost_evidence_ids=additional_cost_evidence_ids,
            fx_reference_at=fx_reference_at,
            table_repository=table_repository,
            structure_repository=structure_repository,
            surcharge_repository=surcharge_repository,
            source_repository=source_repository,
            scope_repository=scope_repository,
            additional_cost_repository=additional_cost_repository,
            validity_repository=validity_repository,
            fx_repository=fx_repository,
            rounding_repository=rounding_repository,
        )
    except AirCostScopeCoveragePreviewError as exc:
        raise AirCostCompletenessPreviewError(str(exc)) from exc

    semantics = unsupported_semantics_repository.get(unsupported_cost_semantics_review_id)
    if semantics is None:
        raise AirCostCompletenessPreviewError("air_unsupported_cost_semantics_review_not_found")

    source = source_repository.get_rate_source(coverage.cost_preview.freight.source_id)
    if source is None:
        raise AirCostCompletenessPreviewError("air_rate_source_not_found")
    if semantics.source_id != source.source_id or semantics.source_sha256 != source.sha256_hex:
        raise AirCostCompletenessPreviewError("air_unsupported_cost_semantics_review_source_mismatch")
    if semantics.inquiry_reference != coverage.inquiry_reference:
        raise AirCostCompletenessPreviewError("air_unsupported_cost_semantics_review_inquiry_mismatch")

    blocking_surcharges = []
    non_applicable_surcharges = []
    for item in coverage.cost_preview.excluded_surcharges:
        payload = AirCostCompletenessSurchargeBlocker(
            candidate_id=item.candidate_id,
            surcharge_code=item.surcharge_code,
            currency=item.currency,
            reason=item.reason,
        )
        if item.reason in _NON_APPLICABLE_EXCLUSION_REASONS:
            non_applicable_surcharges.append(payload)
        else:
            blocking_surcharges.append(payload)

    rounding_reviewed = coverage.cost_preview.freight.rounding_review_id is not None
    blockers = list(coverage.blockers)
    if not semantics.semantics_classification_complete:
        blockers.append("unsupported_cost_semantics_classification_incomplete")
    blockers.extend(
        f"unsupported_cost_semantic_applicable_unresolved:{semantic}"
        for semantic in semantics.applicable_unresolved_semantics
    )
    blockers.extend(
        f"surcharge_cost_unresolved:{item.candidate_id}:{item.reason}"
        for item in blocking_surcharges
    )
    if not rounding_reviewed:
        blockers.append("airline_weight_rounding_unreviewed")

    confirmed = (
        coverage.required_flat_cost_coverage_complete
        and semantics.unsupported_semantics_cleared
        and not blocking_surcharges
        and rounding_reviewed
    )
    return AirCostCompletenessPreview(
        coverage_preview=coverage,
        unsupported_cost_semantics_review_id=semantics.review_id,
        inquiry_reference=coverage.inquiry_reference,
        semantics_classification_complete=semantics.semantics_classification_complete,
        unsupported_semantics_cleared=semantics.unsupported_semantics_cleared,
        unresolved_semantics=sorted(semantics.unresolved_semantics),
        applicable_unresolved_semantics=sorted(semantics.applicable_unresolved_semantics),
        blocking_surcharge_exclusions=blocking_surcharges,
        non_applicable_surcharge_exclusions=non_applicable_surcharges,
        airline_weight_rounding_reviewed=rounding_reviewed,
        blockers=blockers,
        cost_completeness_confirmed=confirmed,
        confirmed_cost_basis_amount=(
            coverage.cost_preview.base_plus_reviewed_surcharges_and_additional_costs
            if confirmed else None
        ),
        confirmed_cost_basis_currency=(coverage.cost_preview.freight.currency if confirmed else None),
    )
