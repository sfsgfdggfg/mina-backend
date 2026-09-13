from __future__ import annotations

from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.air_freight_calculation_preview import (
    AirFreightCalculationPreview,
    AirFreightCalculationPreviewError,
    build_air_freight_calculation_preview,
)
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_surcharge_review_repository import AirRateSurchargeReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_shadow_repository import AirShadowRepository


class AirReviewedSurchargeCostPreviewError(ValueError):
    pass


class AirReviewedSurchargeComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    surcharge_code: str
    currency: str
    rate_per_kg: Decimal
    application_basis: Literal["actual_weight", "chargeable_weight", "pivot_billed_weight"]
    applied_weight_kg: Decimal
    surcharge_cost: Decimal


class AirReviewedFlatSurchargeComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    surcharge_code: str
    currency: str
    amount_per_unit: Decimal
    quantity_basis: Literal["per_shipment", "per_awb", "per_hawb", "per_mawb"]
    applied_count: int = Field(ge=1, le=1000)
    surcharge_cost: Decimal


class AirReviewedSurchargeExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    surcharge_code: str
    currency: str
    reason: Literal[
        "flat_review_incomplete",
        "flat_quantity_basis_unreviewed",
        "currency_mismatch_no_fx",
        "destination_not_applicable",
        "cargo_not_applicable",
        "routing_not_applicable",
    ]


class AirReviewedSurchargeCostPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    freight: AirFreightCalculationPreview
    cargo_context: Literal["general_cargo", "special_cargo"]
    routing_context: Literal["direct", "connecting"]
    via_airport: Optional[str] = None
    included_surcharges: list[AirReviewedSurchargeComponent] = Field(default_factory=list, max_length=100)
    included_flat_surcharges: list[AirReviewedFlatSurchargeComponent] = Field(default_factory=list, max_length=100)
    excluded_surcharges: list[AirReviewedSurchargeExclusion] = Field(default_factory=list, max_length=100)
    reviewed_per_kg_surcharge_total: Decimal
    reviewed_flat_surcharge_total: Decimal
    base_plus_reviewed_per_kg_surcharges: Decimal
    base_plus_reviewed_surcharges: Decimal
    all_in_cost: bool = False
    flat_surcharges_included: bool = False
    fx_applied: bool = False
    surcharge_rounding_applied: bool = False
    capacity_confirmed: bool = False
    tariff_validity_confirmed: bool = False
    runtime_authoritative: bool = False
    customer_quote_eligible: bool = False


