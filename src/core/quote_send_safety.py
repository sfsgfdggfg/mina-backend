from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    SupplierQuote,
)
from src.core.quote_approval import QuoteApproval
from src.core.regulatory_compliance import (
    RegulatoryComplianceAssessment,
)


QuoteSendBlockReason = Literal[
    "approval_missing",
    "approval_pending",
    "approval_rejected",
    "approval_invalidated",
    "quote_snapshot_mismatch",
    "regulatory_compliance_blocked",
    "regulatory_review_pending",
]


class QuoteSendSafetyDecision(BaseModel):
    can_send: bool
    reason: str
    block_reason: QuoteSendBlockReason | None = None
    approval_id: str | None = None
    approved_by: str | None = None
    source: str = "quote_send_safety_engine"


def evaluate_quote_send_safety(
    approval: QuoteApproval | None,
    supplier_quote: SupplierQuote,
    customer_quote: CustomerQuote,
    quote_draft: QuoteDraft,
    regulatory_compliance: RegulatoryComplianceAssessment | None = None,
) -> QuoteSendSafetyDecision:
    if (
        regulatory_compliance is not None
        and not regulatory_compliance.can_continue_to_quote
    ):
        review_pending = (
            regulatory_compliance.status
            == "human_review_required"
        )
        return QuoteSendSafetyDecision(
            can_send=False,
            block_reason=(
                "regulatory_review_pending"
                if review_pending
                else "regulatory_compliance_blocked"
            ),
            reason=(
                "Teklif gönderilemez. Düzenleyici belge istisnası "
                "için açık insan onayı bekleniyor."
                if review_pending
                else (
                    "Teklif gönderilemez. Düzenleyici belge "
                    "uygunluk kapısı geçilmedi."
                )
            ),
        )

    if approval is None:
        return QuoteSendSafetyDecision(
            can_send=False,
            block_reason="approval_missing",
            reason=(
                "Teklif gönderilemez. İnsan onay kaydı bulunmuyor."
            ),
        )

    if approval.approval_status == "pending":
        return QuoteSendSafetyDecision(
            can_send=False,
            block_reason="approval_pending",
            approval_id=approval.approval_id,
            reason=(
                "Teklif gönderilemez. İnsan onayı henüz bekleniyor."
            ),
        )

    if approval.approval_status == "rejected":
        return QuoteSendSafetyDecision(
            can_send=False,
            block_reason="approval_rejected",
            approval_id=approval.approval_id,
            reason=(
                "Teklif gönderilemez. Onay kaydı reddedilmiş."
            ),
        )

    if approval.approval_status == "invalidated":
        return QuoteSendSafetyDecision(
            can_send=False,
            block_reason="approval_invalidated",
            approval_id=approval.approval_id,
            reason=(
                "Teklif gönderilemez. Önceki onay geçersiz kılınmış."
            ),
        )

    if not approval.is_valid_for_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    ):
        return QuoteSendSafetyDecision(
            can_send=False,
            block_reason="quote_snapshot_mismatch",
            approval_id=approval.approval_id,
            approved_by=approval.approved_by,
            reason=(
                "Teklif gönderilemez. Onaylanan teklif snapshot'ı "
                "güncel teklif ile eşleşmiyor."
            ),
        )

    return QuoteSendSafetyDecision(
        can_send=True,
        approval_id=approval.approval_id,
        approved_by=approval.approved_by,
        reason=(
            "Teklif gönderilebilir. Geçerli insan onayı mevcut ve "
            "onay snapshot'ı güncel teklif ile eşleşiyor."
        ),
    )
