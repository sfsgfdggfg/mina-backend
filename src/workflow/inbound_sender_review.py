from __future__ import annotations

from datetime import datetime, timezone

from src.core.inbound_sender_review import (
    InboundSenderReview,
    inbound_review_message_hash,
)
from src.core.inbound_sender_review_repository import InboundSenderReviewRepository
from src.core.mail import InboundMailEnvelope


REVIEWABLE_RESULT_TYPES = {
    "inbound_sender_verification_required",
}
REVIEWABLE_REASON_CODES = {
    "sender_not_in_verified_inbound_scope",
    "sender_not_in_verified_pilot_scope",
    "sender_matches_multiple_pilot_customers",
    "sender_matches_multiple_verified_customers",
}


def capture_inbound_sender_review(
    *,
    mail: InboundMailEnvelope,
    result: dict,
    repository: InboundSenderReviewRepository | None,
    now: datetime | None = None,
) -> InboundSenderReview | None:
    if repository is None:
        return None
    result_type = str(result.get("result_type") or "")
    reason_code = str(result.get("reason_code") or "")
    if result_type not in REVIEWABLE_RESULT_TYPES:
        return None
    if reason_code not in REVIEWABLE_REASON_CODES:
        return None
    message_key = mail.message_deduplication_key
    if not message_key:
        return None
    digest = inbound_review_message_hash(message_key)
    existing = repository.find_by_message_hash(digest)
    if existing is not None:
        return existing

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Inbound sender review timestamp must be timezone-aware.")
    received = mail.received_at or current
    review = InboundSenderReview(
        provider=mail.provider_name or "unknown",
        mailbox_id=mail.mailbox_id or "",
        external_message_id=mail.external_message_id or "",
        message_key_sha256=digest,
        sender_address=mail.sender_address,
        sender_name=mail.sender_name,
        subject=mail.subject,
        received_at=received,
        reason_code=reason_code,
        result_type=result_type,
        created_at=current,
        updated_at=current,
    )
    return repository.save(review)


def resolve_inbound_sender_review(
    *,
    review: InboundSenderReview,
    repository: InboundSenderReviewRepository,
    resolution: str,
    resolved_by: str,
    resolved_subject_type: str | None = None,
    resolved_subject_id: str | None = None,
    resolved_subject_label: str | None = None,
    resolution_note: str | None = None,
    reprocess_result: dict | None = None,
    now: datetime | None = None,
) -> InboundSenderReview:
    if review.status != "pending":
        return review
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Inbound sender review resolution timestamp must be timezone-aware.")
    payload = {
        "status": "dismissed" if resolution == "irrelevant" else "resolved",
        "resolution": resolution,
        "resolved_subject_type": resolved_subject_type,
        "resolved_subject_id": resolved_subject_id,
        "resolved_subject_label": resolved_subject_label,
        "resolved_by": resolved_by,
        "resolution_note": resolution_note,
        "resolved_at": current,
        "updated_at": current,
    }
    if reprocess_result is not None:
        payload.update(
            {
                "reprocess_result_type": reprocess_result.get("result_type"),
                "reprocess_ingestion_status": reprocess_result.get("ingestion_status"),
                "reprocess_reason_code": reprocess_result.get("reason_code"),
            }
        )
    updated = InboundSenderReview.model_validate(
        review.model_copy(update=payload).model_dump(mode="json")
    )
    return repository.save(updated)
