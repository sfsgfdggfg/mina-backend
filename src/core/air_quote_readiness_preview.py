from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.air_additional_cost_evidence_repository import AirAdditionalCostEvidenceRepository
from src.core.air_cost_scope_review_repository import AirCostScopeReviewRepository
from src.core.air_customer_pricing_preview import (
    AirCustomerPricingPreview,
    AirCustomerPricingPreviewError,
    build_air_customer_pricing_preview,
)
from src.core.air_fx_rate_evidence_repository import AirFxRateEvidenceRepository
from src.core.air_operational_readiness_preview import (
    AirOperationalReadinessPreview,
    AirOperationalReadinessPreviewError,
    build_air_operational_readiness_preview,
)
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_surcharge_review_repository import AirRateSurchargeReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_rate_validity_review_repository import AirRateValidityReviewRepository
from src.core.air_rate_weight_rounding_review_repository import AirRateWeightRoundingReviewRepository
from src.core.air_service_availability_repository import AirServiceAvailabilityRepository
from src.core.air_shadow_repository import AirShadowRepository
from src.core.air_unsupported_cost_semantics_review_repository import AirUnsupportedCostSemanticsReviewRepository
from src.core.master_data import normalize_master_text
from src.core.master_data_repository import MasterDataRepository
from src.core.models import Shipment
from src.core.pricing_policy import PricingFormula


class AirQuoteReadinessPreviewError(ValueError):
    pass


class AirQuoteReadinessPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pricing_preview: AirCustomerPricingPreview
    operational_readiness: AirOperationalReadinessPreview
    shipment: Shipment
    service_date: date
    cargo_ready_date: Optional[date] = None
    customer_required_delivery_date: Optional[date] = None
    expected_delivery_date: Optional[date] = None
    delivery_deadline_status: Literal[
        "not_provided", "confirmed", "evidence_missing", "not_met", "invalid"
    ] = "not_provided"
    package_piece_count: int = 0
    total_volume_cm3: Optional[Decimal] = None
    shipment_input_blockers: list[str] = Field(default_factory=list, max_length=100)
    blockers: list[str] = Field(default_factory=list, max_length=200)
    shipment_inputs_complete: bool = False
    pricing_complete: bool = False
    operational_evidence_complete: bool = False
    quote_ready: bool = False
    quote_creation_authority: bool = False
    quote_created: bool = False
    quote_send_authority: bool = False
    booking_authority: bool = False
    outbound_authority: bool = False
    runtime_authoritative: bool = False


