from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel

from src.core.mail import MailSendResult, OutboundMailSender
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import record_mina_job_customer_quote_sent
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case import (
    CustomerQuoteAutomatedSendState,
    CustomerQuoteAutomatedSentEvidence,
    CustomerQuoteSendReconciliationEvidence,
    QuoteCase,
)
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_final_output import (
    QuoteFinalOutputNotFoundError,
    QuoteFinalOutputTransitionError,
    build_quote_final_output,
)
from src.core.sqlite_repositories import atomic_repository_transaction
from src.workflow.mail_delivery import CustomerQuoteMailDeliveryResult, send_customer_quote_via_mail


class CustomerQuoteAutomatedSentNotFoundError(LookupError):
    pass


class CustomerQuoteAutomatedSentTransitionError(ValueError):
    pass


class CustomerQuoteAutomatedSentResult(BaseModel):
    quote_case: QuoteCase
    delivery: MailSendResult
    automated_sent_evidence: CustomerQuoteAutomatedSentEvidence | None = None
    source: str = "customer_quote_automated_sent_service"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _require_current_sendable_case(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
    approval_id: str,
) -> tuple[QuoteCase, int]:
    quote_case = quote_case_repository.get(case_id)
    if quote_case is None:
        raise CustomerQuoteAutomatedSentNotFoundError(f"Quote case not found: {case_id}")
    if quote_case.quote_approval is None:
        raise CustomerQuoteAutomatedSentTransitionError("Quote case has no current approval.")
    if quote_case.quote_approval.approval_id != approval_id:
        raise CustomerQuoteAutomatedSentTransitionError(
            "Automated customer quote send is stale because the current approval has changed."
        )
    revision_number = len(quote_case.quote_revisions)
    if any(
        item.approval_id == approval_id and item.revision_number == revision_number
        for item in quote_case.manual_sent_evidence
    ):
        raise CustomerQuoteAutomatedSentTransitionError(
            "Current customer quote revision already has manual send evidence."
        )
    if any(
        item.approval_id == approval_id and item.revision_number == revision_number
        for item in quote_case.automated_sent_evidence
    ):
        raise CustomerQuoteAutomatedSentTransitionError(
            "Current customer quote revision already has automated send evidence."
        )
    try:
        build_quote_final_output(
            quote_case_repository=quote_case_repository,
            approval_repository=approval_repository,
            case_id=case_id,
        )
    except QuoteFinalOutputNotFoundError as exc:
        raise CustomerQuoteAutomatedSentNotFoundError(str(exc)) from exc
    except QuoteFinalOutputTransitionError as exc:
        raise CustomerQuoteAutomatedSentTransitionError(str(exc)) from exc
    if quote_case.supplier_quote is None or quote_case.customer_quote is None or quote_case.quote_draft is None:
        raise CustomerQuoteAutomatedSentTransitionError("Quote case is incomplete for delivery.")
    return quote_case, revision_number


def _reserve_send(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
    approval_id: str,
    recipient_email: str,
    triggered_by: str,
) -> tuple[QuoteCase, int, int]:
    with atomic_repository_transaction(quote_case_repository, approval_repository):
        quote_case, revision_number = _require_current_sendable_case(
            quote_case_repository=quote_case_repository,
            approval_repository=approval_repository,
            case_id=case_id,
            approval_id=approval_id,
        )
        current = quote_case.automated_send_state
        same_revision = bool(
            current is not None
            and current.approval_id == approval_id
            and current.revision_number == revision_number
        )
        if same_revision and current.status in {
            "sending", "sent", "delivery_outcome_unknown"
        }:
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote delivery is already reserved, sent, or has an unknown provider outcome."
            )
        attempt_count = (current.attempt_count + 1) if same_revision else 1
        state = CustomerQuoteAutomatedSendState(
            approval_id=approval_id,
            revision_number=revision_number,
            recipient_email=recipient_email,
            status="sending",
            attempt_count=attempt_count,
            reserved_by=triggered_by,
            reserved_at=_now(),
        )
        reserved_case = quote_case_repository.save(
            QuoteCase.model_validate(
                quote_case.model_copy(
                    update={"automated_send_state": state, "updated_at": state.reserved_at}
                ).model_dump()
            )
        )
        return reserved_case, revision_number, attempt_count


