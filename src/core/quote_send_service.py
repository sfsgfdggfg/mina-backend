from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    SupplierQuote,
)
from src.core.quote_approval import QuoteApproval
from src.core.quote_send_safety import (
    QuoteSendSafetyDecision,
    evaluate_quote_send_safety,
)


QuoteSendServiceStatus = Literal[
    "blocked",
    "send_ready",
]


class QuoteSendServiceResult(BaseModel):
    status: QuoteSendServiceStatus
    sent: bool = False
    recipient_email: str
    subject: str
    body: str

    safety_decision: QuoteSendSafetyDecision

    message: str
    source: str = "quote_send_service"


def prepare_quote_for_sending(
    recipient_email: str,
    approval: QuoteApproval | None,
    supplier_quote: SupplierQuote,
    customer_quote: CustomerQuote,
    quote_draft: QuoteDraft,
) -> QuoteSendServiceResult:
    normalized_recipient = recipient_email.strip()

    if not normalized_recipient:
        raise ValueError(
            "Quote recipient email must not be empty."
        )

    safety_decision = evaluate_quote_send_safety(
        approval=approval,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )

    if not safety_decision.can_send:
        return QuoteSendServiceResult(
            status="blocked",
            sent=False,
            recipient_email=normalized_recipient,
            subject=quote_draft.subject,
            body=quote_draft.body,
            safety_decision=safety_decision,
            message=(
                "Teklif gönderime hazırlanmadı. "
                f"{safety_decision.reason}"
            ),
        )

    return QuoteSendServiceResult(
        status="send_ready",
        sent=False,
        recipient_email=normalized_recipient,
        subject=quote_draft.subject,
        body=quote_draft.body,
        safety_decision=safety_decision,
        message=(
            "Teklif gönderime hazır. Gerçek e-posta gönderimi "
            "henüz çalıştırılmadı."
        ),
    )
