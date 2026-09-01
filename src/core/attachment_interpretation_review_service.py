from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import ValidationError

from src.core.attachment_content_verification import AttachmentRetrievalResult
from src.core.attachment_interpretation_review import (
    AttachmentInterpretationReview,
    AttachmentReviewEvidence,
)
from src.core.attachment_interpretation_review_repository import (
    AttachmentInterpretationReviewRepository,
)
from src.core.attachment_safe_interpretation import AttachmentInterpretationResult
from src.core.extraction_confirmation import ShipmentExtractionProposal, ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import ExtractionProposalRepository
from src.core.mail import InboundMailEnvelope
from src.core.privacy import PRIVACY_TRANSFORM_VERSION, fingerprint_text, minimize_text
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse
from src.core.supplier_rfq_lifecycle import attach_supplier_rfq_response
from src.core.supplier_rfq_repository import SupplierRFQRepository


class AttachmentReviewNotFoundError(LookupError):
    pass


class AttachmentReviewTransitionError(ValueError):
    pass


class AttachmentReviewConflictError(ValueError):
    pass


def _stable_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rfq_fingerprint(draft: SupplierRFQDraft) -> str:
    return _stable_hash(draft.model_dump(mode="json"))


def _privacy_safe_review_mail(mail: InboundMailEnvelope) -> InboundMailEnvelope:
    safe_body = minimize_text(mail.body_text) if mail.body_text.strip() else ""
    safe_subject = minimize_text(mail.subject) if mail.subject else None
    return mail.model_copy(
        update={
            "body_text": safe_body,
            "subject": safe_subject,
            "sender_name": None,
            "raw_body_sha256": fingerprint_text(mail.body_text),
            "privacy_transformed": True,
            "privacy_transform_version": PRIVACY_TRANSFORM_VERSION,
            "attachment_manifest": [],
            "attachment_manifest_truncated": False,
        }
    )


def _review_source_fingerprint(
    *,
    mail: InboundMailEnvelope,
    evidence: list[AttachmentReviewEvidence],
    interpretation: AttachmentInterpretationResult,
    candidate: ShipmentProposalSnapshot | SupplierResponseExtraction,
    rfq_snapshot_sha256: str | None,
) -> str:
    candidate_payload = candidate.model_dump(mode="json")
    return _stable_hash({
        "message_key": mail.message_deduplication_key,
        "sender_address": mail.sender_address,
        "received_at": mail.received_at,
        "raw_body_sha256": fingerprint_text(mail.body_text),
        "attachments": [item.model_dump(mode="json") for item in evidence],
        "route": interpretation.route,
        "privacy_transform_version": interpretation.privacy_transform_version,
        "candidate": candidate_payload,
        "rfq_snapshot_sha256": rfq_snapshot_sha256,
    })