def _complete_non_sent(
    *,
    quote_case_repository: QuoteCaseRepository,
    case_id: str,
    approval_id: str,
    revision_number: int,
    attempt_count: int,
    delivery: MailSendResult,
) -> QuoteCase:
    with atomic_repository_transaction(quote_case_repository):
        current = quote_case_repository.get(case_id)
        if current is None:
            raise CustomerQuoteAutomatedSentNotFoundError(f"Quote case not found: {case_id}")
        state = current.automated_send_state
        if (
            state is None
            or state.approval_id != approval_id
            or state.revision_number != revision_number
            or state.attempt_count != attempt_count
            or state.status != "sending"
        ):
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote send reservation changed before provider outcome was recorded."
            )
        next_status = (
            "delivery_outcome_unknown"
            if delivery.status == "delivery_outcome_unknown"
            else "failed"
        )
        updated_state = state.model_copy(
            update={
                "status": next_status,
                "completed_at": _now(),
                "provider_name": delivery.provider_name,
                "failure_code": delivery.status,
            }
        )
        return quote_case_repository.save(
            QuoteCase.model_validate(
                current.model_copy(
                    update={"automated_send_state": updated_state, "updated_at": updated_state.completed_at}
                ).model_dump()
            )
        )


def reconcile_customer_quote_delivery(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
    expected_approval_id: str,
    outcome: str,
    reconciled_by: str,
    observed_sent_at: datetime | None = None,
    note: str | None = None,
    reconciled_at: datetime | None = None,
    mina_job_repository: MinaJobRepository | None = None,
) -> QuoteCase:
    normalized_case_id = case_id.strip()
    normalized_approval_id = expected_approval_id.strip()
    actor = reconciled_by.strip()
    if outcome not in {"confirmed_sent", "confirmed_not_sent"}:
        raise ValueError("Customer quote reconciliation outcome is invalid.")
    if not actor:
        raise ValueError("Customer quote reconciliation requires an operator.")
    if outcome == "confirmed_sent" and observed_sent_at is None:
        raise ValueError("Confirmed sent reconciliation requires the observed Outlook sent time.")
    if observed_sent_at is not None and observed_sent_at.tzinfo is None:
        raise ValueError("Observed Outlook sent time must include timezone information.")
    timestamp = reconciled_at or _now()
    normalized_note = note.strip() if note and note.strip() else None
    with atomic_repository_transaction(
        quote_case_repository, approval_repository, mina_job_repository
    ):
        current = quote_case_repository.get(normalized_case_id)
        if current is None:
            raise CustomerQuoteAutomatedSentNotFoundError(
                f"Quote case not found: {normalized_case_id}"
            )
        state = current.automated_send_state
        revision_number = len(current.quote_revisions)
        if (
            current.quote_approval is None
            or current.quote_approval.approval_id != normalized_approval_id
            or state is None
            or state.approval_id != normalized_approval_id
            or state.revision_number != revision_number
            or state.status != "delivery_outcome_unknown"
        ):
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote reconciliation requires the current unknown provider outcome."
            )
        evidence = CustomerQuoteSendReconciliationEvidence(
            case_id=current.case_id,
            approval_id=normalized_approval_id,
            revision_number=revision_number,
            recipient_email=state.recipient_email,
            attempt_count=state.attempt_count,
            outcome=outcome,
            reconciled_by=actor,
            reconciled_at=timestamp,
            observed_sent_at=observed_sent_at,
            note=normalized_note,
        )
        next_state = state.model_copy(update={
            "status": "sent" if outcome == "confirmed_sent" else "failed",
            "completed_at": timestamp,
            "failure_code": None if outcome == "confirmed_sent" else "operator_reconciled_not_sent",
        })
        updated = quote_case_repository.save(
            QuoteCase.model_validate(
                current.model_copy(update={
                    "automated_send_state": next_state,
                    "send_reconciliation_evidence": [
                        *current.send_reconciliation_evidence, evidence
                    ],
                    "updated_at": timestamp,
                }).model_dump()
            )
        )
        if outcome == "confirmed_sent" and mina_job_repository is not None and updated.mina_job_id:
            record_mina_job_customer_quote_sent(
                repository=mina_job_repository,
                job_id=updated.mina_job_id,
                actor=actor,
                revision_number=revision_number,
                send_mode="provider_outcome_reconciled",
                occurred_at=observed_sent_at,
            )
        return updated


