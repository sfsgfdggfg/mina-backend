from __future__ import annotations

from datetime import date, datetime, timezone

from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import MinaJobNotFoundError, MinaJobTransitionError
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_price import (
    SupplierFixedRate, SupplierFixedRateApplicability, SupplierFixedRateEvidenceSource,
    SupplierPriceOffer, SupplierPriceSource, evaluate_fixed_rate_applicability,
    offer_from_fixed_rate, offer_from_rfq_response,
)
from src.core.supplier_price_repository import SupplierPriceRepository
from src.core.supplier_rfq import SupplierPricingBasis


DIRECT_PRICE_SOURCES = {"email", "phone", "whatsapp", "portal", "api", "manual"}
PRICE_SOURCING_STAGES = {
    "inquiry_confirmed", "pricing", "quote_ready", "quote_sent", "negotiation"
}


def _aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Supplier price timestamps must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _utc_sort_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _open_price_job(repository: MinaJobRepository, job_id: str):
    job = repository.get(job_id)
    if job is None:
        raise MinaJobNotFoundError(f"MINA job not found: {job_id}")
    if job.is_closed:
        raise MinaJobTransitionError("Closed MINA jobs cannot receive supplier prices.")
    if job.stage not in PRICE_SOURCING_STAGES:
        raise MinaJobTransitionError(
            f"Supplier pricing is not open while MINA job is in stage {job.stage}."
        )
    return job


def create_supplier_fixed_rate(
    *, repository: SupplierPriceRepository, entry_id: str, supplier_name: str,
    origin_country: str, destination_country: str, cost: float, currency: str,
    valid_from: date, valid_to: date, evidence_source: SupplierFixedRateEvidenceSource,
    recorded_by: str, recorded_at: datetime | None = None,
    origin_city: str | None = None, destination_city: str | None = None,
    origin_region: str | None = None, destination_region: str | None = None,
    transport_mode=None, service_type: str | None = None, equipment_type: str | None = None,
    transit_time: str | None = None, pricing_basis: SupplierPricingBasis | None = None,
    included_costs: list[str] | None = None, excluded_costs: list[str] | None = None,
    evidence_reference: str | None = None, notes: str | None = None, active: bool = True,
) -> SupplierFixedRate:
    rate = SupplierFixedRate(
        entry_id=entry_id.strip(), supplier_name=supplier_name, origin_country=origin_country,
        destination_country=destination_country, origin_city=origin_city,
        destination_city=destination_city, origin_region=origin_region,
        destination_region=destination_region, transport_mode=transport_mode,
        service_type=service_type, equipment_type=equipment_type, cost=cost,
        currency=currency, transit_time=transit_time, pricing_basis=pricing_basis,
        included_costs=included_costs, excluded_costs=excluded_costs,
        valid_from=valid_from, valid_to=valid_to, evidence_source=evidence_source,
        evidence_reference=evidence_reference, recorded_by=_actor(recorded_by),
        recorded_at=_aware_utc(recorded_at), notes=notes, active=active,
    )
    with atomic_repository_transaction(repository):
        saved, _ = repository.create_fixed_rate(rate)
        return saved


def list_fixed_rate_applicability(
    *, repository: SupplierPriceRepository, shipment, as_of: date | None = None,
) -> list[tuple[SupplierFixedRate, SupplierFixedRateApplicability]]:
    return [
        (rate, evaluate_fixed_rate_applicability(rate=rate, shipment=shipment, as_of=as_of))
        for rate in repository.list_fixed_rates()
    ]


def _append_price_event(
    *, mina_repository: MinaJobRepository, job, offer: SupplierPriceOffer, actor: str,
    occurred_at: datetime, event_type: str,
) -> None:
    mina_repository.append_event(MinaJobEvent(
        job_id=job.job_id, mina_code=job.mina_code, event_type=event_type,
        occurred_at=occurred_at, actor=actor, resource_type="supplier_price_offer",
        resource_id=offer.offer_id, metadata={
            "supplier_name": offer.supplier_name, "source_type": offer.source_type,
            "source_reference_id": offer.source_reference_id, "cost": offer.cost,
            "currency": offer.currency,
        },
    ))


