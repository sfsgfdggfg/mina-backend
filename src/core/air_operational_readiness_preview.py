from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.air_additional_cost_evidence_repository import AirAdditionalCostEvidenceRepository
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
from src.core.air_service_availability_repository import AirServiceAvailabilityRepository
from src.core.air_shadow_repository import AirShadowRepository


class AirOperationalReadinessPreviewError(ValueError):
    pass


AirOperationalBlocker = Literal[
    "availability_evidence_missing",
    "capacity_unavailable",
    "schedule_not_confirmed",
]


class AirOperationalReadinessPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_preview: AirReviewedSurchargeCostPreview
    inquiry_reference: str
    service_date: date
    availability_evidence_found: bool
    availability_confirmation_id: Optional[str] = None
    capacity_status: Optional[Literal["available", "unavailable"]] = None
    schedule_status: Optional[Literal["confirmed", "not_confirmed"]] = None
    flight_reference: Optional[str] = None
    operational_blockers: list[AirOperationalBlocker] = Field(default_factory=list, max_length=3)
    tariff_validity_confirmed: bool
    fx_applied: bool
    fx_evidence_ids_used: list[str] = Field(default_factory=list, max_length=20)
    capacity_confirmed: bool
    schedule_confirmed: bool
    operational_evidence_complete: bool
    partial_cost_only: bool = True
    customer_quote_ready: bool = False
    booking_ready: bool = False
    outbound_authority: bool = False
    runtime_authoritative: bool = False


def _normalized_inquiry_reference(value: str) -> str:
    normalized = " ".join(str(value or "").strip().split())
    if not normalized or len(normalized) > 300:
        raise AirOperationalReadinessPreviewError("inquiry_reference_required")
    return normalized


def build_air_operational_readiness_preview(
    *,
    review_id: str,
    candidate_id: str,
    inquiry_reference: str,
    service_date: date,
    actual_weight_kg,
    cargo_context: Literal["general_cargo", "special_cargo"],
    routing_context: Literal["direct", "connecting"],
    table_repository: AirRateTableReviewRepository,
    structure_repository: AirRateStructureReviewRepository,
    surcharge_repository: AirRateSurchargeReviewRepository,
    source_repository: AirShadowRepository,
    validity_repository: AirRateValidityReviewRepository,
    availability_repository: AirServiceAvailabilityRepository,
    fx_repository: AirFxRateEvidenceRepository | None = None,
    additional_cost_repository: AirAdditionalCostEvidenceRepository | None = None,
    rounding_repository: AirRateWeightRoundingReviewRepository | None = None,
    volumetric_weight_kg=None,
    total_volume_cm3=None,
    via_airport: Optional[str] = None,
    shipment_count: Optional[int] = None,
    awb_count: Optional[int] = None,
    hawb_count: Optional[int] = None,
    mawb_count: Optional[int] = None,
    fx_evidence_ids: Optional[list[str]] = None,
    additional_cost_evidence_ids: Optional[list[str]] = None,
    fx_reference_at: Optional[datetime] = None,
) -> AirOperationalReadinessPreview:
    inquiry = _normalized_inquiry_reference(inquiry_reference)
    selected_fx_ids = list(fx_evidence_ids or [])
    selected_additional_ids = list(additional_cost_evidence_ids or [])
    if fx_reference_at is not None and not selected_fx_ids:
        raise AirOperationalReadinessPreviewError("fx_evidence_ids_required_for_fx_context")

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
            reference_date=service_date,
            inquiry_reference=inquiry if (selected_fx_ids or selected_additional_ids) else None,
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
        raise AirOperationalReadinessPreviewError(str(exc)) from exc

    source = source_repository.get_rate_source(cost_preview.freight.source_id)
    if source is None:
        raise AirOperationalReadinessPreviewError("air_rate_source_not_found")
    destination_code = cost_preview.freight.destination_code
    if destination_code is None:
        raise AirOperationalReadinessPreviewError(
            "air_operational_readiness_destination_code_required"
        )

    matches = [
        item
        for item in availability_repository.list_all()
        if item.source_id == source.source_id
        and item.source_sha256 == source.sha256_hex
        and item.inquiry_reference == inquiry
        and item.destination_code == destination_code
        and item.routing_context == cost_preview.routing_context
        and item.via_airport == cost_preview.via_airport
        and item.service_date == service_date
    ]
    if len(matches) > 1:
        raise AirOperationalReadinessPreviewError(
            "air_service_availability_context_ambiguous"
        )

    common = dict(
        cost_preview=cost_preview,
        inquiry_reference=inquiry,
        service_date=service_date,
        tariff_validity_confirmed=cost_preview.tariff_validity_confirmed,
        fx_applied=cost_preview.fx_applied,
        fx_evidence_ids_used=cost_preview.fx_evidence_ids_used,
    )
    if not matches:
        return AirOperationalReadinessPreview(
            **common,
            availability_evidence_found=False,
            operational_blockers=["availability_evidence_missing"],
            capacity_confirmed=False,
            schedule_confirmed=False,
            operational_evidence_complete=False,
        )

    confirmation = matches[0]
    capacity_confirmed = confirmation.capacity_status == "available"
    schedule_confirmed = confirmation.schedule_status == "confirmed"
    blockers: list[AirOperationalBlocker] = []
    if not capacity_confirmed:
        blockers.append("capacity_unavailable")
    if not schedule_confirmed:
        blockers.append("schedule_not_confirmed")

    return AirOperationalReadinessPreview(
        **common,
        availability_evidence_found=True,
        availability_confirmation_id=confirmation.confirmation_id,
        capacity_status=confirmation.capacity_status,
        schedule_status=confirmation.schedule_status,
        flight_reference=confirmation.flight_reference,
        operational_blockers=blockers,
        capacity_confirmed=capacity_confirmed,
        schedule_confirmed=schedule_confirmed,
        operational_evidence_complete=(
            cost_preview.tariff_validity_confirmed
            and capacity_confirmed
            and schedule_confirmed
        ),
    )