def send_customer_quote_and_record(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
    expected_approval_id: str,
    recipient_email: str,
    sender: OutboundMailSender | None,
    mina_job_repository: MinaJobRepository | None = None,
    triggered_by: str = "MINAI automation",
) -> CustomerQuoteAutomatedSentResult:
    normalized_case_id = case_id.strip()
    normalized_approval_id = expected_approval_id.strip()
    normalized_recipient = recipient_email.strip().casefold()
    actor = triggered_by.strip()
    if not normalized_case_id:
        raise ValueError("Quote case ID is required.")
    if not normalized_approval_id:
        raise ValueError("Expected approval ID is required.")
    if not normalized_recipient or "@" not in normalized_recipient:
        raise ValueError("Customer quote recipient email is required.")
    if not actor:
        raise ValueError("Customer quote delivery trigger identity is required.")

    reserved_case, revision_number, attempt_count = _reserve_send(
        quote_case_repository=quote_case_repository,
        approval_repository=approval_repository,
        case_id=normalized_case_id,
        approval_id=normalized_approval_id,
        recipient_email=normalized_recipient,
        triggered_by=actor,
    )
    current_approval = approval_repository.get(normalized_approval_id)
    if current_approval is None:
        raise CustomerQuoteAutomatedSentNotFoundError(
            f"Quote approval not found: {normalized_approval_id}"
        )

    mail_result: CustomerQuoteMailDeliveryResult = send_customer_quote_via_mail(
        recipient_email=normalized_recipient,
        approval=current_approval,
        supplier_quote=reserved_case.supplier_quote,
        customer_quote=reserved_case.customer_quote,
        quote_draft=reserved_case.quote_draft,
        sender=sender,
        regulatory_compliance=reserved_case.regulatory_compliance,
    )
    delivery = mail_result.delivery
    if delivery.status != "sent":
        updated_case = _complete_non_sent(
            quote_case_repository=quote_case_repository,
            case_id=normalized_case_id,
            approval_id=normalized_approval_id,
            revision_number=revision_number,
            attempt_count=attempt_count,
            delivery=delivery,
        )
        return CustomerQuoteAutomatedSentResult(quote_case=updated_case, delivery=delivery)
    if delivery.provider_name is None or delivery.provider_message_id is None or delivery.sent_at is None:
        unknown = MailSendResult(
            operation_id=delivery.operation_id,
            status="delivery_outcome_unknown",
            reason="Provider reported send success without complete durable metadata; retry is blocked.",
            provider_name=delivery.provider_name,
        )
        updated_case = _complete_non_sent(
            quote_case_repository=quote_case_repository,
            case_id=normalized_case_id,
            approval_id=normalized_approval_id,
            revision_number=revision_number,
            attempt_count=attempt_count,
            delivery=unknown,
        )
        return CustomerQuoteAutomatedSentResult(quote_case=updated_case, delivery=unknown)

    evidence = CustomerQuoteAutomatedSentEvidence(
        case_id=normalized_case_id,
        approval_id=normalized_approval_id,
        revision_number=revision_number,
        recipient_email=normalized_recipient,
        provider_name=delivery.provider_name,
        provider_message_id=delivery.provider_message_id,
        sent_at=delivery.sent_at,
        triggered_by=actor,
    )
    with atomic_repository_transaction(
        quote_case_repository, approval_repository, mina_job_repository
    ):
        current_case = quote_case_repository.get(normalized_case_id)
        if current_case is None:
            raise CustomerQuoteAutomatedSentNotFoundError(
                f"Quote case not found: {normalized_case_id}"
            )
        state = current_case.automated_send_state
        if (
            state is None
            or state.approval_id != normalized_approval_id
            or state.revision_number != revision_number
            or state.attempt_count != attempt_count
            or state.status != "sending"
        ):
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote send reservation changed after provider delivery."
            )
        if current_case.quote_approval is None or current_case.quote_approval.approval_id != normalized_approval_id:
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote approval changed after provider delivery."
            )
        if len(current_case.quote_revisions) != revision_number:
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote revision changed after provider delivery."
            )
        sent_state = state.model_copy(
            update={
                "status": "sent",
                "completed_at": delivery.sent_at,
                "provider_name": delivery.provider_name,
                "provider_message_id": delivery.provider_message_id,
                "failure_code": None,
            }
        )
        updated_case = quote_case_repository.save(
            QuoteCase.model_validate(
                current_case.model_copy(
                    update={
                        "automated_sent_evidence": [*current_case.automated_sent_evidence, evidence],
                        "automated_send_state": sent_state,
                        "updated_at": delivery.sent_at,
                    }
                ).model_dump()
            )
        )
        if mina_job_repository is not None and updated_case.mina_job_id:
            record_mina_job_customer_quote_sent(
                repository=mina_job_repository,
                job_id=updated_case.mina_job_id,
                actor=actor,
                revision_number=revision_number,
                send_mode="automated_provider",
                occurred_at=delivery.sent_at,
            )

    return CustomerQuoteAutomatedSentResult(
        quote_case=updated_case,
        delivery=delivery,
        automated_sent_evidence=evidence,
    )