def create_attachment_interpretation_review(
    *,
    mail: InboundMailEnvelope,
    retrieval: AttachmentRetrievalResult,
    interpretation: AttachmentInterpretationResult,
    repository: AttachmentInterpretationReviewRepository,
    supplier_repository: SupplierRFQRepository,
    trusted_customer_name: str | None = None,
    rfq_id: str | None = None,
    correlation_method: str | None = None,
) -> AttachmentInterpretationReview:
    if interpretation.status != "interpreted" or not interpretation.parser_called:
        raise AttachmentReviewTransitionError("Only a successful AI interpretation may enter review.")
    if interpretation.privacy_transform_version != PRIVACY_TRANSFORM_VERSION:
        raise AttachmentReviewConflictError(
            "Attachment interpretation did not use the approved privacy transform version."
        )
    if retrieval.status != "verified" or not retrieval.verified_receipts:
        raise AttachmentReviewTransitionError("Attachment review requires verified content receipts.")
    if len(retrieval.verified_receipts) != interpretation.source_attachment_count:
        raise AttachmentReviewConflictError("Interpretation attachment count does not match verification receipts.")
    message_key = mail.message_deduplication_key
    if not message_key:
        raise AttachmentReviewConflictError("Attachment review requires a durable message key.")

    evidence = [
        AttachmentReviewEvidence(
            content_profile=receipt.content_profile,
            size_bytes=receipt.size_bytes,
            sha256_hex=receipt.sha256_hex,
        )
        for receipt in retrieval.verified_receipts
    ]
    if [item.content_profile for item in evidence] != list(interpretation.source_profiles):
        raise AttachmentReviewConflictError("Interpretation profiles do not match verification receipts.")

    trusted_name = trusted_customer_name.strip() if trusted_customer_name else None
    if interpretation.route == "customer":
        if interpretation.customer_proposal is None:
            raise AttachmentReviewConflictError("Customer interpretation has no shipment candidate.")
        candidate = interpretation.customer_proposal
        if trusted_name:
            candidate = candidate.model_copy(update={"customer_name": trusted_name})
    else:
        if interpretation.supplier_extraction is None:
            raise AttachmentReviewConflictError("Supplier interpretation has no commercial candidate.")
        candidate = interpretation.supplier_extraction

    expected_rfq_hash = None
    if interpretation.route == "supplier":
        if not rfq_id:
            raise AttachmentReviewConflictError("Supplier attachment review requires an RFQ ID.")
        draft = supplier_repository.get_draft(rfq_id)
        if draft is None:
            raise AttachmentReviewConflictError("Supplier RFQ no longer exists.")
        if draft.status not in {"awaiting_response", "clarification_required"}:
            raise AttachmentReviewTransitionError("Supplier RFQ is no longer review-applicable.")
        if not mail.sender_address or draft.recipient_email != mail.sender_address:
            raise AttachmentReviewConflictError("Supplier identity changed before review creation.")
        expected_rfq_hash = _rfq_fingerprint(draft)

    fingerprint = _review_source_fingerprint(
        mail=mail, evidence=evidence, interpretation=interpretation, candidate=candidate,
        rfq_snapshot_sha256=expected_rfq_hash,
    )
    existing = repository.find_by_source_fingerprint(fingerprint)
    if existing is not None:
        return existing
    prior_message_review = repository.find_by_message_key(message_key)
    if prior_message_review is not None:
        raise AttachmentReviewConflictError(
            "Inbound attachment message already has a different durable review fingerprint."
        )

    safe_mail = _privacy_safe_review_mail(mail)
    review = AttachmentInterpretationReview(
        route=interpretation.route,
        source_message_key=message_key,
        source_fingerprint_sha256=fingerprint,
        inbound_mail=safe_mail,
        attachment_evidence=evidence,
        privacy_transform_version=(
            interpretation.privacy_transform_version or PRIVACY_TRANSFORM_VERSION
        ),
        source_character_count=interpretation.source_character_count,
        source_table_count=interpretation.source_table_count,
        trusted_customer_name=trusted_name,
        rfq_id=rfq_id if interpretation.route == "supplier" else None,
        correlation_method=correlation_method if interpretation.route == "supplier" else None,
        expected_rfq_snapshot_sha256=expected_rfq_hash,
        customer_candidate=(candidate if interpretation.route == "customer" else None),
        supplier_candidate=(candidate if interpretation.route == "supplier" else None),
    )
    return repository.save(review)


def _load_review(
    repository: AttachmentInterpretationReviewRepository, review_id: str
) -> AttachmentInterpretationReview:
    review = repository.get(review_id)
    if review is None:
        raise AttachmentReviewNotFoundError(f"Attachment interpretation review not found: {review_id}")
    return review


def _customer_candidate_with_corrections(
    review: AttachmentInterpretationReview, corrections: dict[str, Any]
) -> tuple[ShipmentProposalSnapshot, dict[str, Any], list[str]]:
    assert review.customer_candidate is not None
    unknown = set(corrections) - set(ShipmentProposalSnapshot.model_fields)
    if unknown:
        raise AttachmentReviewTransitionError(
            "Unknown customer review correction fields: " + ", ".join(sorted(unknown))
        )
    blocked_fields = {"regulatory_exception_reviews"}
    if review.trusted_customer_name:
        blocked_fields.add("customer_name")
    disallowed = set(corrections).intersection(blocked_fields)
    if disallowed:
        raise AttachmentReviewTransitionError(
            "System/trust-managed customer fields cannot be corrected here: "
            + ", ".join(sorted(disallowed))
        )
    data = review.customer_candidate.model_dump()
    data.update(corrections)
    if review.trusted_customer_name:
        data["customer_name"] = review.trusted_customer_name
    try:
        candidate = ShipmentProposalSnapshot.model_validate(data)
    except ValidationError as exc:
        raise AttachmentReviewTransitionError("Customer attachment review corrections are invalid.") from exc
    if candidate.is_adr is False and candidate.adr_class is not None:
        raise AttachmentReviewTransitionError("ADR class must be empty when ADR is false.")
    if candidate.is_temperature_controlled is False and candidate.temperature_requirement is not None:
        raise AttachmentReviewTransitionError(
            "Temperature requirement must be empty when temperature control is false."
        )
    before = review.customer_candidate.model_dump()
    after = candidate.model_dump()
    changed = sorted(name for name in ShipmentProposalSnapshot.model_fields if before.get(name) != after.get(name))
    normalized = {name: after.get(name) for name in changed}
    return candidate, normalized, changed


