from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from src.core.mail import (
    MailSendStatus,
    MailSendResult,
    OutboundMailRequest,
    OutboundMailSender,
)
from src.core.models import CustomerQuote, QuoteDraft, SupplierQuote
from src.core.quote_approval import QuoteApproval
from src.core.quote_send_service import (
    QuoteSendServiceResult,
    prepare_quote_for_sending,
)
from src.core.regulatory_compliance import RegulatoryComplianceAssessment
from src.core.supplier_rfq import (
    SupplierRFQAutomatedSentEvidence,
    SupplierRFQDraft,
)
from src.core.supplier_rfq_lifecycle import (
    SupplierRFQNotFoundError,
    SupplierRFQTransitionError,
    send_supplier_rfq,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQAutomatedSentEvidenceError,
    SupplierRFQRepository,
)
from src.core.sqlite_repositories import atomic_repository_transaction


class SupplierRFQMailDeliveryResult(BaseModel):
    supplier_rfq: SupplierRFQDraft
    mail_request: Optional[OutboundMailRequest] = None
    delivery: MailSendResult
    automated_sent_evidence: Optional[SupplierRFQAutomatedSentEvidence] = None
    source: str = "supplier_rfq_mail_delivery"


class CustomerQuoteMailDeliveryResult(BaseModel):
    preparation: QuoteSendServiceResult
    delivery: MailSendResult
    source: str = "customer_quote_mail_delivery"


def _controlled_result(
    *,
    operation_id: str,
    status: MailSendStatus,
    reason: str,
) -> MailSendResult:
    return MailSendResult(
        operation_id=operation_id,
        status=status,
        reason=reason,
    )


def dispatch_outbound_mail(
    request: OutboundMailRequest,
    sender: OutboundMailSender | None,
) -> MailSendResult:
    if sender is None:
        return _controlled_result(
            operation_id=request.operation_id,
            status="provider_unavailable",
            reason="No outbound mail provider is configured.",
        )

    try:
        raw_result = sender.send(request)
        result = MailSendResult.model_validate(raw_result)
    except Exception:
        return _controlled_result(
            operation_id=request.operation_id,
            status="failed",
            reason="The outbound mail provider failed safely.",
        )

    if result.operation_id != request.operation_id:
        return _controlled_result(
            operation_id=request.operation_id,
            status="failed",
            reason="The provider result did not match the outbound operation.",
        )

    return result


def build_supplier_rfq_mail_request(
    draft: SupplierRFQDraft,
) -> OutboundMailRequest:
    if not draft.recipient_email:
        raise ValueError("Supplier RFQ recipient email is required.")
    return OutboundMailRequest(
        operation_id=f"supplier-rfq:{draft.rfq_id}",
        recipients=[draft.recipient_email],
        subject=draft.subject,
        body_text=draft.body,
        purpose="supplier_rfq",
        correlation_reference=draft.reference_token,
        reference_metadata={
            "rfq_id": draft.rfq_id,
            "workflow_id": draft.workflow_id,
        },
    )


