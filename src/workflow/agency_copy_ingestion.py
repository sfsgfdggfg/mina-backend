from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Callable

from src.core.agency_copy_receipt import (
    AgencyCopyMailReceipt,
    AgencyCopyReceiptRepository,
    DuplicateAgencyCopyReceiptError,
)
from src.core.customer_memory import sender_matches_profile
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import ExtractionProposalRepository
from src.core.mail import InboundMailEnvelope
from src.core.master_data_repository import MasterDataRepository
from src.core.master_data_service import customer_to_legacy_memory
from src.core.mina_job import MinaJob, MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.models import Shipment
from src.core.privacy import fingerprint_text
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_manual_sent import (
    CustomerQuoteManualSentNotFoundError,
    CustomerQuoteManualSentTransitionError,
    record_customer_quote_manually_sent,
)
from src.core.supplier_operational_inbound import matching_supplier_masters
from src.core.supplier_rfq_lifecycle import (
    SupplierRFQTransitionError,
    record_supplier_rfq_manually_sent,
)
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.core.supplier_customer_context import resolve_customer_master_profile
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
    existing_proposal_for_mail,
    extract_shipment_proposal_from_mail,
    save_preparsed_shipment_proposal,
)


_MINA_CODE_RE = re.compile(r"\bMINA\d{4}/[1-9]\d*\b", flags=re.IGNORECASE)
_FREIGHT_TERMS = (
    "navlun", "freight", "taşıma", "tasima", "yükleme", "yukleme", "teslim",
    "pickup", "delivery", "loading", "truck", "tır", "tir", "tenteli", "ftl",
    "ltl", "konteyner", "container", "palet", "pallet", "kg", "ton",
)
_SUPPLIER_RFQ_TERMS = (
    "navlun teklif", "fiyat rica", "teklifinizi rica", "araç talebi",
    "arac talebi", "freight quote", "please quote", "rate request",
)
_CUSTOMER_QUOTE_TERMS = (
    "teklifimiz", "navlun teklifimiz", "fiyatımız", "fiyatimiz",
    "our offer", "our quotation", "freight offer",
)
_FILLABLE_FIELDS = (
    "pickup_country", "pickup_city", "pickup_area", "pickup_postcode",
    "pickup_address", "pickup_contact_name", "pickup_contact_phone",
    "delivery_country", "delivery_city", "delivery_area", "delivery_postcode",
    "delivery_address", "delivery_contact_name", "delivery_contact_phone",
    "commodity", "gross_weight_kg", "equipment_type", "cargo_ready_date",
    "required_delivery_date", "special_notes", "packages",
)


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _message_text(mail: InboundMailEnvelope) -> str:
    return _norm(f"{mail.subject or ''}\n{mail.body_text or ''}")


def _looks_like_freight_context(mail: InboundMailEnvelope) -> bool:
    text = _message_text(mail)
    return sum(term in text for term in _FREIGHT_TERMS) >= 2


def _looks_like_supplier_rfq(mail: InboundMailEnvelope) -> bool:
    text = _message_text(mail)
    return any(term in text for term in _SUPPLIER_RFQ_TERMS)


def _looks_like_customer_quote(mail: InboundMailEnvelope) -> bool:
    text = _message_text(mail)
    return any(term in text for term in _CUSTOMER_QUOTE_TERMS)


def _agency_addresses(
    mail: InboundMailEnvelope,
    configured: list[str] | tuple[str, ...] | set[str],
) -> set[str]:
    mailbox = _norm(mail.mailbox_id)
    result = {_norm(item) for item in configured if _norm(item)}
    if mailbox:
        result.add(mailbox)
        if "@" in mailbox:
            domain = mailbox.rsplit("@", 1)[-1]
            for address in [
                mail.sender_address,
                *mail.recipient_addresses,
                *mail.to_addresses,
                *mail.cc_addresses,
                *mail.bcc_addresses,
            ]:
                normalized = _norm(address)
                if normalized and normalized.rsplit("@", 1)[-1] == domain:
                    result.add(normalized)
    return result


