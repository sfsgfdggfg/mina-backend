from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    Shipment,
    SupplierQuote,
)
from src.core.quote_approval import QuoteApproval
from src.core.quote_revision import QuoteRevision
from src.core.quote_send_safety import QuoteSendSafetyDecision
from src.core.regulatory_compliance import (
    RegulatoryComplianceAssessment,
)
from src.core.supplier_quote_selection import (
    SupplierQuoteSelectionDecision,
)


class CustomerQuoteManualSentEvidence(BaseModel):
    case_id: str
    approval_id: str
    revision_number: int = Field(ge=0)
    recipient_email: str
    sent_by: str
    sent_at: datetime
    source: Literal["manual_external_send"] = "manual_external_send"


class CustomerQuoteAutomatedSentEvidence(BaseModel):
    case_id: str
    approval_id: str
    revision_number: int = Field(ge=0)
    recipient_email: str
    provider_name: str
    provider_message_id: str
    sent_at: datetime
    triggered_by: Optional[str] = None
    source: Literal["automated_provider_send"] = "automated_provider_send"


class CustomerQuoteSendReconciliationEvidence(BaseModel):
    case_id: str
    approval_id: str
    revision_number: int = Field(ge=0)
    recipient_email: str
    attempt_count: int = Field(ge=1)
    outcome: Literal["confirmed_sent", "confirmed_not_sent"]
    reconciled_by: str
    reconciled_at: datetime
    observed_sent_at: Optional[datetime] = None
    note: Optional[str] = Field(default=None, max_length=1000)
    source: Literal["operator_provider_reconciliation"] = "operator_provider_reconciliation"


CustomerQuoteAutomatedSendStatus = Literal[
    "sending",
    "sent",
    "failed",
    "delivery_outcome_unknown",
]


class CustomerQuoteAutomatedSendState(BaseModel):
    approval_id: str
    revision_number: int = Field(ge=0)
    recipient_email: str
    status: CustomerQuoteAutomatedSendStatus
    attempt_count: int = Field(default=1, ge=1)
    reserved_by: str
    reserved_at: datetime
    completed_at: Optional[datetime] = None
    provider_name: Optional[str] = None
    provider_message_id: Optional[str] = None
    failure_code: Optional[str] = None
    source: str = "customer_quote_automated_send_state"


class QuoteCase(BaseModel):
    case_id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    shipment: Shipment
    mina_job_id: Optional[str] = None
    mina_code: Optional[str] = None
    supplier_rfq_workflow_id: Optional[str] = None

    supplier_quote_selection_decision: Optional[
        SupplierQuoteSelectionDecision
    ] = None

    supplier_quote: Optional[SupplierQuote] = None
    customer_quote: Optional[CustomerQuote] = None
    quote_draft: Optional[QuoteDraft] = None

    quote_approval: Optional[QuoteApproval] = None
    quote_send_safety: Optional[QuoteSendSafetyDecision] = None
    regulatory_compliance: Optional[
        RegulatoryComplianceAssessment
    ] = None

    quote_revisions: list[QuoteRevision] = Field(
        default_factory=list
    )
    manual_sent_evidence: list[
        CustomerQuoteManualSentEvidence
    ] = Field(default_factory=list)
    automated_sent_evidence: list[
        CustomerQuoteAutomatedSentEvidence
    ] = Field(default_factory=list)
    send_reconciliation_evidence: list[
        CustomerQuoteSendReconciliationEvidence
    ] = Field(default_factory=list)

    automated_send_state: Optional[CustomerQuoteAutomatedSendState] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    source: str = "quote_case"