def send_supplier_rfq_via_mail(
    *,
    repository: SupplierRFQRepository,
    rfq_id: str,
    sender: OutboundMailSender | None,
) -> SupplierRFQMailDeliveryResult:
    draft = repository.get_draft(rfq_id)
    if draft is None:
        raise SupplierRFQNotFoundError(f"Supplier RFQ not found: {rfq_id}")

    operation_id = f"supplier-rfq:{rfq_id}"
    if draft.status != "approved":
        return SupplierRFQMailDeliveryResult(
            supplier_rfq=draft,
            delivery=_controlled_result(
                operation_id=operation_id,
                status="rejected_before_provider",
                reason=(
                    "Supplier RFQ must be approved and unsent before delivery; "
                    f"current status is {draft.status}."
                ),
            ),
        )
    if not draft.has_recipient:
        return SupplierRFQMailDeliveryResult(
            supplier_rfq=draft,
            delivery=_controlled_result(
                operation_id=operation_id,
                status="rejected_before_provider",
                reason="Supplier RFQ has no recipient email.",
            ),
        )
    if repository.list_manual_sent_evidence(rfq_id):
        return SupplierRFQMailDeliveryResult(
            supplier_rfq=draft,
            delivery=_controlled_result(
                operation_id=operation_id,
                status="rejected_before_provider",
                reason="Supplier RFQ already has manual send evidence.",
            ),
        )
    if repository.list_automated_sent_evidence(rfq_id):
        return SupplierRFQMailDeliveryResult(
            supplier_rfq=draft,
            delivery=_controlled_result(
                operation_id=operation_id,
                status="rejected_before_provider",
                reason="Supplier RFQ already has automated send evidence.",
            ),
        )

    request = build_supplier_rfq_mail_request(draft)
    delivery = dispatch_outbound_mail(request, sender)
    if delivery.status != "sent":
        return SupplierRFQMailDeliveryResult(
            supplier_rfq=draft,
            mail_request=request,
            delivery=delivery,
        )
    if (
        delivery.provider_name is None
        or delivery.provider_message_id is None
        or delivery.sent_at is None
    ):
        return SupplierRFQMailDeliveryResult(
            supplier_rfq=draft,
            mail_request=request,
            delivery=_controlled_result(
                operation_id=operation_id,
                status="failed",
                reason="Sent Supplier RFQ result is missing durable provider metadata.",
            ),
        )

    evidence = SupplierRFQAutomatedSentEvidence(
        rfq_id=rfq_id,
        recipient_email=draft.recipient_email or "",
        provider_name=delivery.provider_name,
        provider_message_id=delivery.provider_message_id,
        sent_at=delivery.sent_at,
    )
    with atomic_repository_transaction(repository):
        current = repository.get_draft(rfq_id)
        if current is None:
            raise SupplierRFQNotFoundError(f"Supplier RFQ not found: {rfq_id}")
        if current != draft:
            raise SupplierRFQTransitionError(
                "Supplier RFQ changed after provider delivery; automated evidence was not attached to stale state."
            )
        if repository.list_manual_sent_evidence(rfq_id):
            raise SupplierRFQTransitionError(
                "Supplier RFQ received manual send evidence after provider delivery."
            )
        if repository.list_automated_sent_evidence(rfq_id):
            raise SupplierRFQTransitionError(
                "Supplier RFQ already has automated send evidence."
            )
        awaiting = send_supplier_rfq(
            repository=repository,
            rfq_id=rfq_id,
            send_result=delivery,
        )
        try:
            evidence = repository.save_automated_sent_evidence(evidence)
        except DuplicateSupplierRFQAutomatedSentEvidenceError as exc:
            raise SupplierRFQTransitionError(str(exc)) from exc

    return SupplierRFQMailDeliveryResult(
        supplier_rfq=awaiting,
        mail_request=request,
        delivery=delivery,
        automated_sent_evidence=evidence,
    )


def send_customer_quote_via_mail(
    *,
    recipient_email: str,
    approval: QuoteApproval | None,
    supplier_quote: SupplierQuote,
    customer_quote: CustomerQuote,
    quote_draft: QuoteDraft,
    sender: OutboundMailSender | None,
    regulatory_compliance: RegulatoryComplianceAssessment | None = None,
) -> CustomerQuoteMailDeliveryResult:
    preparation = prepare_quote_for_sending(
        recipient_email=recipient_email,
        approval=approval,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        regulatory_compliance=regulatory_compliance,
    )
    if preparation.status != "send_ready" or preparation.mail_request is None:
        approval_reference = approval.approval_id if approval else "missing"
        return CustomerQuoteMailDeliveryResult(
            preparation=preparation,
            delivery=_controlled_result(
                operation_id=f"customer-quote:{approval_reference}",
                status="rejected_before_provider",
                reason=preparation.safety_decision.reason,
            ),
        )

    delivery = dispatch_outbound_mail(preparation.mail_request, sender)
    return CustomerQuoteMailDeliveryResult(
        preparation=preparation,
        delivery=delivery,
    )


def prepare_clarification_mail_request(
    *,
    recipient_email: str,
    clarification_draft: QuoteDraft,
    operation_id: str,
    correlation_reference: str | None = None,
) -> OutboundMailRequest:
    metadata = (
        {"workflow_reference": correlation_reference}
        if correlation_reference
        else {}
    )
    return OutboundMailRequest(
        operation_id=operation_id,
        recipients=[recipient_email],
        subject=clarification_draft.subject,
        body_text=clarification_draft.body,
        purpose="customer_clarification",
        correlation_reference=correlation_reference,
        reference_metadata=metadata,
    )
