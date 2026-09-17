from __future__ import annotations

from datetime import datetime, timezone

from src.core.mina_job import MinaJobEvent
from src.core.mina_job_service import MinaJobNotFoundError, MinaJobTransitionError
from src.core.supplier_award import SupplierAwardSelection
from src.core.supplier_price import SupplierPriceOffer, evaluate_fixed_rate_applicability
from src.core.supplier_price_service import build_job_supplier_price_view


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def current_usable_offers(*, price_repository, mina_repository, supplier_repository, job_id: str) -> list[SupplierPriceOffer]:
    view = build_job_supplier_price_view(
        price_repository=price_repository, mina_repository=mina_repository,
        supplier_repository=supplier_repository, job_id=job_id,
    )
    offers = [SupplierPriceOffer.model_validate(item) for item in view["price_offers"]]
    # A newer usable price from the same supplier supersedes older evidence.
    current_by_supplier: dict[str, SupplierPriceOffer] = {}
    for offer in offers:
        key = " ".join(offer.supplier_name.casefold().split())
        current = current_by_supplier.get(key)
        if current is None or (offer.recorded_at, offer.offer_id) > (current.recorded_at, current.offer_id):
            current_by_supplier[key] = offer
    usable: list[SupplierPriceOffer] = []
    for offer in current_by_supplier.values():
        if not offer.is_price_usable:
            continue
        if offer.fixed_rate_id:
            rate = price_repository.get_fixed_rate(offer.fixed_rate_id)
            job = mina_repository.get(job_id)
            if rate is None or job is None or not evaluate_fixed_rate_applicability(
                rate=rate, shipment=job.shipment
            ).applicable:
                continue
        usable.append(offer)
    return usable


def select_approved_job_supplier_offer(
    *, award_repository, price_repository, mina_repository, supplier_repository,
    job_id: str, offer_id: str, selected_by: str, selected_at: datetime | None = None,
) -> SupplierAwardSelection:
    job = mina_repository.get(job_id)
    if job is None:
        raise MinaJobNotFoundError(f"MINA job not found: {job_id}")
    if job.job_kind != "approved_job":
        raise MinaJobTransitionError("Supplier award selection is only available for approved jobs.")
    if job.stage != "pricing":
        raise MinaJobTransitionError("Approved-job supplier award can only be selected during pricing.")
    offers = {item.offer_id: item for item in current_usable_offers(
        price_repository=price_repository, mina_repository=mina_repository,
        supplier_repository=supplier_repository, job_id=job_id,
    )}
    offer = offers.get(offer_id)
    if offer is None:
        raise MinaJobTransitionError("Selected supplier price offer is not current and usable.")
    actor = _actor(selected_by)
    timestamp = (selected_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = award_repository.current_for_job(job_id)
    selection = SupplierAwardSelection.from_offer(
        job_id=job.job_id, mina_code=job.mina_code, offer=offer,
        selected_by=actor, selected_at=timestamp,
        supersedes_selection_id=None if previous is None else previous.selection_id,
    )
    saved = award_repository.append(selection)
    mina_repository.append_event(MinaJobEvent(
        job_id=job.job_id, mina_code=job.mina_code,
        event_type="approved_job_supplier_award_selected", occurred_at=timestamp,
        actor=actor, resource_type="supplier_price_offer", resource_id=offer.offer_id,
        metadata={
            "selection_id": saved.selection_id, "supplier_name": saved.supplier_name,
            "offer_id": saved.offer_id, "cost": saved.cost, "currency": saved.currency,
            "source_type": saved.source_type,
            "source_reference_id": saved.source_reference_id,
            "rfq_id": saved.rfq_id, "fixed_rate_id": saved.fixed_rate_id,
            "supersedes_selection_id": saved.supersedes_selection_id,
        },
    ))
    return saved


def require_current_approved_job_supplier_award(
    *, job, award_repository, price_repository, mina_repository, supplier_repository,
) -> SupplierAwardSelection:
    selection = award_repository.current_for_job(job.job_id) if award_repository is not None else None
    if selection is None:
        raise MinaJobTransitionError(
            "Approved job operation opening requires an explicit supplier award selection."
        )
    offers = {item.offer_id: item for item in current_usable_offers(
        price_repository=price_repository, mina_repository=mina_repository,
        supplier_repository=supplier_repository, job_id=job.job_id,
    )}
    offer = offers.get(selection.offer_id)
    if offer is None:
        raise MinaJobTransitionError(
            "Approved job supplier award is stale; select a current usable supplier price offer."
        )
    snapshot = (offer.supplier_name, float(offer.cost), offer.currency, offer.source_type,
                offer.source_reference_id, offer.rfq_id, offer.fixed_rate_id)
    selected = (selection.supplier_name, selection.cost, selection.currency, selection.source_type,
                selection.source_reference_id, selection.rfq_id, selection.fixed_rate_id)
    if snapshot != selected:
        raise MinaJobTransitionError("Approved job supplier award evidence no longer matches its price offer.")
    return selection


def supplier_award_view(*, award_repository, price_repository, mina_repository, supplier_repository, job_id: str) -> dict:
    current = award_repository.current_for_job(job_id)
    current_ids = {item.offer_id for item in current_usable_offers(
        price_repository=price_repository, mina_repository=mina_repository,
        supplier_repository=supplier_repository, job_id=job_id,
    )}
    return {
        "current": None if current is None else current.model_dump(mode="json"),
        "current_selection_usable": bool(current and current.offer_id in current_ids),
        "history": [item.model_dump(mode="json") for item in award_repository.list_for_job(job_id)],
    }
