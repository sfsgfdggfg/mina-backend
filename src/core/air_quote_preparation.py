from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from src.core.air_additional_cost_evidence_repository import AirAdditionalCostEvidenceRepository
from src.core.air_cost_scope_review_repository import AirCostScopeReviewRepository
from src.core.air_fx_rate_evidence_repository import AirFxRateEvidenceRepository
from src.core.air_quote_context import AirQuoteContextSnapshot
from src.core.air_quote_readiness_preview import (
    AirQuoteReadinessPreview,
    AirQuoteReadinessPreviewError,
    build_air_quote_readiness_preview,
)
from src.core.air_rate_structure_review_repository import AirRateStructureReviewRepository
from src.core.air_rate_surcharge_review_repository import AirRateSurchargeReviewRepository
from src.core.air_rate_table_review_repository import AirRateTableReviewRepository
from src.core.air_rate_validity_review_repository import AirRateValidityReviewRepository
from src.core.air_rate_weight_rounding_review_repository import AirRateWeightRoundingReviewRepository
from src.core.air_service_availability_repository import AirServiceAvailabilityRepository
from src.core.air_shadow_repository import AirShadowRepository
from src.core.air_unsupported_cost_semantics_review_repository import AirUnsupportedCostSemanticsReviewRepository
from src.core.customer_commercial_context import build_customer_commercial_context
from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job import MinaJob
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import link_mina_job_quote_case
from src.core.models import CustomerQuote, QuoteDraft, Shipment, SupplierQuote
from src.core.pricing_policy import PricingFormula
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_send_safety import evaluate_quote_send_safety
from src.core.sqlite_repositories import atomic_repository_transaction


class AirQuotePreparationNotFoundError(LookupError):
    pass


class AirQuotePreparationTransitionError(ValueError):
    pass


class AirQuotePreparationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["blocked", "prepared", "existing"]
    readiness: AirQuoteReadinessPreview
    mina_job: MinaJob
    quote_case: Optional[QuoteCase] = None
    quote_approval: Optional[QuoteApproval] = None
    created: bool = False
    human_approval_required: bool = True
    quote_send_authority: bool = False
    booking_authority: bool = False
    outbound_authority: bool = False
    runtime_authoritative: bool = False


def _location_text(address: str | None, city: str | None, country: str | None) -> str:
    if address and address.strip():
        return address.strip()
    parts = [part.strip() for part in (city, country) if isinstance(part, str) and part.strip()]
    return ", ".join(parts) or "Belirtilmedi"


def _air_quote_draft(*, readiness: AirQuoteReadinessPreview, source, customer_quote: CustomerQuote) -> QuoteDraft:
    shipment = readiness.shipment
    freight = readiness.pricing_preview.cost_completeness.coverage_preview.cost_preview.freight
    operational = readiness.operational_readiness
    route_parts = [source.origin_airport or "çıkış", freight.destination_code or freight.destination_label]
    route = " → ".join(route_parts)
    if operational.cost_preview.routing_context == "connecting" and operational.cost_preview.via_airport:
        route = f"{route_parts[0]} → {operational.cost_preview.via_airport} → {route_parts[-1]}"

    lines = [
        "Merhaba,",
        "",
        "Aşağıdaki havayolu taşıma talebinize istinaden teklifimizi bilgilerinize sunarız.",
        "",
        f"Yükleme: {_location_text(shipment.pickup_address, shipment.pickup_city, shipment.pickup_country)}",
        f"Teslimat: {_location_text(shipment.delivery_address, shipment.delivery_city, shipment.delivery_country)}",
        f"Yük: {shipment.commodity or 'Belirtilmedi'}",
        f"Parça: {readiness.package_piece_count}",
        f"Brüt Ağırlık: {shipment.gross_weight_kg:g} kg",
        f"Chargeable Ağırlık: {freight.recommended_billed_weight_kg} kg",
        f"Havayolu Rotası: {route}",
        f"Planlanan Servis Tarihi: {readiness.service_date.isoformat()}",
    ]
    if readiness.expected_delivery_date is not None:
        lines.append(f"Beklenen Teslim Tarihi: {readiness.expected_delivery_date.isoformat()}")
    if operational.flight_reference:
        lines.append(f"Uçuş Referansı: {operational.flight_reference}")
    lines.extend([
        "",
        f"Fiyat: {customer_quote.final_price} {customer_quote.currency}",
        "",
        "Saygılarımızla,",
        "MINAI Freight OS",
    ])
    return QuoteDraft(subject="Havayolu Taşıma Teklifimiz Hakkında", body="\n".join(lines))