def _supplier_candidate_with_corrections(
    review: AttachmentInterpretationReview, corrections: dict[str, Any]
) -> tuple[SupplierResponseExtraction, dict[str, Any], list[str]]:
    assert review.supplier_candidate is not None
    allowed = set(SupplierResponseExtraction.model_fields)
    unknown = set(corrections) - allowed
    if unknown:
        raise AttachmentReviewTransitionError(
            "Unknown supplier review correction fields: " + ", ".join(sorted(unknown))
        )
    data = review.supplier_candidate.model_dump()
    data.update(corrections)
    try:
        candidate = SupplierResponseExtraction.model_validate(data)
    except ValidationError as exc:
        raise AttachmentReviewTransitionError("Supplier attachment review corrections are invalid.") from exc
    if candidate.status is None:
        raise AttachmentReviewTransitionError("Supplier review requires an explicit response status.")
    if candidate.status == "quoted":
        if candidate.cost is None or candidate.currency is None:
            raise AttachmentReviewTransitionError("Quoted supplier review requires cost and currency.")
        if "cost" in candidate.uncertain_fields or "currency" in candidate.uncertain_fields:
            raise AttachmentReviewTransitionError("Quoted supplier review cannot apply uncertain cost or currency.")
    before = review.supplier_candidate.model_dump()
    after = candidate.model_dump()
    changed = sorted(name for name in SupplierResponseExtraction.model_fields if before.get(name) != after.get(name))
    normalized = {name: after.get(name) for name in changed}
    return candidate, normalized, changed



_CUSTOMER_SAFETY_FIELDS = {
    "is_adr", "adr_class", "is_temperature_controlled",
    "temperature_requirement", "is_high_value",
}
_CUSTOMER_OPERATIONAL_FIELDS = {
    "pickup_country", "pickup_city", "pickup_area", "pickup_postcode",
    "delivery_country", "delivery_city", "delivery_area", "delivery_postcode",
    "commodity", "gross_weight_kg", "service_type", "quote_mode",
    "transport_mode", "equipment_type", "cargo_ready_date",
    "required_delivery_date", "packages",
}
_SUPPLIER_CRITICAL_FIELDS = {"status", "cost", "currency"}
_SUPPLIER_IMPORTANT_FIELDS = {
    "transit_time", "validity_date", "vehicle_available_date",
    "equipment_type", "pricing_basis", "included_costs", "excluded_costs",
}


def _review_field_category(route: str, name: str) -> str:
    if route == "customer":
        if name in _CUSTOMER_SAFETY_FIELDS:
            return "safety"
        if name in _CUSTOMER_OPERATIONAL_FIELDS:
            return "operational"
        return "informational"
    if name in _SUPPLIER_CRITICAL_FIELDS:
        return "commercial_critical"
    if name in _SUPPLIER_IMPORTANT_FIELDS:
        return "commercial"
    return "informational"


def _review_field_editable(review: AttachmentInterpretationReview, name: str) -> bool:
    if review.route == "customer":
        if name == "regulatory_exception_reviews":
            return False
        if name == "customer_name" and review.trusted_customer_name:
            return False
    return name != "uncertain_fields"