def _parse_iso_date(value: Optional[str], *, blocker: str, blockers: list[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        blockers.append(blocker)
        return None


def _shipment_context(
    *,
    shipment: Shipment,
    customer,
    service_date: date,
    required_cost_categories: set[str],
    expected_delivery_date: Optional[date],
) -> tuple[list[str], int, Optional[Decimal], Optional[date], Optional[date], str]:
    blockers: list[str] = []
    if shipment.transport_mode != "air":
        blockers.append("shipment_transport_mode_must_be_air")

    valid_names = {normalize_master_text(customer.customer_name)}
    valid_names.update(normalize_master_text(alias) for alias in customer.aliases if str(alias).strip())
    if normalize_master_text(shipment.customer_name) not in valid_names:
        blockers.append("shipment_customer_mismatch")

    if not (shipment.pickup_address or shipment.pickup_city or shipment.pickup_postcode):
        blockers.append("pickup_location_required")
    if not (shipment.delivery_address or shipment.delivery_city or shipment.delivery_postcode):
        blockers.append("delivery_location_required")
    if "pickup" in required_cost_categories and not shipment.pickup_address:
        blockers.append("pickup_address_required_for_required_pickup_cost")
    if "delivery" in required_cost_categories and not shipment.delivery_address:
        blockers.append("delivery_address_required_for_required_delivery_cost")
    if not shipment.commodity:
        blockers.append("commodity_required")
    if shipment.gross_weight_kg is None or shipment.gross_weight_kg <= 0:
        blockers.append("gross_weight_kg_required")

    if shipment.is_adr is None:
        blockers.append("adr_status_required")
    elif shipment.is_adr and not shipment.adr_class:
        blockers.append("adr_class_required")
    if shipment.is_temperature_controlled is None:
        blockers.append("temperature_control_status_required")
    elif shipment.is_temperature_controlled and not shipment.temperature_requirement:
        blockers.append("temperature_requirement_required")
    if shipment.is_high_value is None:
        blockers.append("high_value_status_required")

    piece_count = 0
    total_volume = Decimal("0")
    if not shipment.packages:
        blockers.append("packages_required")
    for index, package in enumerate(shipment.packages, start=1):
        if package.quantity <= 0:
            blockers.append(f"package_quantity_invalid:{index}")
            continue
        piece_count += package.quantity
        dims = (package.length_cm, package.width_cm, package.height_cm)
        if any(value is None or value <= 0 for value in dims):
            blockers.append(f"package_dimensions_required:{index}")
            continue
        total_volume += (
            Decimal(str(package.quantity))
            * Decimal(str(package.length_cm))
            * Decimal(str(package.width_cm))
            * Decimal(str(package.height_cm))
        )
    if total_volume > Decimal("1000000000"):
        blockers.append("total_volume_cm3_out_of_range")

    cargo_ready = _parse_iso_date(
        shipment.cargo_ready_date,
        blocker="cargo_ready_date_invalid_or_missing",
        blockers=blockers,
    )
    if cargo_ready is None and not shipment.cargo_ready_date:
        blockers.append("cargo_ready_date_invalid_or_missing")
    if cargo_ready is not None and service_date < cargo_ready:
        blockers.append("service_date_before_cargo_ready_date")

    required_delivery = _parse_iso_date(
        shipment.required_delivery_date,
        blocker="required_delivery_date_invalid",
        blockers=blockers,
    )
    deadline_status = "not_provided"
    if shipment.required_delivery_date:
        if required_delivery is None:
            deadline_status = "invalid"
        elif expected_delivery_date is None:
            deadline_status = "evidence_missing"
            blockers.append("expected_delivery_date_evidence_required_for_customer_deadline")
        elif expected_delivery_date > required_delivery:
            deadline_status = "not_met"
            blockers.append("customer_delivery_deadline_not_met")
        else:
            deadline_status = "confirmed"

    return (
        blockers,
        piece_count,
        total_volume if total_volume > 0 else None,
        cargo_ready,
        required_delivery,
        deadline_status,
    )


def build_air_quote_readiness_preview(
    *,
    review_id: str,
    candidate_id: str,
    cost_scope_review_id: str,
    unsupported_cost_semantics_review_id: str,
    inquiry_reference: str,
    customer_id: str,
    service_date: date,
    shipment: Shipment,
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
    validity_repository: AirRateValidityReviewRepository,
    availability_repository: AirServiceAvailabilityRepository,
    master_data_repository: MasterDataRepository,
    fx_repository: AirFxRateEvidenceRepository | None = None,
    via_airport: Optional[str] = None,
    shipment_count: Optional[int] = None,
    awb_count: Optional[int] = None,
    hawb_count: Optional[int] = None,
    mawb_count: Optional[int] = None,
    fx_evidence_ids: Optional[list[str]] = None,
    additional_cost_evidence_ids: Optional[list[str]] = None,
    fx_reference_at: Optional[datetime] = None,
    quote_pricing_override: PricingFormula | None = None,
    environ: Mapping[str, str] | None = None,
) -> AirQuoteReadinessPreview:
    customer = master_data_repository.get_customer(str(customer_id or "").strip())
    if customer is None:
        raise AirQuoteReadinessPreviewError("customer_master_profile_not_found")
    if not customer.active:
        raise AirQuoteReadinessPreviewError("customer_master_profile_inactive")

    # Weight and dimensions directly change air chargeable weight; never fabricate them.
    if shipment.gross_weight_kg is None or shipment.gross_weight_kg <= 0:
        raise AirQuoteReadinessPreviewError("air_quote_readiness_gross_weight_required")
    if not shipment.packages:
        raise AirQuoteReadinessPreviewError("air_quote_readiness_packages_required")
    total_volume = Decimal("0")
    for index, package in enumerate(shipment.packages, start=1):
        dims = (package.length_cm, package.width_cm, package.height_cm)
        if package.quantity <= 0:
            raise AirQuoteReadinessPreviewError(f"air_quote_readiness_package_quantity_invalid:{index}")
        if any(value is None or value <= 0 for value in dims):
            raise AirQuoteReadinessPreviewError(f"air_quote_readiness_package_dimensions_required:{index}")
        total_volume += (
            Decimal(str(package.quantity))
            * Decimal(str(package.length_cm))
            * Decimal(str(package.width_cm))
            * Decimal(str(package.height_cm))
        )
    if total_volume <= 0 or total_volume > Decimal("1000000000"):
        raise AirQuoteReadinessPreviewError("air_quote_readiness_total_volume_out_of_range")
    volumetric_input = total_volume
    actual_weight = shipment.gross_weight_kg

    try:
        pricing = build_air_customer_pricing_preview(
            review_id=review_id,
            candidate_id=candidate_id,
            cost_scope_review_id=cost_scope_review_id,
            unsupported_cost_semantics_review_id=unsupported_cost_semantics_review_id,
            inquiry_reference=inquiry_reference,
            customer_id=customer_id,
            actual_weight_kg=actual_weight,
            total_volume_cm3=volumetric_input,
            cargo_context=cargo_context,
            routing_context=routing_context,
            via_airport=via_airport,
            shipment_count=shipment_count,
            awb_count=awb_count,
            hawb_count=hawb_count,
            mawb_count=mawb_count,
            reference_date=service_date,
            fx_evidence_ids=fx_evidence_ids,
            additional_cost_evidence_ids=additional_cost_evidence_ids,
            fx_reference_at=fx_reference_at,
            quote_pricing_override=quote_pricing_override,
            table_repository=table_repository,
            structure_repository=structure_repository,
            surcharge_repository=surcharge_repository,
            source_repository=source_repository,
            scope_repository=scope_repository,
            unsupported_semantics_repository=unsupported_semantics_repository,
            additional_cost_repository=additional_cost_repository,
            rounding_repository=rounding_repository,
            validity_repository=validity_repository,
            fx_repository=fx_repository,
            master_data_repository=master_data_repository,
            environ=environ,
        )
        operational = build_air_operational_readiness_preview(
            review_id=review_id,
            candidate_id=candidate_id,
            inquiry_reference=inquiry_reference,
            service_date=service_date,
            actual_weight_kg=actual_weight,
            total_volume_cm3=volumetric_input,
            cargo_context=cargo_context,
            routing_context=routing_context,
            via_airport=via_airport,
            shipment_count=shipment_count,
            awb_count=awb_count,
            hawb_count=hawb_count,
            mawb_count=mawb_count,
            fx_evidence_ids=fx_evidence_ids,
            additional_cost_evidence_ids=additional_cost_evidence_ids,
            fx_reference_at=fx_reference_at,
            table_repository=table_repository,
            structure_repository=structure_repository,
            surcharge_repository=surcharge_repository,
            source_repository=source_repository,
            validity_repository=validity_repository,
            availability_repository=availability_repository,
            fx_repository=fx_repository,
            additional_cost_repository=additional_cost_repository,
            rounding_repository=rounding_repository,
        )
    except (AirCustomerPricingPreviewError, AirOperationalReadinessPreviewError) as exc:
        raise AirQuoteReadinessPreviewError(str(exc)) from exc

    required_categories = set(pricing.cost_completeness.coverage_preview.required_categories)
    (
        shipment_blockers,
        piece_count,
        computed_volume,
        cargo_ready,
        required_delivery,
        deadline_status,
    ) = _shipment_context(
        shipment=shipment,
        customer=customer,
        service_date=service_date,
        required_cost_categories=required_categories,
        expected_delivery_date=operational.expected_delivery_date,
    )

    blockers = list(shipment_blockers)
    if pricing.pricing_status != "priced_preview" or not pricing.customer_price_preview_available:
        blockers.extend(f"pricing:{item}" for item in pricing.blockers or [pricing.pricing_status])
    if not operational.operational_evidence_complete:
        blockers.extend(f"operational:{item}" for item in operational.operational_blockers)

    pricing_cost = pricing.cost_completeness.coverage_preview.cost_preview
    operational_cost = operational.cost_preview
    if pricing_cost.freight.source_id != operational_cost.freight.source_id:
        blockers.append("pricing_operational_source_mismatch")
    if pricing_cost.freight.candidate_id != operational_cost.freight.candidate_id:
        blockers.append("pricing_operational_tariff_row_mismatch")
    if (
        pricing.cost_completeness.confirmed_cost_basis_amount is not None
        and pricing.cost_completeness.confirmed_cost_basis_amount
        != operational_cost.base_plus_reviewed_surcharges_and_additional_costs
    ):
        blockers.append("pricing_operational_cost_basis_mismatch")

    blockers = list(dict.fromkeys(blockers))
    shipment_complete = not shipment_blockers
    pricing_complete = pricing.pricing_status == "priced_preview" and pricing.customer_price_preview_available
    operational_complete = operational.operational_evidence_complete
    quote_ready = shipment_complete and pricing_complete and operational_complete and not blockers

    return AirQuoteReadinessPreview(
        pricing_preview=pricing,
        operational_readiness=operational,
        shipment=shipment,
        service_date=service_date,
        cargo_ready_date=cargo_ready,
        customer_required_delivery_date=required_delivery,
        expected_delivery_date=operational.expected_delivery_date,
        delivery_deadline_status=deadline_status,
        package_piece_count=piece_count,
        total_volume_cm3=computed_volume,
        shipment_input_blockers=shipment_blockers,
        blockers=blockers,
        shipment_inputs_complete=shipment_complete,
        pricing_complete=pricing_complete,
        operational_evidence_complete=operational_complete,
        quote_ready=quote_ready,
    )
