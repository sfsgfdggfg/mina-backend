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


class AirReviewedSurchargeExclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_id: str
    surcharge_code: str
    currency: str
    reason: Literal[
        "flat_quantity_scope_unresolved",
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
    excluded_surcharges: list[AirReviewedSurchargeExclusion] = Field(default_factory=list, max_length=100)
    reviewed_per_kg_surcharge_total: Decimal
    base_plus_reviewed_per_kg_surcharges: Decimal
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

    surcharge_review = surcharge_repository.find_by_source(freight.source_id)
    if surcharge_review is None:
        raise AirReviewedSurchargeCostPreviewError("air_rate_surcharge_review_required")
    if surcharge_review.status != "completed":
        raise AirReviewedSurchargeCostPreviewError("air_rate_surcharge_review_must_be_completed")
    source = source_repository.get_rate_source(freight.source_id)
    if source is None:
        raise AirReviewedSurchargeCostPreviewError("air_rate_source_not_found")

    included: list[AirReviewedSurchargeComponent] = []
    excluded: list[AirReviewedSurchargeExclusion] = []
    total = Decimal("0")

    for candidate in surcharge_review.candidates:
        if candidate.status != "confirmed":
            continue
        if candidate.basis == "flat":
            excluded.append(AirReviewedSurchargeExclusion(
                candidate_id=candidate.candidate_id,
                surcharge_code=candidate.surcharge_code,
                currency=candidate.currency,
                reason="flat_quantity_scope_unresolved",
            ))
            continue
        if candidate.currency != freight.currency:
            excluded.append(AirReviewedSurchargeExclusion(
                candidate_id=candidate.candidate_id,
                surcharge_code=candidate.surcharge_code,
                currency=candidate.currency,
                reason="currency_mismatch_no_fx",
            ))
            continue
        if candidate.application_basis is None or candidate.applicability_scope is None:
            raise AirReviewedSurchargeCostPreviewError("applicable_per_kg_surcharge_review_incomplete")

        if candidate.applicability_scope == "destination_specific":
            if not freight.destination_code:
                raise AirReviewedSurchargeCostPreviewError("destination_code_required_for_specific_surcharge")
            if candidate.applicability_destination_code != freight.destination_code:
                excluded.append(AirReviewedSurchargeExclusion(
                    candidate_id=candidate.candidate_id,
                    surcharge_code=candidate.surcharge_code,
                    currency=candidate.currency,
                    reason="destination_not_applicable",
                ))
                continue

        if candidate.cargo_applicability is None or candidate.routing_applicability is None:
            raise AirReviewedSurchargeCostPreviewError("applicable_per_kg_surcharge_operational_conditions_incomplete")
        if not _cargo_matches(candidate, source_cargo_scope=source.cargo_scope, cargo_context=cargo_context):
            excluded.append(AirReviewedSurchargeExclusion(
                candidate_id=candidate.candidate_id,
                surcharge_code=candidate.surcharge_code,
                currency=candidate.currency,
                reason="cargo_not_applicable",
            ))
            continue
        if candidate.routing_applicability == "via_airport" and routing_context == "connecting" and normalized_via is None:
            raise AirReviewedSurchargeCostPreviewError("via_airport_context_required_for_reviewed_surcharge")
        if not _routing_matches(candidate, routing_context=routing_context, via_airport=normalized_via):
            excluded.append(AirReviewedSurchargeExclusion(
                candidate_id=candidate.candidate_id,
                surcharge_code=candidate.surcharge_code,
                currency=candidate.currency,
                reason="routing_not_applicable",
            ))
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
        total += cost

    return AirReviewedSurchargeCostPreview(
        freight=freight,
        cargo_context=cargo_context,
        routing_context=routing_context,
        via_airport=normalized_via,
        included_surcharges=included,
        excluded_surcharges=excluded,
        reviewed_per_kg_surcharge_total=total,
        base_plus_reviewed_per_kg_surcharges=freight.recommended_base_freight + total,
    )