def _preparation_key(*, job: MinaJob, readiness: AirQuoteReadinessPreview, review_id: str,
                     candidate_id: str, cost_scope_review_id: str,
                     unsupported_cost_semantics_review_id: str, inquiry_reference: str,
                     customer_id: str, cargo_context: str, routing_context: str,
                     via_airport: str | None, shipment_count: int | None, awb_count: int | None,
                     hawb_count: int | None, mawb_count: int | None,
                     fx_evidence_ids: list[str], additional_cost_evidence_ids: list[str],
                     fx_reference_at: datetime | None, quote_pricing_override: PricingFormula | None) -> str:
    quote = readiness.pricing_preview.customer_price_preview
    cost = readiness.pricing_preview.cost_completeness
    payload = {
        "job_id": job.job_id,
        "shipment": job.shipment.model_dump(mode="json"),
        "review_id": review_id,
        "candidate_id": candidate_id,
        "cost_scope_review_id": cost_scope_review_id,
        "unsupported_cost_semantics_review_id": unsupported_cost_semantics_review_id,
        "inquiry_reference": inquiry_reference.strip(),
        "customer_id": customer_id.strip(),
        "service_date": readiness.service_date.isoformat(),
        "cargo_context": cargo_context,
        "routing_context": routing_context,
        "via_airport": via_airport.upper() if via_airport else None,
        "shipment_count": shipment_count,
        "awb_count": awb_count,
        "hawb_count": hawb_count,
        "mawb_count": mawb_count,
        "fx_evidence_ids": sorted(fx_evidence_ids),
        "additional_cost_evidence_ids": sorted(additional_cost_evidence_ids),
        "fx_reference_at": None if fx_reference_at is None else fx_reference_at.isoformat(),
        "quote_pricing_override": None if quote_pricing_override is None else quote_pricing_override.model_dump(mode="json"),
        "availability_confirmation_id": readiness.operational_readiness.availability_confirmation_id,
        "confirmed_cost_basis_amount": None if cost.confirmed_cost_basis_amount is None else str(cost.confirmed_cost_basis_amount),
        "confirmed_cost_basis_currency": cost.confirmed_cost_basis_currency,
        "customer_final_price": None if quote is None else quote.final_price,
        "customer_price_currency": None if quote is None else quote.currency,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _air_context(*, key: str, readiness: AirQuoteReadinessPreview, source,
                 cost_scope_review_id: str, unsupported_cost_semantics_review_id: str,
                 prepared_by: str, prepared_at: datetime) -> AirQuoteContextSnapshot:
    pricing = readiness.pricing_preview
    cost = pricing.cost_completeness
    cost_preview = cost.coverage_preview.cost_preview
    freight = cost_preview.freight
    quote = pricing.customer_price_preview
    if cost.confirmed_cost_basis_amount is None or cost.confirmed_cost_basis_currency is None or quote is None:
        raise AirQuotePreparationTransitionError("air_quote_ready_cost_or_customer_price_missing")
    return AirQuoteContextSnapshot(
        preparation_key=key,
        inquiry_reference=cost.inquiry_reference,
        customer_id=pricing.customer_id,
        customer_name=pricing.customer_name,
        source_id=source.source_id,
        source_sha256=source.sha256_hex,
        airline_name=source.airline_name,
        origin_airport=source.origin_airport,
        destination_code=freight.destination_code,
        table_review_id=freight.review_id,
        candidate_id=freight.candidate_id,
        cost_scope_review_id=cost_scope_review_id,
        unsupported_cost_semantics_review_id=unsupported_cost_semantics_review_id,
        validity_review_id=cost_preview.validity_review_id,
        rounding_review_id=freight.rounding_review_id,
        availability_confirmation_id=readiness.operational_readiness.availability_confirmation_id,
        service_date=readiness.service_date,
        expected_delivery_date=readiness.expected_delivery_date,
        routing_context=readiness.operational_readiness.cost_preview.routing_context,
        via_airport=readiness.operational_readiness.cost_preview.via_airport,
        flight_reference=readiness.operational_readiness.flight_reference,
        confirmed_cost_basis_amount=cost.confirmed_cost_basis_amount,
        confirmed_cost_basis_currency=cost.confirmed_cost_basis_currency,
        customer_final_price=Decimal(str(quote.final_price)),
        customer_price_currency=quote.currency,
        pricing_policy_source=None if pricing.pricing_policy is None else pricing.pricing_policy.policy_source,
        fx_evidence_ids=list(cost_preview.fx_evidence_ids_used),
        additional_cost_evidence_ids=list(cost_preview.additional_cost_evidence_ids_used),
        prepared_by=prepared_by,
        prepared_at=prepared_at,
    )


def _supplier_quote(*, readiness: AirQuoteReadinessPreview, source) -> SupplierQuote:
    cost = readiness.pricing_preview.cost_completeness
    cost_preview = cost.coverage_preview.cost_preview
    if cost.confirmed_cost_basis_amount is None or cost.confirmed_cost_basis_currency is None:
        raise AirQuotePreparationTransitionError("air_quote_ready_cost_basis_missing")
    included = ["base_freight"]
    included.extend(f"air_surcharge:{item.surcharge_code}" for item in cost_preview.included_surcharges)
    included.extend(f"air_flat_surcharge:{item.surcharge_code}" for item in cost_preview.included_flat_surcharges)
    included.extend(f"local_cost:{item.cost_category}" for item in cost_preview.included_additional_costs)
    transit = None
    if readiness.expected_delivery_date is not None:
        days = (readiness.expected_delivery_date - readiness.service_date).days
        transit = f"Planlanan {days} gün" if days >= 0 else None
    return SupplierQuote(
        supplier_name=source.airline_name,
        cost=float(cost.confirmed_cost_basis_amount),
        currency=cost.confirmed_cost_basis_currency,
        transit_time=transit,
        validity_date=None if cost_preview.reviewed_valid_to is None else cost_preview.reviewed_valid_to.isoformat(),
        equipment_type="air",
        pricing_basis="base_freight_plus_extras",
        included_costs=list(dict.fromkeys(included)),
        excluded_costs=[],
        notes="Confirmed air tariff/cost evidence basis; not an airline booking confirmation.",
        price_source="air_tariff_evidence",
        price_source_reference=f"{source.source_id}:{source.sha256_hex}:{cost_preview.freight.candidate_id}",
    )


def prepare_air_quote_case(
    *,
    job_id: str,
    review_id: str,
    candidate_id: str,
    cost_scope_review_id: str,
    unsupported_cost_semantics_review_id: str,
    inquiry_reference: str,
    customer_id: str,
    service_date: date,
    cargo_context: Literal["general_cargo", "special_cargo"],
    routing_context: Literal["direct", "connecting"],
    prepared_by: str,
    mina_job_repository: MinaJobRepository,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
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
    learning_fact_repository: LearningFactRepository | None = None,
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
    prepared_at: datetime | None = None,
) -> AirQuotePreparationResult:
    normalized_job_id = str(job_id or "").strip()
    actor = str(prepared_by or "").strip()
    if not normalized_job_id:
        raise ValueError("job_id is required")
    if not actor:
        raise ValueError("prepared_by is required")
    job = mina_job_repository.get(normalized_job_id)
    if job is None:
        raise AirQuotePreparationNotFoundError(f"MINA job not found: {normalized_job_id}")
    if job.job_kind != "price_request":
        raise AirQuotePreparationTransitionError("air_customer_quote_requires_price_request_job")
    if job.is_closed:
        raise AirQuotePreparationTransitionError("closed_mina_job_cannot_prepare_air_quote")
    if job.shipment.transport_mode != "air":
        raise AirQuotePreparationTransitionError("mina_job_transport_mode_must_be_air")

    selected_fx = list(fx_evidence_ids or [])
    selected_additional = list(additional_cost_evidence_ids or [])
    try:
        readiness = build_air_quote_readiness_preview(
            review_id=review_id,
            candidate_id=candidate_id,
            cost_scope_review_id=cost_scope_review_id,
            unsupported_cost_semantics_review_id=unsupported_cost_semantics_review_id,
            inquiry_reference=inquiry_reference,
            customer_id=customer_id,
            service_date=service_date,
            shipment=job.shipment,
            cargo_context=cargo_context,
            routing_context=routing_context,
            via_airport=via_airport,
            shipment_count=shipment_count,
            awb_count=awb_count,
            hawb_count=hawb_count,
            mawb_count=mawb_count,
            fx_evidence_ids=selected_fx,
            additional_cost_evidence_ids=selected_additional,
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
            availability_repository=availability_repository,
            fx_repository=fx_repository,
            master_data_repository=master_data_repository,
            environ=environ,
        )
    except AirQuoteReadinessPreviewError as exc:
        raise AirQuotePreparationTransitionError(str(exc)) from exc

    if not readiness.quote_ready:
        return AirQuotePreparationResult(status="blocked", readiness=readiness, mina_job=job)

    cost_preview = readiness.pricing_preview.cost_completeness.coverage_preview.cost_preview
    source = source_repository.get_rate_source(cost_preview.freight.source_id)
    if source is None:
        raise AirQuotePreparationNotFoundError("air_rate_source_not_found")
    now = prepared_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("prepared_at must be timezone-aware")
    key = _preparation_key(
        job=job, readiness=readiness, review_id=review_id, candidate_id=candidate_id,
        cost_scope_review_id=cost_scope_review_id,
        unsupported_cost_semantics_review_id=unsupported_cost_semantics_review_id,
        inquiry_reference=inquiry_reference, customer_id=customer_id,
        cargo_context=cargo_context, routing_context=routing_context, via_airport=via_airport,
        shipment_count=shipment_count, awb_count=awb_count, hawb_count=hawb_count,
        mawb_count=mawb_count, fx_evidence_ids=selected_fx,
        additional_cost_evidence_ids=selected_additional, fx_reference_at=fx_reference_at,
        quote_pricing_override=quote_pricing_override,
    )
    context = _air_context(
        key=key, readiness=readiness, source=source,
        cost_scope_review_id=cost_scope_review_id,
        unsupported_cost_semantics_review_id=unsupported_cost_semantics_review_id,
        prepared_by=actor, prepared_at=now,
    )

    with atomic_repository_transaction(
        mina_job_repository, quote_case_repository, approval_repository
    ):
        current = mina_job_repository.get(normalized_job_id)
        if current is None:
            raise AirQuotePreparationNotFoundError(f"MINA job not found: {normalized_job_id}")
        if current.shipment.model_dump(mode="json") != job.shipment.model_dump(mode="json"):
            raise AirQuotePreparationTransitionError("mina_job_shipment_changed_during_air_quote_preparation")
        if current.quote_case_id:
            existing_case = quote_case_repository.get(current.quote_case_id)
            if existing_case is None:
                raise AirQuotePreparationTransitionError("mina_job_quote_case_link_is_broken")
            if existing_case.air_quote_context is None or existing_case.air_quote_context.preparation_key != key:
                raise AirQuotePreparationTransitionError("mina_job_quote_case_already_linked_to_different_evidence")
            if existing_case.quote_approval is None:
                raise AirQuotePreparationTransitionError("existing_air_quote_case_missing_approval")
            approval = approval_repository.get(existing_case.quote_approval.approval_id)
            if approval is None:
                raise AirQuotePreparationTransitionError("existing_air_quote_approval_not_found")
            return AirQuotePreparationResult(
                status="existing", readiness=readiness, mina_job=current,
                quote_case=existing_case.model_copy(update={"quote_approval": approval}),
                quote_approval=approval, created=False,
            )
        if current.job_kind != "price_request" or current.is_closed:
            raise AirQuotePreparationTransitionError("mina_job_no_longer_eligible_for_air_quote")
        if current.stage not in {"inquiry_confirmed", "pricing", "quote_ready"}:
            raise AirQuotePreparationTransitionError(f"mina_job_stage_not_eligible_for_air_quote:{current.stage}")

        supplier_quote = _supplier_quote(readiness=readiness, source=source)
        customer_quote = readiness.pricing_preview.customer_price_preview
        if customer_quote is None:
            raise AirQuotePreparationTransitionError("air_customer_price_preview_missing")
        quote_draft = _air_quote_draft(readiness=readiness, source=source, customer_quote=customer_quote)
        quote_case = QuoteCase(
            shipment=current.shipment,
            mina_job_id=current.job_id,
            mina_code=current.mina_code,
            supplier_rfq_workflow_id=current.supplier_rfq_workflow_id,
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
            regulatory_compliance=readiness.regulatory_compliance,
            air_quote_context=context,
            created_at=now,
            updated_at=now,
        )
        commercial_context = build_customer_commercial_context(
            quote_case=quote_case,
            master_data_repository=master_data_repository,
            learning_fact_repository=learning_fact_repository,
            as_of=now,
        )
        approval = QuoteApproval(
            quote_snapshot=QuoteApprovalSnapshot.from_quote(
                supplier_quote=supplier_quote,
                customer_quote=customer_quote,
                quote_draft=quote_draft,
            ),
            customer_commercial_context_snapshot=commercial_context,
            air_quote_context_snapshot=context,
            created_at=now,
        )
        approval = approval_repository.save(approval)
        send_safety = evaluate_quote_send_safety(
            approval=approval,
            supplier_quote=supplier_quote,
            customer_quote=customer_quote,
            quote_draft=quote_draft,
            regulatory_compliance=readiness.regulatory_compliance,
        )
        quote_case = QuoteCase.model_validate(
            quote_case.model_copy(update={
                "quote_approval": approval,
                "quote_send_safety": send_safety,
                "updated_at": now,
            }).model_dump()
        )
        quote_case = quote_case_repository.save(quote_case)
        linked_job = link_mina_job_quote_case(
            repository=mina_job_repository,
            job_id=current.job_id,
            quote_case_id=quote_case.case_id,
            occurred_at=now,
        )

    return AirQuotePreparationResult(
        status="prepared", readiness=readiness, mina_job=linked_job,
        quote_case=quote_case, quote_approval=approval, created=True,
    )
