from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from src.core.air_additional_cost_evidence_repository import AirAdditionalCostEvidenceRepository
from src.core.air_cost_completeness_preview import (
    AirCostCompletenessPreview,
    AirCostCompletenessPreviewError,
    build_air_cost_completeness_preview,
)
from src.core.air_cost_scope_review_repository import AirCostScopeReviewRepository
from src.core.air_fx_rate_evidence_repository import AirFxRateEvidenceRepository
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_surcharge_review_repository import AirRateSurchargeReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_rate_validity_review_repository import AirRateValidityReviewRepository
from src.core.air_rate_weight_rounding_review_repository import AirRateWeightRoundingReviewRepository
from src.core.air_shadow_repository import AirShadowRepository
from src.core.air_unsupported_cost_semantics_review_repository import AirUnsupportedCostSemanticsReviewRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.models import CustomerQuote, SupplierQuote
from src.core.pricing import calculate_customer_quote
from src.core.pricing_policy import PricingFormula, PricingPolicyResolution, resolve_pricing_policy


class AirCustomerPricingPreviewError(ValueError):
    pass


class AirCustomerPricingPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cost_completeness: AirCostCompletenessPreview
    customer_id: str
    customer_name: str
    customer_active: bool
    pricing_status: Literal[
        "priced_preview", "cost_incomplete", "pricing_policy_required", "pricing_policy_invalid"
    ]
    pricing_policy: Optional[PricingPolicyResolution] = None
    customer_price_preview: Optional[CustomerQuote] = None
    blockers: list[str] = Field(default_factory=list, max_length=150)
    customer_price_preview_available: bool = False
    quote_ready: bool = False
    quote_created: bool = False
    quote_send_authority: bool = False
    booking_authority: bool = False
    outbound_authority: bool = False
    runtime_authoritative: bool = False


def build_air_customer_pricing_preview(
    *,
    review_id: str,
    candidate_id: str,
    cost_scope_review_id: str,
    unsupported_cost_semantics_review_id: str,
    inquiry_reference: str,
    customer_id: str,
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
    master_data_repository: MasterDataRepository,
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
    quote_pricing_override: PricingFormula | None = None,
    environ: Mapping[str, str] | None = None,
) -> AirCustomerPricingPreview:
    customer = master_data_repository.get_customer(str(customer_id or "").strip())
    if customer is None:
        raise AirCustomerPricingPreviewError("customer_master_profile_not_found")
    if not customer.active:
        raise AirCustomerPricingPreviewError("customer_master_profile_inactive")

    try:
        completeness = build_air_cost_completeness_preview(
            review_id=review_id,
            candidate_id=candidate_id,
            cost_scope_review_id=cost_scope_review_id,
            unsupported_cost_semantics_review_id=unsupported_cost_semantics_review_id,
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
            unsupported_semantics_repository=unsupported_semantics_repository,
            additional_cost_repository=additional_cost_repository,
            rounding_repository=rounding_repository,
            validity_repository=validity_repository,
            fx_repository=fx_repository,
        )
    except AirCostCompletenessPreviewError as exc:
        raise AirCustomerPricingPreviewError(str(exc)) from exc

    if not completeness.cost_completeness_confirmed:
        return AirCustomerPricingPreview(
            cost_completeness=completeness,
            customer_id=customer.customer_id,
            customer_name=customer.customer_name,
            customer_active=True,
            pricing_status="cost_incomplete",
            blockers=list(completeness.blockers) or ["air_cost_completeness_not_confirmed"],
        )

    currency = completeness.confirmed_cost_basis_currency
    amount = completeness.confirmed_cost_basis_amount
    if currency is None or amount is None:
        raise AirCustomerPricingPreviewError("confirmed_air_cost_basis_missing")

    resolution = resolve_pricing_policy(
        currency=currency,
        customer_pricing_policy=customer.pricing_policy,
        quote_override=quote_pricing_override,
        environ=environ,
    )
    if resolution.status == "invalid":
        return AirCustomerPricingPreview(
            cost_completeness=completeness,
            customer_id=customer.customer_id,
            customer_name=customer.customer_name,
            customer_active=True,
            pricing_status="pricing_policy_invalid",
            pricing_policy=resolution,
            blockers=[resolution.reason or "pricing_policy_invalid"],
        )
    if not resolution.resolved:
        return AirCustomerPricingPreview(
            cost_completeness=completeness,
            customer_id=customer.customer_id,
            customer_name=customer.customer_name,
            customer_active=True,
            pricing_status="pricing_policy_required",
            pricing_policy=resolution,
            blockers=[resolution.reason or "pricing_policy_required"],
        )

    adapter = SupplierQuote(
        supplier_name="MINAI confirmed air cost basis",
        cost=float(amount),
        currency=currency,
        pricing_basis="base_freight_plus_extras",
        notes="Internal pricing adapter only; not a supplier offer or booking authority.",
    )
    quote = calculate_customer_quote(adapter, resolution)
    return AirCustomerPricingPreview(
        cost_completeness=completeness,
        customer_id=customer.customer_id,
        customer_name=customer.customer_name,
        customer_active=True,
        pricing_status="priced_preview",
        pricing_policy=resolution,
        customer_price_preview=quote,
        customer_price_preview_available=True,
    )
