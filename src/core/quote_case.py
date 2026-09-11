from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

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


class SupplierDecisionOutcomeFeedback(BaseModel):
    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    job_id: str = Field(min_length=1, max_length=100)
    case_id: str = Field(min_length=1, max_length=100)
    supplier_name: str = Field(min_length=1, max_length=240)
    engine_recommended_supplier: Optional[str] = Field(default=None, max_length=240)
    override_applied: bool = False
    override_reason_category: Optional[str] = Field(default=None, max_length=80)
    overall_outcome: Literal["successful", "acceptable", "problematic"]
    communication_quality: Literal["good", "acceptable", "poor"]
    would_choose_again: Literal["yes", "unsure", "no"]
    delivered_at: datetime
    required_delivery_date: Optional[str] = Field(default=None, max_length=80)
    on_time_delivery: Optional[bool] = None
    operation_exception_count: int = Field(ge=0)
    actual_delay_count: int = Field(ge=0)
    damage_exception_count: int = Field(ge=0)
    operation_exception_ids: list[str] = Field(default_factory=list)
    operation_snapshot_updated_at: datetime
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    note: Optional[str] = Field(default=None, max_length=1200)
    source: Literal["supplier_decision_outcome_feedback_v1"] = "supplier_decision_outcome_feedback_v1"

    @field_validator("delivered_at", "operation_snapshot_updated_at", "recorded_at")
    @classmethod
    def require_aware_outcome_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Supplier decision outcome timestamps must be timezone-aware.")
        return value


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
    supplier_decision_outcome_feedback: Optional[SupplierDecisionOutcomeFeedback] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    source: str = "quote_case"
