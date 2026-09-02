from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import record_mina_job_customer_quote_sent
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case import CustomerQuoteManualSentEvidence, QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_final_output import (
    QuoteFinalOutputNotFoundError,
    QuoteFinalOutputTransitionError,
    build_quote_final_output,
)
from src.core.sqlite_repositories import atomic_repository_transaction


class CustomerQuoteManualSentNotFoundError(LookupError):
    pass


class CustomerQuoteManualSentTransitionError(ValueError):
    pass


class CustomerQuoteManualSentResult(BaseModel):
    quote_case: QuoteCase
    manual_sent_evidence: CustomerQuoteManualSentEvidence
    source: str = "customer_quote_manual_sent_service"


def record_customer_quote_manually_sent(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
    expected_approval_id: str,
    recipient_email: str,
    sent_by: str,
    sent_at: datetime | None = None,
    mina_job_repository: MinaJobRepository | None = None,
) -> CustomerQuoteManualSentResult:
    normalized_case_id = case_id.strip()
    normalized_approval_id = expected_approval_id.strip()
    normalized_recipient = recipient_email.strip().lower()
    normalized_operator = sent_by.strip()

    if not normalized_case_id:
        raise ValueError("Quote case ID is required.")
    if not normalized_approval_id:
        raise ValueError("Expected approval ID is required.")
    if not normalized_recipient or "@" not in normalized_recipient:
        raise ValueError("Customer quote recipient email is required.")
    if not normalized_operator:
        raise ValueError("Customer quote send recorder identity is required.")

    timestamp = sent_at or datetime.utcnow()

    with atomic_repository_transaction(
        quote_case_repository,
        approval_repository,
        mina_job_repository,
    ):
        quote_case = quote_case_repository.get(normalized_case_id)
        if quote_case is None:
            raise CustomerQuoteManualSentNotFoundError(
                f"Quote case not found: {normalized_case_id}"
            )

        if quote_case.quote_approval is None:
            raise CustomerQuoteManualSentTransitionError(
                "Quote case has no current approval."
            )

        current_approval_id = quote_case.quote_approval.approval_id
        if current_approval_id != normalized_approval_id:
            raise CustomerQuoteManualSentTransitionError(
                "Manual customer quote send is stale because the current approval has changed."
            )

        revision_number = len(quote_case.quote_revisions)
        if any(
            item.approval_id == normalized_approval_id
            and item.revision_number == revision_number
            for item in quote_case.manual_sent_evidence
        ):
            raise CustomerQuoteManualSentTransitionError(
                "Current customer quote revision already has manual send evidence."
            )
        if any(
            item.approval_id == normalized_approval_id
            and item.revision_number == revision_number
            for item in quote_case.automated_sent_evidence
        ):
            raise CustomerQuoteManualSentTransitionError(
                "Current customer quote revision already has automated send evidence."
            )

        try:
            build_quote_final_output(
                quote_case_repository=quote_case_repository,
                approval_repository=approval_repository,
                case_id=normalized_case_id,
            )
        except QuoteFinalOutputNotFoundError as exc:
            raise CustomerQuoteManualSentNotFoundError(str(exc)) from exc
        except QuoteFinalOutputTransitionError as exc:
            raise CustomerQuoteManualSentTransitionError(str(exc)) from exc

        evidence = CustomerQuoteManualSentEvidence(
            case_id=normalized_case_id,
            approval_id=normalized_approval_id,
            revision_number=revision_number,
            recipient_email=normalized_recipient,
            sent_by=normalized_operator,
            sent_at=timestamp,
        )

        updated_case = QuoteCase.model_validate(
            quote_case.model_copy(
                update={
                    "manual_sent_evidence": [
                        *quote_case.manual_sent_evidence,
                        evidence,
                    ],
                    "updated_at": timestamp,
                }
            ).model_dump()
        )
        updated_case = quote_case_repository.save(updated_case)
        if mina_job_repository is not None and updated_case.mina_job_id:
            record_mina_job_customer_quote_sent(
                repository=mina_job_repository,
                job_id=updated_case.mina_job_id,
                actor=normalized_operator,
                revision_number=revision_number,
                send_mode="manual_external",
                occurred_at=timestamp,
            )

    return CustomerQuoteManualSentResult(
        quote_case=updated_case,
        manual_sent_evidence=evidence,
    )