def _mailbox_recipient_role(mail: InboundMailEnvelope) -> str:
    mailbox = _norm(mail.mailbox_id)
    if mailbox and mailbox in {_norm(item) for item in mail.cc_addresses}:
        return "cc"
    if mailbox and mailbox in {_norm(item) for item in mail.to_addresses}:
        return "to"
    if mailbox and mailbox in {_norm(item) for item in mail.bcc_addresses}:
        return "bcc"
    if mailbox and mailbox in {_norm(item) for item in mail.recipient_addresses}:
        return "recipient"
    return "unknown"


def is_agency_copied_mail(
    mail: InboundMailEnvelope,
    *,
    configured_agency_addresses: list[str] | tuple[str, ...] | set[str] = (),
) -> bool:
    sender = _norm(mail.sender_address)
    if not sender:
        return False
    agency = _agency_addresses(mail, configured_agency_addresses)
    if sender not in agency:
        return False
    mailbox = _norm(mail.mailbox_id)
    return bool(
        mailbox
        and mailbox in {
            _norm(item)
            for item in [
                *mail.recipient_addresses,
                *mail.to_addresses,
                *mail.cc_addresses,
                *mail.bcc_addresses,
            ]
        }
    )


def _external_recipients(
    mail: InboundMailEnvelope,
    *,
    agency_addresses: set[str],
) -> list[str]:
    return [
        address
        for address in dict.fromkeys(_norm(item) for item in mail.recipient_addresses)
        if address and address not in agency_addresses
    ]


def _recipient_counterparties(
    *,
    addresses: list[str],
    master_repository: MasterDataRepository | None,
) -> tuple[list[Any], list[Any]]:
    if master_repository is None:
        return [], []
    customers: dict[str, Any] = {}
    suppliers: dict[str, Any] = {}
    for address in addresses:
        for customer in master_repository.list_customers():
            if not customer.active:
                continue
            if sender_matches_profile(customer_to_legacy_memory(customer), address):
                customers[customer.customer_id] = customer
        for supplier in matching_supplier_masters(master_repository, address):
            if supplier.active:
                suppliers[supplier.supplier_id] = supplier
    return list(customers.values()), list(suppliers.values())


def _mina_references(mail: InboundMailEnvelope) -> list[str]:
    values = _MINA_CODE_RE.findall(f"{mail.subject or ''}\n{mail.body_text or ''}")
    return list(dict.fromkeys(value.upper() for value in values))


def _location_present(shipment: ShipmentProposalSnapshot, prefix: str) -> bool:
    return any(
        bool(getattr(shipment, f"{prefix}_{field}", None))
        for field in ("address", "postcode", "city", "country")
    )


def _proposal_has_route(shipment: ShipmentProposalSnapshot) -> bool:
    return _location_present(shipment, "pickup") and _location_present(
        shipment, "delivery"
    )