def _normalize_via(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    normalized = value.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise AirReviewedSurchargeCostPreviewError("via_airport_must_be_three_letter_iata")
    return normalized


def _cargo_matches(candidate, *, source_cargo_scope: str, cargo_context: str) -> bool:
    if candidate.cargo_applicability == "general_cargo":
        return cargo_context == "general_cargo"
    if candidate.cargo_applicability == "special_cargo":
        return cargo_context == "special_cargo"
    if candidate.cargo_applicability == "source_scope":
        if source_cargo_scope == "mixed":
            return cargo_context in {"general_cargo", "special_cargo"}
        return cargo_context == source_cargo_scope
    return False


def _routing_matches(candidate, *, routing_context: str, via_airport: Optional[str]) -> bool:
    if candidate.routing_applicability == "all_source_routings":
        return True
    if candidate.routing_applicability == "direct_only":
        return routing_context == "direct"
    if candidate.routing_applicability == "connecting_only":
        return routing_context == "connecting"
    if candidate.routing_applicability == "via_airport":
        return routing_context == "connecting" and via_airport == candidate.routing_via_airport
    return False


def build_air_reviewed_surcharge_cost_preview(
    *,
    review_id: str,
    candidate_id: str,
    actual_weight_kg,
    cargo_context: Literal["general_cargo", "special_cargo"],
    routing_context: Literal["direct", "connecting"],
    table_repository: AirRateTableReviewRepository,
    structure_repository: AirRateStructureReviewRepository,
    surcharge_repository: AirRateSurchargeReviewRepository,
    source_repository: AirShadowRepository,
    volumetric_weight_kg=None,
    total_volume_cm3=None,
    via_airport: Optional[str] = None,
    shipment_count: Optional[int] = None,
    awb_count: Optional[int] = None,
    hawb_count: Optional[int] = None,
    mawb_count: Optional[int] = None,
) -> AirReviewedSurchargeCostPreview:
    try:
        freight = build_air_freight_calculation_preview(
            review_id=review_id,
            candidate_id=candidate_id,
            actual_weight_kg=actual_weight_kg,
            volumetric_weight_kg=volumetric_weight_kg,
            total_volume_cm3=total_volume_cm3,
            table_repository=table_repository,
            structure_repository=structure_repository,
        )
    except AirFreightCalculationPreviewError as exc:
        raise AirReviewedSurchargeCostPreviewError(str(exc)) from exc

    normalized_via = _normalize_via(via_airport)
    if routing_context == "direct" and normalized_via is not None:
        raise AirReviewedSurchargeCostPreviewError("direct_routing_cannot_have_via_airport")

    flat_counts = {
        "per_shipment": shipment_count,
        "per_awb": awb_count,
        "per_hawb": hawb_count,
        "per_mawb": mawb_count,
    }
    for basis, count in flat_counts.items():
        if count is None:
            continue
        if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 1000:
            raise AirReviewedSurchargeCostPreviewError(f"invalid_flat_surcharge_count:{basis}")

    surcharge_review = surcharge_repository.find_by_source(freight.source_id)
    if surcharge_review is None:
        raise AirReviewedSurchargeCostPreviewError("air_rate_surcharge_review_required")
    if surcharge_review.status != "completed":
        raise AirReviewedSurchargeCostPreviewError("air_rate_surcharge_review_must_be_completed")
    source = source_repository.get_rate_source(freight.source_id)
    if source is None:
        raise AirReviewedSurchargeCostPreviewError("air_rate_source_not_found")

    included: list[AirReviewedSurchargeComponent] = []
    included_flat: list[AirReviewedFlatSurchargeComponent] = []
    excluded: list[AirReviewedSurchargeExclusion] = []
    per_kg_total = Decimal("0")
    flat_total = Decimal("0")

    def exclude(candidate, reason: str) -> None:
        excluded.append(AirReviewedSurchargeExclusion(
            candidate_id=candidate.candidate_id,
            surcharge_code=candidate.surcharge_code,
            currency=candidate.currency,
            reason=reason,
        ))

    def context_matches(candidate) -> bool:
        if candidate.applicability_scope == "destination_specific":
            if not freight.destination_code:
                raise AirReviewedSurchargeCostPreviewError("destination_code_required_for_specific_surcharge")
            if candidate.applicability_destination_code != freight.destination_code:
                exclude(candidate, "destination_not_applicable")
                return False
        if not _cargo_matches(candidate, source_cargo_scope=source.cargo_scope, cargo_context=cargo_context):
            exclude(candidate, "cargo_not_applicable")
            return False
        if candidate.routing_applicability == "via_airport" and routing_context == "connecting" and normalized_via is None:
            raise AirReviewedSurchargeCostPreviewError("via_airport_context_required_for_reviewed_surcharge")
        if not _routing_matches(candidate, routing_context=routing_context, via_airport=normalized_via):
            exclude(candidate, "routing_not_applicable")
            return False
        return True

    for candidate in surcharge_review.candidates:
        if candidate.status != "confirmed":
            continue
        if candidate.currency != freight.currency:
            exclude(candidate, "currency_mismatch_no_fx")
            continue

        if candidate.basis == "flat":
            if (
                candidate.application_basis != "flat"
                or candidate.applicability_scope is None
                or candidate.cargo_applicability is None
                or candidate.routing_applicability is None
            ):
                exclude(candidate, "flat_review_incomplete")
                continue
            if not context_matches(candidate):
                continue
            if candidate.flat_quantity_basis is None:
                exclude(candidate, "flat_quantity_basis_unreviewed")
                continue
            count = flat_counts[candidate.flat_quantity_basis]
            if count is None:
                raise AirReviewedSurchargeCostPreviewError(
                    f"flat_surcharge_count_required:{candidate.flat_quantity_basis}"
                )
            cost = candidate.amount * count
            included_flat.append(AirReviewedFlatSurchargeComponent(
                candidate_id=candidate.candidate_id,
                surcharge_code=candidate.surcharge_code,
                currency=candidate.currency,
                amount_per_unit=candidate.amount,
                quantity_basis=candidate.flat_quantity_basis,
                applied_count=count,
                surcharge_cost=cost,
            ))
            flat_total += cost
            continue

        if candidate.application_basis is None or candidate.applicability_scope is None:
            raise AirReviewedSurchargeCostPreviewError("applicable_per_kg_surcharge_review_incomplete")
        if candidate.cargo_applicability is None or candidate.routing_applicability is None:
            raise AirReviewedSurchargeCostPreviewError("applicable_per_kg_surcharge_operational_conditions_incomplete")
        if not context_matches(candidate):
            continue

        if candidate.application_basis == "actual_weight":
            applied_weight = freight.actual_weight_kg
        elif candidate.application_basis == "chargeable_weight":
            applied_weight = freight.chargeable_weight_kg
        elif candidate.application_basis == "pivot_billed_weight":
            applied_weight = freight.recommended_billed_weight_kg
        else:
            raise AirReviewedSurchargeCostPreviewError("unsupported_per_kg_surcharge_application_basis")

        cost = candidate.amount * applied_weight
        included.append(AirReviewedSurchargeComponent(
            candidate_id=candidate.candidate_id,
            surcharge_code=candidate.surcharge_code,
            currency=candidate.currency,
            rate_per_kg=candidate.amount,
            application_basis=candidate.application_basis,
            applied_weight_kg=applied_weight,
            surcharge_cost=cost,
        ))
        per_kg_total += cost

    return AirReviewedSurchargeCostPreview(
        freight=freight,
        cargo_context=cargo_context,
        routing_context=routing_context,
        via_airport=normalized_via,
        included_surcharges=included,
        included_flat_surcharges=included_flat,
        excluded_surcharges=excluded,
        reviewed_per_kg_surcharge_total=per_kg_total,
        reviewed_flat_surcharge_total=flat_total,
        base_plus_reviewed_per_kg_surcharges=freight.recommended_base_freight + per_kg_total,
        base_plus_reviewed_surcharges=freight.recommended_base_freight + per_kg_total + flat_total,
        flat_surcharges_included=bool(included_flat),
    )