def build_attachment_review_preview(
    review: AttachmentInterpretationReview,
    corrections: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a mutation-free field review using the exact apply validators."""
    supplied = corrections or {}
    blockers: list[str] = []
    warnings: list[str] = []
    validation_error = None
    original = (
        review.customer_candidate.model_dump(mode="json")
        if review.route == "customer" and review.customer_candidate is not None
        else review.supplier_candidate.model_dump(mode="json")
        if review.supplier_candidate is not None
        else {}
    )
    normalized = dict(original)
    changed: list[str] = []
    if review.status != "pending":
        blockers.append("review_is_not_pending")
    else:
        try:
            if review.route == "customer":
                candidate, _, changed = _customer_candidate_with_corrections(review, supplied)
            else:
                candidate, _, changed = _supplier_candidate_with_corrections(review, supplied)
            normalized = candidate.model_dump(mode="json")
        except AttachmentReviewTransitionError as exc:
            validation_error = str(exc)
            blockers.append("corrections_invalid_or_not_applyable")

    uncertain = set(
        (review.supplier_candidate.uncertain_fields if review.supplier_candidate else [])
    )
    field_names = [
        name for name in original
        if name != "uncertain_fields"
    ]
    fields = []
    critical_attention = []
    for name in field_names:
        category = _review_field_category(review.route, name)
        value = normalized.get(name)
        reasons: list[str] = []
        safety_unknown = False
        if review.route == "customer" and category == "safety" and value is None:
            if name in {"is_adr", "is_temperature_controlled", "is_high_value"}:
                safety_unknown = True
            elif name == "adr_class" and normalized.get("is_adr") is True:
                safety_unknown = True
            elif (
                name == "temperature_requirement"
                and normalized.get("is_temperature_controlled") is True
            ):
                safety_unknown = True
        if safety_unknown:
            reasons.append("safety_value_unknown")
            warnings.append(f"safety_value_unknown:{name}")
        if review.route == "supplier" and name in uncertain:
            reasons.append("parser_marked_uncertain")
            warnings.append(f"parser_marked_uncertain:{name}")
        if name in changed and category in {"safety", "commercial_critical"}:
            reasons.append("critical_field_changed_by_operator")
        requires_attention = bool(reasons)
        if requires_attention or (
            name in changed and category in {"safety", "commercial_critical"}
        ):
            critical_attention.append(name)
        fields.append({
            "field": name,
            "category": category,
            "editable": _review_field_editable(review, name),
            "source_state": (
                "uncertain" if name in uncertain
                else "not_provided" if original.get(name) is None
                else "provided"
            ),
            "original_value": original.get(name),
            "preview_value": value,
            "changed": name in changed,
            "requires_attention": requires_attention,
            "attention_reasons": reasons,
        })

    token_payload = {
        "review_id": review.review_id,
        "source_fingerprint": review.source_fingerprint_sha256,
        "status": review.status,
        "corrections": supplied,
        "normalized": normalized,
    }
    preview_token = _stable_hash(token_payload)
    return {
        "review_id": review.review_id,
        "route": review.route,
        "status": review.status,
        "apply_ready": not blockers,
        "preview_token": preview_token,
        "changed_fields": changed,
        "critical_attention_fields": sorted(set(critical_attention)),
        "blockers": blockers,
        "warnings": sorted(set(warnings)),
        "validation_error": validation_error,
        "field_count": len(fields),
        "changed_field_count": len(changed),
        "critical_attention_count": len(set(critical_attention)),
        "fields": fields,
    }


def require_matching_attachment_review_preview(
    review: AttachmentInterpretationReview,
    *,
    corrections: dict[str, Any] | None,
    preview_token: str,
) -> dict[str, Any]:
    preview = build_attachment_review_preview(review, corrections)
    if not preview["apply_ready"]:
        raise AttachmentReviewTransitionError(
            preview.get("validation_error") or "Attachment review preview is not apply-ready."
        )
    if not preview_token or preview_token != preview["preview_token"]:
        raise AttachmentReviewConflictError(
            "Attachment review preview token does not match the current corrections/state."
        )
    return preview


def apply_attachment_interpretation_review(
    *,
    repository: AttachmentInterpretationReviewRepository,
    review_id: str,
    operator_identity: str,
    corrections: dict[str, Any] | None,
    proposal_repository: ExtractionProposalRepository,
    supplier_repository: SupplierRFQRepository,
    reviewed_at: datetime | None = None,
) -> AttachmentInterpretationReview:
    operator = operator_identity.strip()
    if not operator:
        raise ValueError("Attachment review operator identity is required.")
    initial = _load_review(repository, review_id)
    if initial.status != "pending":
        raise AttachmentReviewTransitionError("Only a pending attachment review may be applied.")
    now = reviewed_at or datetime.now(timezone.utc)

    target_repository = proposal_repository if initial.route == "customer" else supplier_repository
    with atomic_repository_transaction(repository, target_repository):
        review = _load_review(repository, review_id)
        if review != initial or review.status != "pending":
            raise AttachmentReviewTransitionError("Attachment review changed during apply.")

        if review.route == "customer":
            candidate, normalized, changed = _customer_candidate_with_corrections(
                review, corrections or {}
            )
            existing = proposal_repository.find_by_message_key(review.source_message_key)
            if existing is not None:
                raise AttachmentReviewConflictError("Customer attachment message already has an extraction proposal.")
            proposal = ShipmentExtractionProposal(
                inbound_mail=review.inbound_mail,
                proposed_shipment=candidate,
                source_attachment_review_id=review.review_id,
                source="attachment_interpretation_review",
            )
            proposal = proposal_repository.save(proposal)
            updated = review.model_copy(update={
                "status": "applied",
                "reviewed_by": operator,
                "reviewed_at": now,
                "operator_corrections": normalized,
                "changed_fields": changed,
                "applied_proposal_id": proposal.proposal_id,
            })
        else:
            assert review.rfq_id and review.expected_rfq_snapshot_sha256
            draft = supplier_repository.get_draft(review.rfq_id)
            if draft is None:
                raise AttachmentReviewConflictError("Supplier RFQ no longer exists.")
            if _rfq_fingerprint(draft) != review.expected_rfq_snapshot_sha256:
                raise AttachmentReviewConflictError("Supplier RFQ changed after attachment review creation.")
            if not review.inbound_mail.sender_address or draft.recipient_email != review.inbound_mail.sender_address:
                raise AttachmentReviewConflictError("Supplier identity changed after attachment review creation.")
            candidate, normalized, changed = _supplier_candidate_with_corrections(
                review, corrections or {}
            )
            response = SupplierRFQResponse(
                rfq_id=draft.rfq_id,
                supplier_name=draft.supplier_name,
                rfq_priority=draft.priority,
                status=candidate.status,
                cost=candidate.cost,
                currency=candidate.currency,
                transit_time=candidate.transit_time,
                validity_date=candidate.validity_date,
                vehicle_available_date=candidate.vehicle_available_date,
                equipment_type=candidate.equipment_type,
                pricing_basis=candidate.pricing_basis,
                included_costs=candidate.included_costs,
                excluded_costs=candidate.excluded_costs,
                notes=candidate.notes,
                source="email",
                recorded_by=operator,
                received_at=review.inbound_mail.received_at or now,
                source_attachment_review_id=review.review_id,
            )
            attach_supplier_rfq_response(supplier_repository, response)
            supplier_repository.record_ingested_message(
                review.source_message_key,
                body_sha256=review.inbound_mail.raw_body_sha256,
                sender_address=review.inbound_mail.sender_address,
                attachment_source_sha256=review.source_fingerprint_sha256,
                attachment_review_id=review.review_id,
            )
            updated = review.model_copy(update={
                "status": "applied",
                "reviewed_by": operator,
                "reviewed_at": now,
                "operator_corrections": normalized,
                "changed_fields": changed,
                "applied_rfq_id": draft.rfq_id,
            })
        return repository.save(AttachmentInterpretationReview.model_validate(updated.model_dump()))


def reject_attachment_interpretation_review(
    *,
    repository: AttachmentInterpretationReviewRepository,
    review_id: str,
    operator_identity: str,
    rejection_reason: str,
    reviewed_at: datetime | None = None,
) -> AttachmentInterpretationReview:
    operator = operator_identity.strip()
    reason = rejection_reason.strip()
    if not operator or not reason:
        raise ValueError("Attachment review rejection requires operator identity and reason.")
    with atomic_repository_transaction(repository):
        review = _load_review(repository, review_id)
        if review.status != "pending":
            raise AttachmentReviewTransitionError("Only a pending attachment review may be rejected.")
        updated = review.model_copy(update={
            "status": "rejected",
            "reviewed_by": operator,
            "reviewed_at": reviewed_at or datetime.now(timezone.utc),
            "rejection_reason": reason,
        })
        return repository.save(AttachmentInterpretationReview.model_validate(updated.model_dump()))


def attachment_review_public_payload(
    review: AttachmentInterpretationReview, *, include_candidate: bool
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "review_id": review.review_id,
        "route": review.route,
        "status": review.status,
        "created_at": review.created_at,
        "reviewed_by": review.reviewed_by,
        "reviewed_at": review.reviewed_at,
        "privacy_transform_version": review.privacy_transform_version,
        "attachment_count": len(review.attachment_evidence),
        "attachment_profiles": [item.content_profile for item in review.attachment_evidence],
        "attachment_total_size_bytes": sum(item.size_bytes for item in review.attachment_evidence),
        "source_character_count": review.source_character_count,
        "source_table_count": review.source_table_count,
        "rfq_id": review.rfq_id,
        "correlation_method": review.correlation_method,
        "changed_fields": review.changed_fields,
        "applied_proposal_id": review.applied_proposal_id,
        "applied_rfq_id": review.applied_rfq_id,
    }
    if include_candidate:
        payload["subject"] = review.inbound_mail.subject
        payload["rejection_reason"] = review.rejection_reason
        payload["operator_corrections"] = review.operator_corrections
        payload["candidate"] = (
            review.customer_candidate.model_dump(mode="json")
            if review.route == "customer" and review.customer_candidate is not None
            else review.supplier_candidate.model_dump(mode="json")
            if review.supplier_candidate is not None
            else None
        )
    return {key: value for key, value in payload.items() if value is not None}
