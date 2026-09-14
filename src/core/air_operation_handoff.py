from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.air_quote_context import AirQuoteContextSnapshot


class AirOperationCustomerQuoteSentEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_kind: Literal["manual_external_send", "automated_provider_send", "operator_provider_reconciliation"]
    approval_id: str = Field(min_length=1, max_length=300)
    revision_number: int = Field(ge=0)
    recipient_email: str = Field(min_length=3, max_length=320)
    sent_at: datetime
    provider_name: str | None = Field(default=None, max_length=200)
    provider_message_id: str | None = Field(default=None, max_length=500)

    @field_validator("sent_at")
    @classmethod
    def require_aware_sent_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air handoff sent evidence timestamp must be timezone-aware.")
        return value


class AirOperationHandoff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handoff_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str = Field(min_length=1, max_length=100)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    quote_case_id: str = Field(min_length=1, max_length=100)
    approval_id: str = Field(min_length=1, max_length=100)
    revision_number: int = Field(ge=0)
    air_quote_context: AirQuoteContextSnapshot
    customer_quote_sent_evidence: list[AirOperationCustomerQuoteSentEvidence] = Field(min_length=1, max_length=20)
    accepted_by: str = Field(min_length=1, max_length=200)
    accepted_at: datetime
    handed_off_by: str = Field(min_length=1, max_length=200)
    handed_off_at: datetime
    booking_confirmed: Literal[False] = False
    booking_reference: None = None
    airline_contact_performed: Literal[False] = False
    booking_authority: Literal[False] = False
    outbound_authority: Literal[False] = False
    runtime_authoritative: Literal[False] = False
    source: Literal["air_operation_handoff_v1"] = "air_operation_handoff_v1"

    @field_validator("accepted_at", "handed_off_at")
    @classmethod
    def require_aware_times(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air operation handoff timestamps must be timezone-aware.")
        return value