def create_direct_supplier_price_offer(
    *, price_repository: SupplierPriceRepository, mina_repository: MinaJobRepository,
    job_id: str, entry_id: str, supplier_name: str, source_type: SupplierPriceSource,
    cost: float, currency: str, recorded_by: str, recorded_at: datetime | None = None,
    source_reference_id: str | None = None, transit_time: str | None = None,
    validity_date: str | None = None, vehicle_available_date: str | None = None,
    equipment_type: str | None = None, pricing_basis: SupplierPricingBasis | None = None,
    included_costs: list[str] | None = None, excluded_costs: list[str] | None = None,
    notes: str | None = None,
) -> SupplierPriceOffer:
    if source_type not in DIRECT_PRICE_SOURCES:
        raise ValueError("Direct price entry source must be email/phone/whatsapp/portal/api/manual.")
    timestamp = _aware_utc(recorded_at)
    actor = _actor(recorded_by)
    with atomic_repository_transaction(price_repository, mina_repository):
        job = _open_price_job(mina_repository, job_id)
        offer = SupplierPriceOffer(
            entry_id=entry_id.strip(), mina_job_id=job.job_id, mina_code=job.mina_code,
            supplier_name=supplier_name, source_type=source_type,
            source_reference_id=source_reference_id, cost=cost, currency=currency,
            transit_time=transit_time, validity_date=validity_date,
            vehicle_available_date=vehicle_available_date, equipment_type=equipment_type,
            pricing_basis=pricing_basis, included_costs=included_costs,
            excluded_costs=excluded_costs, notes=notes, recorded_by=actor,
            recorded_at=timestamp,
        )
        saved, created = price_repository.create_offer(offer)
        if created:
            _append_price_event(
                mina_repository=mina_repository, job=job, offer=saved, actor=actor,
                occurred_at=timestamp, event_type="supplier_price_recorded",
            )
        return saved


def use_fixed_rate_for_job(
    *, price_repository: SupplierPriceRepository, mina_repository: MinaJobRepository,
    job_id: str, rate_id: str, entry_id: str, recorded_by: str,
    recorded_at: datetime | None = None, as_of: date | None = None,
) -> SupplierPriceOffer:
    timestamp = _aware_utc(recorded_at)
    actor = _actor(recorded_by)
    with atomic_repository_transaction(price_repository, mina_repository):
        job = _open_price_job(mina_repository, job_id)
        rate = price_repository.get_fixed_rate(rate_id)
        if rate is None:
            raise ValueError(f"Supplier fixed rate not found: {rate_id}")
        applicability = evaluate_fixed_rate_applicability(
            rate=rate, shipment=job.shipment, as_of=as_of
        )
        if not applicability.applicable:
            raise ValueError(
                "Supplier fixed rate is not applicable: " + ", ".join(applicability.reasons)
            )
        offer = offer_from_fixed_rate(
            rate=rate, job_id=job.job_id, mina_code=job.mina_code,
            entry_id=entry_id.strip(), recorded_by=actor, recorded_at=timestamp,
        )
        saved, created = price_repository.create_offer(offer)
        if created:
            _append_price_event(
                mina_repository=mina_repository, job=job, offer=saved, actor=actor,
                occurred_at=timestamp, event_type="supplier_fixed_rate_used",
            )
        return saved


def build_job_supplier_price_view(
    *, price_repository: SupplierPriceRepository, mina_repository: MinaJobRepository,
    supplier_repository, job_id: str, as_of: date | None = None,
) -> dict:
    job = mina_repository.get(job_id)
    if job is None:
        raise MinaJobNotFoundError(f"MINA job not found: {job_id}")

    offers = list(price_repository.list_offers(job_id=job.job_id))
    if job.supplier_rfq_workflow_id:
        workflow = supplier_repository.get_workflow(job.supplier_rfq_workflow_id)
        if workflow is not None:
            for draft in supplier_repository.list_drafts():
                if draft.workflow_id != workflow.workflow_id:
                    continue
                responses = [
                    item for item in supplier_repository.list_responses(draft.rfq_id)
                    if item.is_price_usable
                ]
                if not responses:
                    continue
                latest = max(responses, key=lambda item: _utc_sort_time(item.received_at))
                offers.append(offer_from_rfq_response(
                    response=latest, job_id=job.job_id, mina_code=job.mina_code
                ))

    applicable_rates = []
    rejected_count = 0
    for rate, applicability in list_fixed_rate_applicability(
        repository=price_repository, shipment=job.shipment, as_of=as_of
    ):
        if applicability.applicable:
            applicable_rates.append({
                "rate": rate.model_dump(),
                "applicability": applicability.model_dump(),
            })
        else:
            rejected_count += 1

    offers.sort(key=lambda item: (item.recorded_at, item.offer_id))
    return {
        "job_id": job.job_id,
        "mina_code": job.mina_code,
        "price_offers": [item.model_dump() for item in offers],
        "applicable_fixed_rates": applicable_rates,
        "non_applicable_fixed_rate_count": rejected_count,
    }


def set_supplier_fixed_rate_active(
    *, repository: SupplierPriceRepository, rate_id: str, active: bool,
    updated_by: str, updated_at: datetime | None = None,
) -> SupplierFixedRate:
    timestamp = _aware_utc(updated_at)
    actor = _actor(updated_by)
    with atomic_repository_transaction(repository):
        rate = repository.get_fixed_rate(rate_id)
        if rate is None:
            raise ValueError(f"Supplier fixed rate not found: {rate_id}")
        if rate.active == active:
            return rate
        updated = SupplierFixedRate.model_validate(
            rate.model_copy(update={
                "active": active, "updated_by": actor, "updated_at": timestamp,
            }).model_dump()
        )
        return repository.save_fixed_rate(updated)
