from __future__ import annotations

from src.core.mail import OutboundMailRequest
from src.core.supplier_rfq import SupplierRFQDraft


_REASON_QUESTIONS = {
    "supplier_transit_missing_or_unparseable": (
        "Tahmini transit süreyi ve zaman birimini paylaşabilir misiniz?"
    ),
    "supplier_quote_expired": (
        "Fiyatı güncel olarak teyit edebilir misiniz?"
    ),
    "supplier_equipment_mismatch": (
        "Talep ettiğimiz araç / ekipman ile fiyatı teyit edebilir misiniz?"
    ),
    "supplier_price_has_unpriced_extras": (
        "Ek masraflar dahil toplam all-in navlun fiyatını paylaşabilir misiniz?"
    ),
    "supplier_has_excluded_costs": (
        "Hariç belirtilen masrafları da dahil ederek toplam all-in fiyatı teyit edebilir misiniz?"
    ),
}


def build_supplier_follow_up_draft(
    *,
    draft: SupplierRFQDraft,
    rejection_reasons: list[str],
    sequence_number: int = 1,
) -> OutboundMailRequest | None:
    questions = [
        question
        for reason in rejection_reasons
        if (question := _REASON_QUESTIONS.get(reason)) is not None
    ]
    questions = list(dict.fromkeys(questions))
    if not questions or not draft.recipient_email:
        return None

    question_text = "\n".join(f"- {item}" for item in questions)
    body = f"""
Merhaba,

Teklifiniz için teşekkür ederiz. Aşağıdaki RFQ için fiyat çalışmasını tamamlayabilmemiz adına şu bilgileri rica ederiz.

RFQ Referansı: {draft.reference_token}

{question_text}

Teşekkürler.

Saygılarımızla,
MINAI Freight OS
""".strip()

    return OutboundMailRequest(
        operation_id=(
            f"supplier-rfq-clarification:{draft.rfq_id}:"
            f"{sequence_number}"
        ),
        recipients=[draft.recipient_email],
        subject=f"Re: {draft.subject}",
        body_text=body,
        purpose="supplier_rfq",
        correlation_reference=draft.reference_token,
        reference_metadata={
            "rfq_id": draft.rfq_id,
            "action": "supplier_clarification",
        },
    )
