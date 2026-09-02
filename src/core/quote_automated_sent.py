from datetime import datetime

from pydantic import BaseModel

from src.core.mail import MailSendResult, OutboundMailSender
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import record_mina_job_customer_quote_sent
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case import CustomerQuoteAutomatedSentEvidence, QuoteCase
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


def send_customer_quote_and_record(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
    expected_approval_id: str,
    recipient_email: str,
    sender: OutboundMailSender | None,
    mina_job_repository: MinaJobRepository | None = None,
) -> CustomerQuoteAutomatedSentResult:
    normalized_case_id = case_id.strip()
    normalized_approval_id = expected_approval_id.strip()
    normalized_recipient = recipient_email.strip().lower()
    if not normalized_case_id:
        raise ValueError("Quote case ID is required.")
    if not normalized_approval_id:
        raise ValueError("Expected approval ID is required.")
    if not normalized_recipient or "@" not in normalized_recipient:
        raise ValueError("Customer quote recipient email is required.")

    quote_case = quote_case_repository.get(normalized_case_id)
    if quote_case is None:
        raise CustomerQuoteAutomatedSentNotFoundError(
            f"Quote case not found: {normalized_case_id}"
        )
    if quote_case.quote_approval is None:
        raise CustomerQuoteAutomatedSentTransitionError("Quote case has no current approval.")
    if quote_case.quote_approval.approval_id != normalized_approval_id:
        raise CustomerQuoteAutomatedSentTransitionError(
            "Automated customer quote send is stale because the current approval has changed."
        )
    revision_number = len(quote_case.quote_revisions)
    if any(
        item.approval_id == normalized_approval_id and item.revision_number == revision_number
        for item in quote_case.manual_sent_evidence
    ):
        raise CustomerQuoteAutomatedSentTransitionError(
            "Current customer quote revision already has manual send evidence."
        )
    if any(
        item.approval_id == normalized_approval_id and item.revision_number == revision_number
        for item in quote_case.automated_sent_evidence
    ):
        raise CustomerQuoteAutomatedSentTransitionError(
            "Current customer quote revision already has automated send evidence."
        )

    try:
        build_quote_final_output(
            quote_case_repository=quote_case_repository,
            approval_repository=approval_repository,
            case_id=normalized_case_id,
        )
    except QuoteFinalOutputNotFoundError as exc:
        raise CustomerQuoteAutomatedSentNotFoundError(str(exc)) from exc
    except QuoteFinalOutputTransitionError as exc:
        raise CustomerQuoteAutomatedSentTransitionError(str(exc)) from exc

    current_approval = approval_repository.get(normalized_approval_id)
    if current_approval is None:
        raise CustomerQuoteAutomatedSentNotFoundError(
            f"Quote approval not found: {normalized_approval_id}"
        )
    if quote_case.supplier_quote is None or quote_case.customer_quote is None or quote_case.quote_draft is None:
        raise CustomerQuoteAutomatedSentTransitionError("Quote case is incomplete for delivery.")

    mail_result: CustomerQuoteMailDeliveryResult = send_customer_quote_via_mail(
        recipient_email=normalized_recipient,
        approval=current_approval,
        supplier_quote=quote_case.supplier_quote,
        customer_quote=quote_case.customer_quote,
        quote_draft=quote_case.quote_draft,
        sender=sender,
        regulatory_compliance=quote_case.regulatory_compliance,
    )
    delivery = mail_result.delivery
    if delivery.status != "sent":
        return CustomerQuoteAutomatedSentResult(
            quote_case=quote_case,
            delivery=delivery,
        )
    if delivery.provider_name is None or delivery.provider_message_id is None or delivery.sent_at is None:
        raise CustomerQuoteAutomatedSentTransitionError(
            "Sent delivery result is missing durable provider metadata."
        )

    evidence = CustomerQuoteAutomatedSentEvidence(
        case_id=normalized_case_id,
        approval_id=normalized_approval_id,
        revision_number=revision_number,
        recipient_email=normalized_recipient,
        provider_name=delivery.provider_name,
        provider_message_id=delivery.provider_message_id,
        sent_at=delivery.sent_at,
    )
    with atomic_repository_transaction(
        quote_case_repository, approval_repository, mina_job_repository
    ):
        current_case = quote_case_repository.get(normalized_case_id)
        if current_case is None:
            raise CustomerQuoteAutomatedSentNotFoundError(
                f"Quote case not found: {normalized_case_id}"
            )
        if current_case.quote_approval is None or current_case.quote_approval.approval_id != normalized_approval_id:
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote approval changed after provider delivery; evidence was not attached to a stale case."
            )
        if len(current_case.quote_revisions) != revision_number:
            raise CustomerQuoteAutomatedSentTransitionError(
                "Customer quote revision changed after provider delivery; evidence was not attached to a stale revision."
            )
        updated_case = QuoteCase.model_validate(
            current_case.model_copy(
                update={
                    "automated_sent_evidence": [*current_case.automated_sent_evidence, evidence],
                    "updated_at": delivery.sent_at or datetime.utcnow(),
                }
            ).model_dump()
        )
        updated_case = quote_case_repository.save(updated_case)
        if mina_job_repository is not None and updated_case.mina_job_id:
            record_mina_job_customer_quote_sent(
                repository=mina_job_repository,
                job_id=updated_case.mina_job_id,
                actor="MINAI automation",
                revision_number=revision_number,
                send_mode="automated_provider",
                occurred_at=delivery.sent_at,
            )

    return CustomerQuoteAutomatedSentResult(
        quote_case=updated_case,
        delivery=delivery,
        automated_sent_evidence=evidence,
    )
