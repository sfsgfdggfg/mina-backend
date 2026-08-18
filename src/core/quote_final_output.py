from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_send_safety import evaluate_quote_send_safety


class QuoteFinalOutputNotFoundError(LookupError):
    pass


class QuoteFinalOutputTransitionError(ValueError):
    pass


class QuoteFinalOutput(BaseModel):
    case_id: str
    approval_id: str
    approved_by: str
    approved_at: datetime
    revision_number: int

    subject: str
    body: str
    final_price: float
    currency: str

    delivery_mode: Literal[
        "manual_external_operation"
    ] = "manual_external_operation"
    automated_send_performed: Literal[False] = False

    source: str = "quote_final_output_service"


def build_quote_final_output(
    *,
    quote_case_repository: QuoteCaseRepository,
    approval_repository: QuoteApprovalRepository,
    case_id: str,
) -> QuoteFinalOutput:
    normalized_case_id = case_id.strip()

    if not normalized_case_id:
        raise ValueError("Quote case ID is required.")

    quote_case = quote_case_repository.get(normalized_case_id)

    if quote_case is None:
        raise QuoteFinalOutputNotFoundError(
            f"Quote case not found: {normalized_case_id}"
        )

    if (
        quote_case.supplier_quote is None
        or quote_case.customer_quote is None
        or quote_case.quote_draft is None
        or quote_case.quote_approval is None
    ):
        raise QuoteFinalOutputTransitionError(
            "Quote case is not complete enough for final output."
        )

    approval_id = quote_case.quote_approval.approval_id
    current_approval = approval_repository.get(approval_id)

    if current_approval is None:
        raise QuoteFinalOutputNotFoundError(
            f"Current quote approval not found: {approval_id}"
        )

    send_safety = evaluate_quote_send_safety(
        approval=current_approval,
        supplier_quote=quote_case.supplier_quote,
        customer_quote=quote_case.customer_quote,
        quote_draft=quote_case.quote_draft,
        regulatory_compliance=quote_case.regulatory_compliance,
    )

    if not send_safety.can_send:
        raise QuoteFinalOutputTransitionError(
            "Current quote is not approved for final manual handoff."
        )

    if (
        current_approval.approved_by is None
        or current_approval.approved_at is None
    ):
        raise QuoteFinalOutputTransitionError(
            "Approved quote is missing approval metadata."
        )

    return QuoteFinalOutput(
        case_id=quote_case.case_id,
        approval_id=current_approval.approval_id,
        approved_by=current_approval.approved_by,
        approved_at=current_approval.approved_at,
        revision_number=len(quote_case.quote_revisions),
        subject=quote_case.quote_draft.subject,
        body=quote_case.quote_draft.body,
        final_price=quote_case.customer_quote.final_price,
        currency=quote_case.customer_quote.currency,
    )
