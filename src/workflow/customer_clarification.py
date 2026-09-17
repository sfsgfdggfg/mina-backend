from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import ValidationError

from src.core.extraction_confirmation_repository import ExtractionProposalRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job import MinaJob, MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import (
    MinaJobTransitionError,
    get_mina_job_or_raise,
    link_mina_job_workflow,
    record_mina_job_resume_result,
)
from src.core.models import Shipment
from src.core.operational_data import OperationalDataSources
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.workflow.pipeline import process_shipment

CustomerClarificationChannel = Literal[
    "email", "phone", "whatsapp", "portal", "face_to_face", "other"
]

ALLOWED_CUSTOMER_CLARIFICATION_FIELDS = frozenset({
    "pickup_country", "pickup_city", "pickup_area", "pickup_postcode",
    "pickup_address", "pickup_contact_name", "pickup_contact_phone",
    "delivery_country", "delivery_city", "delivery_area", "delivery_postcode",
    "delivery_address", "delivery_contact_name", "delivery_contact_phone",
    "commodity", "gross_weight_kg", "weight_is_approximate", "service_type",
    "equipment_type", "cargo_ready_date", "required_delivery_date",
    "special_notes", "packages",
})


def _updated_shipment(job: MinaJob, updates: dict[str, Any]) -> tuple[Shipment, list[str]]:
    if not updates:
        raise ValueError("At least one customer clarification field is required.")
    unsupported = sorted(set(updates) - ALLOWED_CUSTOMER_CLARIFICATION_FIELDS)
    if unsupported:
        raise ValueError(
            "Customer clarification cannot change protected shipment fields: "
            + ", ".join(unsupported)
        )
    candidate = job.shipment.model_dump()
    candidate.update(updates)
    try:
        shipment = Shipment.model_validate(candidate)
    except ValidationError as exc:
        raise ValueError("Customer clarification contains invalid shipment values.") from exc
    before = job.shipment.model_dump()
    after = shipment.model_dump()
    changed = sorted(field for field in updates if before.get(field) != after.get(field))
    if not changed:
        raise ValueError("Customer clarification does not change the current shipment.")
    return shipment, changed


def apply_customer_clarification(
    *,
    mina_repository: MinaJobRepository,
    proposal_repository: ExtractionProposalRepository,
    rfq_repository: SupplierRFQRepository,
    approval_repository: QuoteApprovalRepository,
    quote_case_repository: QuoteCaseRepository,
    job_id: str,
    actor: str,
    updates: dict[str, Any],
    source_channel: CustomerClarificationChannel,
    source_reference: str,
    note: str | None = None,
    operational_data_sources: OperationalDataSources | None = None,
    master_data_repository: MasterDataRepository | None = None,
    learning_fact_repository=None,
    occurred_at: datetime | None = None,
) -> dict:
    operator = actor.strip()
    reference = source_reference.strip()
    if not operator:
        raise ValueError("Operator identity is required.")
    if not reference:
        raise ValueError("Customer clarification source reference is required.")

    job = get_mina_job_or_raise(mina_repository, job_id=job_id)
    if job.is_closed or job.stage != "inquiry_confirmed":
        raise MinaJobTransitionError(
            "Customer clarification can update only an open inquiry-confirmed MINA job."
        )
    if job.supplier_rfq_workflow_id:
        raise MinaJobTransitionError(
            "Customer clarification cannot rewrite shipment facts after supplier sourcing has started."
        )

    shipment, changed_fields = _updated_shipment(job, updates)
    proposal = (
        proposal_repository.get(job.source_proposal_id)
        if job.source_proposal_id
        else None
    )
    inbound = None if proposal is None else proposal.inbound_mail
    result = process_shipment(
        shipment=shipment,
        email_text=None if inbound is None else inbound.body_text,
        sender_address=None if inbound is None else inbound.sender_address,
        customer_subject=None if inbound is None else inbound.subject,
        mina_job_id=job.job_id,
        mina_code=job.mina_code,
        rfq_repository=rfq_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        _persist_rfq_transition=False,
        operational_data_sources=operational_data_sources,
        master_data_repository=master_data_repository,
        learning_fact_repository=learning_fact_repository,
    )
    readiness = result.get("quote_readiness")
    result_type = str(
        result.get("result_type")
        or getattr(readiness, "result_type", None)
        or "unknown"
    )
    result["result_type"] = result_type
    workflow = result.get("supplier_rfq_workflow")
    drafts = result.get("supplier_rfq_drafts") or []
    timestamp = occurred_at or datetime.now(timezone.utc)

    with atomic_repository_transaction(
        mina_repository,
        rfq_repository if workflow is not None else None,
    ):
        current = get_mina_job_or_raise(mina_repository, job_id=job_id)
        if (
            current.updated_at != job.updated_at
            or current.stage != job.stage
            or current.supplier_rfq_workflow_id != job.supplier_rfq_workflow_id
            or current.shipment != job.shipment
        ):
            raise MinaJobTransitionError(
                "MINA job changed while customer clarification was being processed."
            )
        updated = MinaJob.model_validate(
            current.model_copy(
                update={"shipment": shipment, "updated_at": timestamp}
            ).model_dump()
        )
        updated = mina_repository.save(updated)
        mina_repository.append_event(
            MinaJobEvent(
                job_id=updated.job_id,
                mina_code=updated.mina_code,
                event_type="customer_clarification_applied",
                occurred_at=timestamp,
                actor=operator,
                resource_type="customer_clarification",
                resource_id=reference,
                metadata={
                    "changed_fields": changed_fields,
                    "source_channel": source_channel,
                    "source_reference": reference,
                    "note": (note or "").strip() or None,
                    "result_type": result_type,
                },
            )
        )
        if workflow is not None:
            result["supplier_rfq_drafts"] = rfq_repository.save_drafts(drafts)
            result["supplier_rfq_workflow"] = rfq_repository.save_workflow(workflow)
            updated = link_mina_job_workflow(
                repository=mina_repository,
                job_id=updated.job_id,
                workflow_id=workflow.workflow_id,
                result_type=result_type,
                occurred_at=timestamp,
            )
        else:
            updated = record_mina_job_resume_result(
                repository=mina_repository,
                job_id=updated.job_id,
                result_type=result_type,
                occurred_at=timestamp,
            )

    result["mina_job"] = updated
    result["customer_clarification"] = {
        "changed_fields": changed_fields,
        "source_channel": source_channel,
        "source_reference": reference,
        "result_type": result_type,
    }
    return result