def _same_value(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    if isinstance(left, str) or isinstance(right, str):
        return _norm(left) == _norm(right)
    return left == right


def _route_matches(job: MinaJob, proposed: ShipmentProposalSnapshot) -> bool:
    pickup_pairs = (
        ("pickup_postcode", 3),
        ("pickup_city", 2),
        ("pickup_country", 1),
    )
    delivery_pairs = (
        ("delivery_postcode", 3),
        ("delivery_city", 2),
        ("delivery_country", 1),
    )
    pickup_score = max(
        (
            score
            for field, score in pickup_pairs
            if _same_value(getattr(job.shipment, field), getattr(proposed, field))
        ),
        default=0,
    )
    delivery_score = max(
        (
            score
            for field, score in delivery_pairs
            if _same_value(getattr(job.shipment, field), getattr(proposed, field))
        ),
        default=0,
    )
    return pickup_score >= 1 and delivery_score >= 1 and pickup_score + delivery_score >= 3


def _resolve_customer_for_proposal(
    *,
    proposed: ShipmentProposalSnapshot,
    known_customer,
    master_repository: MasterDataRepository | None,
):
    if known_customer is not None:
        return known_customer
    if master_repository is None:
        return None
    name = _norm(proposed.customer_name)
    if not name or name == "unknown customer":
        return None
    return resolve_customer_master_profile(
        customer_name=proposed.customer_name,
        master_repository=master_repository,
    )


def _resolve_job(
    *,
    mail: InboundMailEnvelope,
    proposed: ShipmentProposalSnapshot | None,
    customer,
    mina_repository: MinaJobRepository | None,
) -> tuple[MinaJob | None, str | None]:
    if mina_repository is None:
        return None, None
    referenced = [
        job
        for code in _mina_references(mail)
        if (job := mina_repository.get_by_code(code)) is not None
    ]
    unique_referenced = {job.job_id: job for job in referenced}
    if len(unique_referenced) == 1:
        return next(iter(unique_referenced.values())), "mina_code_reference"
    if len(unique_referenced) > 1:
        return None, "ambiguous_mina_code_reference"
    if proposed is None or customer is None:
        return None, None

    matches = []
    for job in mina_repository.list_all():
        if job.is_closed:
            continue
        if _norm(job.shipment.customer_name) != _norm(customer.customer_name):
            continue
        if _route_matches(job, proposed):
            matches.append(job)
    if len(matches) == 1:
        return matches[0], "customer_route_unique_open_job"
    if len(matches) > 1:
        return None, "ambiguous_customer_route"
    return None, None


def _missing(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _apply_missing_fields(
    *,
    job: MinaJob,
    proposed: ShipmentProposalSnapshot,
    mina_repository: MinaJobRepository,
    mail: InboundMailEnvelope,
    counterparty_type: str,
    counterparty_name: str | None,
    correlation_method: str | None,
) -> tuple[MinaJob, list[str]]:
    if (
        job.is_closed
        or job.stage != "inquiry_confirmed"
        or job.supplier_rfq_workflow_id is not None
    ):
        return job, []

    updates: dict[str, Any] = {}
    for field in _FILLABLE_FIELDS:
        current = getattr(job.shipment, field)
        candidate = getattr(proposed, field)
        if _missing(current) and not _missing(candidate):
            updates[field] = candidate
    if not updates:
        return job, []

    shipment_data = job.shipment.model_dump()
    shipment_data.update(updates)
    updated_shipment = Shipment.model_validate(shipment_data)
    timestamp = mail.received_at or datetime.now(timezone.utc)
    updated = MinaJob.model_validate(
        job.model_copy(
            update={"shipment": updated_shipment, "updated_at": timestamp}
        ).model_dump()
    )
    updated = mina_repository.save(updated)
    return updated, sorted(updates)


def _event_resource_id(mail: InboundMailEnvelope) -> str:
    key = mail.message_deduplication_key or (
        f"{mail.provider_name}:{mail.mailbox_id}:{mail.external_message_id}"
    )
    return "agency-copy:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:40]


def _append_observation_event(
    *,
    job: MinaJob,
    mail: InboundMailEnvelope,
    mina_repository: MinaJobRepository,
    changed_fields: list[str],
    counterparty_type: str,
    counterparty_name: str | None,
    correlation_method: str | None,
) -> bool:
    resource_id = _event_resource_id(mail)
    if any(
        event.resource_type == "agency_copy_mail"
        and event.resource_id == resource_id
        for event in mina_repository.list_events(job.job_id)
    ):
        return False
    mina_repository.append_event(
        MinaJobEvent(
            job_id=job.job_id,
            mina_code=job.mina_code,
            event_type="agency_copied_mail_observed",
            occurred_at=mail.received_at or datetime.now(timezone.utc),
            actor=mail.sender_address,
            resource_type="agency_copy_mail",
            resource_id=resource_id,
            metadata={
                "message_key_sha256": resource_id.removeprefix("agency-copy:"),
                "mailbox_recipient_role": _mailbox_recipient_role(mail),
                "counterparty_type": counterparty_type,
                "counterparty_name": counterparty_name,
                "correlation_method": correlation_method,
                "changed_fields": changed_fields,
                "has_attachments": mail.has_attachments,
            },
        )
    )
    return True


def _try_record_supplier_rfq_send(
    *,
    job: MinaJob,
    supplier,
    external_addresses: list[str],
    mail: InboundMailEnvelope,
    supplier_repository: SupplierRFQRepository | None,
) -> str | None:
    if (
        supplier_repository is None
        or not job.supplier_rfq_workflow_id
        or not _looks_like_supplier_rfq(mail)
    ):
        return None
    matches = [
        draft
        for draft in supplier_repository.list_drafts()
        if draft.workflow_id == job.supplier_rfq_workflow_id
        and draft.status == "approved"
        and _norm(draft.recipient_email) in set(external_addresses)
        and _norm(draft.supplier_name) == _norm(supplier.supplier_name)
    ]
    if len(matches) != 1:
        return None
    try:
        record_supplier_rfq_manually_sent(
            supplier_repository,
            matches[0].rfq_id,
            recorded_by=mail.sender_address or "agency copied mail",
            recorded_at=mail.received_at,
        )
    except SupplierRFQTransitionError:
        return None
    return matches[0].rfq_id


def _try_record_customer_quote_send(
    *,
    job: MinaJob,
    customer,
    external_addresses: list[str],
    mail: InboundMailEnvelope,
    quote_case_repository: QuoteCaseRepository | None,
    approval_repository: QuoteApprovalRepository | None,
    mina_repository: MinaJobRepository | None,
) -> str | None:
    if (
        quote_case_repository is None
        or approval_repository is None
        or not job.quote_case_id
        or not _looks_like_customer_quote(mail)
    ):
        return None
    case = quote_case_repository.get(job.quote_case_id)
    if case is None or case.quote_approval is None:
        return None
    recipient = next(
        (
            address
            for address in external_addresses
            if sender_matches_profile(customer_to_legacy_memory(customer), address)
        ),
        None,
    )
    if recipient is None:
        return None
    try:
        record_customer_quote_manually_sent(
            quote_case_repository=quote_case_repository,
            approval_repository=approval_repository,
            case_id=case.case_id,
            expected_approval_id=case.quote_approval.approval_id,
            recipient_email=recipient,
            sent_by=mail.sender_address or "agency copied mail",
            sent_at=mail.received_at,
            mina_job_repository=mina_repository,
        )
    except (
        CustomerQuoteManualSentNotFoundError,
        CustomerQuoteManualSentTransitionError,
    ):
        return None
    return case.case_id



def _receipt_identity(mail: InboundMailEnvelope) -> tuple[str, str, str]:
    message_key = mail.message_deduplication_key
    if not message_key:
        raise InboundMailIdempotencyConflictError(
            "Agency copy mail requires a provider message identity."
        )
    sender = _norm(mail.sender_address)
    return (
        hashlib.sha256(message_key.encode("utf-8")).hexdigest(),
        fingerprint_text(mail.body_text),
        hashlib.sha256(sender.encode("utf-8")).hexdigest(),
    )


def _duplicate_result_from_receipt(receipt: AgencyCopyMailReceipt) -> dict:
    return {
        "result_type": "agency_copy_duplicate",
        "ingestion_status": "duplicate",
        "reason_code": "agency_copy_message_already_observed",
        "inbound_route": "agency_copy",
        "job_id": receipt.job_id,
        "mina_code": receipt.mina_code,
        "proposal_id": receipt.proposal_id,
        "counterparty_type": receipt.counterparty_type,
        "evidence_origin": "agency_copied",
        "extraction_proposal": None,
        "supplier_response": None,
    }


def _existing_receipt_result(
    *,
    mail: InboundMailEnvelope,
    receipt_repository: AgencyCopyReceiptRepository | None,
) -> dict | None:
    if receipt_repository is None:
        return None
    key_hash, body_hash, sender_hash = _receipt_identity(mail)
    existing = receipt_repository.get(key_hash)
    if existing is None:
        return None
    if (
        existing.body_sha256 != body_hash
        or existing.sender_sha256 != sender_hash
    ):
        raise InboundMailIdempotencyConflictError(
            "Agency copy message ID was reused with different content or sender."
        )
    return _duplicate_result_from_receipt(existing)


def _finalize_receipt(
    *,
    mail: InboundMailEnvelope,
    result: dict,
    receipt_repository: AgencyCopyReceiptRepository | None,
) -> dict:
    if receipt_repository is None:
        return result
    key_hash, body_hash, sender_hash = _receipt_identity(mail)
    proposal = result.get("extraction_proposal")
    proposal_id = result.get("proposal_id") or (
        getattr(proposal, "proposal_id", None) if proposal is not None else None
    )
    receipt = AgencyCopyMailReceipt(
        message_key_sha256=key_hash,
        body_sha256=body_hash,
        sender_sha256=sender_hash,
        result_type=str(result.get("result_type") or "agency_copy_observed"),
        ingestion_status=str(result.get("ingestion_status") or "review_required"),
        reason_code=str(
            result.get("reason_code")
            or "agency_copy_context_not_safe_for_automatic_job_action"
        ),
        observed_at=mail.received_at or datetime.now(timezone.utc),
        job_id=result.get("job_id"),
        mina_code=result.get("mina_code"),
        proposal_id=proposal_id,
        counterparty_type=result.get("counterparty_type"),
    )
    try:
        saved = receipt_repository.save_once(receipt)
    except DuplicateAgencyCopyReceiptError as exc:
        raise InboundMailIdempotencyConflictError(str(exc)) from exc
    if saved != receipt:
        return _duplicate_result_from_receipt(saved)
    return result


def process_agency_copied_mail(
    *,
    mail: InboundMailEnvelope,
    shipment_parser: Callable,
    proposal_repository: ExtractionProposalRepository,
    master_repository: MasterDataRepository | None,
    mina_repository: MinaJobRepository | None,
    supplier_repository: SupplierRFQRepository | None = None,
    quote_case_repository: QuoteCaseRepository | None = None,
    approval_repository: QuoteApprovalRepository | None = None,
    receipt_repository: AgencyCopyReceiptRepository | None = None,
    configured_agency_addresses: list[str] | tuple[str, ...] | set[str] = (),
) -> dict | None:
    """Observe an agency-authored message copied to the connected MINAI mailbox.

    This path never treats agency-authored text as customer-authored evidence.
    Existing jobs may receive only missing, non-safety shipment fields before
    sourcing starts. Otherwise the mail is linked as timeline evidence or becomes
    a human-reviewable extraction proposal.
    """

    if not is_agency_copied_mail(
        mail, configured_agency_addresses=configured_agency_addresses
    ):
        return None

    duplicate = _existing_receipt_result(
        mail=mail,
        receipt_repository=receipt_repository,
    )
    if duplicate is not None:
        return duplicate

    def finish(result: dict) -> dict:
        return _finalize_receipt(
            mail=mail,
            result=result,
            receipt_repository=receipt_repository,
        )

    agency = _agency_addresses(mail, configured_agency_addresses)
    external = _external_recipients(mail, agency_addresses=agency)
    customers, suppliers = _recipient_counterparties(
        addresses=external,
        master_repository=master_repository,
    )
    if len(customers) > 1 or len(suppliers) > 1 or (customers and suppliers):
        return finish({
            "result_type": "agency_copy_manual_review_required",
            "ingestion_status": "review_required",
            "reason_code": "agency_copy_counterparty_ambiguous",
            "inbound_route": "agency_copy",
            "extraction_proposal": None,
            "supplier_response": None,
        })

    known_customer = customers[0] if len(customers) == 1 else None
    known_supplier = suppliers[0] if len(suppliers) == 1 else None

    prior = existing_proposal_for_mail(
        mail=mail,
        repository=proposal_repository,
    )
    if prior is not None:
        return finish({
            "result_type": "extraction_confirmation_required",
            "ingestion_status": "duplicate_existing_proposal",
            "reason_code": "agency_copy_message_already_ingested",
            "inbound_route": "agency_copy",
            "extraction_proposal": prior,
            "supplier_response": None,
            "evidence_origin": prior.evidence_origin,
        })

    proposed = None
    safe_mail = None
    if not mail.has_attachments and _looks_like_freight_context(mail):
        safe_mail, proposed = extract_shipment_proposal_from_mail(
            mail=mail,
            shipment_parser=shipment_parser,
            trusted_customer_name=(
                known_customer.customer_name if known_customer is not None else None
            ),
        )

    customer_for_job = None
    if proposed is not None:
        customer_for_job = _resolve_customer_for_proposal(
            proposed=proposed,
            known_customer=known_customer,
            master_repository=master_repository,
        )
    elif known_customer is not None:
        customer_for_job = known_customer

    job, correlation_method = _resolve_job(
        mail=mail,
        proposed=proposed,
        customer=customer_for_job,
        mina_repository=mina_repository,
    )
    if correlation_method in {
        "ambiguous_mina_code_reference",
        "ambiguous_customer_route",
    }:
        return finish({
            "result_type": "agency_copy_manual_review_required",
            "ingestion_status": "review_required",
            "reason_code": correlation_method,
            "inbound_route": "agency_copy",
            "extraction_proposal": None,
            "supplier_response": None,
        })

    if job is not None and mina_repository is not None:
        changed_fields: list[str] = []
        if proposed is not None:
            job, changed_fields = _apply_missing_fields(
                job=job,
                proposed=proposed,
                mina_repository=mina_repository,
                mail=mail,
                counterparty_type=(
                    "customer" if known_customer is not None else "supplier"
                    if known_supplier is not None else "unknown"
                ),
                counterparty_name=(
                    known_customer.customer_name if known_customer is not None
                    else known_supplier.supplier_name if known_supplier is not None
                    else None
                ),
                correlation_method=correlation_method,
            )
        event_created = _append_observation_event(
            job=job,
            mail=mail,
            mina_repository=mina_repository,
            changed_fields=changed_fields,
            counterparty_type=(
                "customer" if known_customer is not None else "supplier"
                if known_supplier is not None else "unknown"
            ),
            counterparty_name=(
                known_customer.customer_name if known_customer is not None
                else known_supplier.supplier_name if known_supplier is not None
                else None
            ),
            correlation_method=correlation_method,
        )
        rfq_id = None
        quote_case_id = None
        if known_supplier is not None:
            rfq_id = _try_record_supplier_rfq_send(
                job=job,
                supplier=known_supplier,
                external_addresses=external,
                mail=mail,
                supplier_repository=supplier_repository,
            )
        if known_customer is not None:
            quote_case_id = _try_record_customer_quote_send(
                job=job,
                customer=known_customer,
                external_addresses=external,
                mail=mail,
                quote_case_repository=quote_case_repository,
                approval_repository=approval_repository,
                mina_repository=mina_repository,
            )
        return finish({
            "result_type": "agency_copy_job_observation",
            "ingestion_status": (
                "job_updated" if changed_fields else "job_evidence_attached"
            ),
            "reason_code": (
                "agency_copy_missing_fields_applied"
                if changed_fields
                else "agency_copy_correlated_to_existing_job"
            ),
            "inbound_route": "agency_copy",
            "job_id": job.job_id,
            "mina_code": job.mina_code,
            "correlation_method": correlation_method,
            "changed_fields": changed_fields,
            "event_created": event_created,
            "rfq_id": rfq_id,
            "quote_case_id": quote_case_id,
            "extraction_proposal": None,
            "supplier_response": None,
        })

    if proposed is not None and safe_mail is not None and _proposal_has_route(proposed):
        # A customer recipient is authoritative only for identity, not for the
        # authorship of shipment facts. A supplier-recipient copy must carry a
        # resolvable customer name in the parsed freight context.
        if known_customer is not None or customer_for_job is not None:
            trusted_name = (
                known_customer.customer_name if known_customer is not None else None
            )
            result = save_preparsed_shipment_proposal(
                original_mail=mail,
                safe_mail=safe_mail,
                proposed_shipment=proposed,
                proposal_repository=proposal_repository,
                trusted_customer_name=trusted_name,
                evidence_origin="agency_copied",
            )
            result.update(
                {
                    "result_type": "agency_copy_new_work_candidate",
                    "reason_code": "agency_copy_freight_context_requires_confirmation",
                    "inbound_route": "agency_copy",
                    "supplier_response": None,
                    "evidence_origin": "agency_copied",
                    "counterparty_type": (
                        "customer" if known_customer is not None else "supplier"
                    ),
                    "counterparty_name": (
                        known_customer.customer_name
                        if known_customer is not None
                        else known_supplier.supplier_name
                        if known_supplier is not None
                        else None
                    ),
                }
            )
            return finish(result)

    return finish({
        "result_type": "agency_copy_observed",
        "ingestion_status": "review_required",
        "reason_code": "agency_copy_context_not_safe_for_automatic_job_action",
        "inbound_route": "agency_copy",
        "extraction_proposal": None,
        "supplier_response": None,
        "counterparty_type": (
            "customer" if known_customer is not None else "supplier"
            if known_supplier is not None else "unknown"
        ),
        "counterparty_name": (
            known_customer.customer_name if known_customer is not None
            else known_supplier.supplier_name if known_supplier is not None
            else None
        ),
    })
