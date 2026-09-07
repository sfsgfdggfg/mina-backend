from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.automation_policy import AutomationMode


OperationStartMessageKind = Literal["selected_supplier_confirmation", "supplier_closure"]
OperationStartMessageStatus = Literal[
    "approval_required", "manual_required", "sending", "sent", "rejected", "failed"
]


class OperationStartMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str = Field(min_length=1, max_length=300)
    mina_code: str = Field(min_length=1, max_length=80)
    supplier_name: str = Field(min_length=1, max_length=240)
    recipient_email: str = Field(min_length=3, max_length=320)
    kind: OperationStartMessageKind
    outbound_mode: AutomationMode
    subject: str = Field(min_length=1, max_length=300)
    body_text: str = Field(min_length=1, max_length=12000)
    status: OperationStartMessageStatus
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=200)
    attention_reason: str | None = Field(default=None, max_length=1000)
    decided_at: datetime | None = None
    decided_by: str | None = Field(default=None, max_length=200)
    decision_reason: str | None = Field(default=None, max_length=1000)
    sent_at: datetime | None = None
    sent_by: str | None = Field(default=None, max_length=200)
    provider_name: str | None = Field(default=None, max_length=200)
    provider_message_id: str | None = Field(default=None, max_length=500)
    source: str = "operation_start_orchestration"

    @field_validator("recipient_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized.count("@") != 1 or any(ch.isspace() for ch in normalized):
            raise ValueError("Operation-start message recipient must be a valid email address.")
        return normalized

    @field_validator("created_at", "decided_at", "sent_at")
    @classmethod
    def require_aware_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Operation-start message timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_state(self):
        if self.status == "sent":
            if self.sent_at is None or not self.sent_by:
                raise ValueError("Sent operation-start message requires send evidence.")
        elif self.sent_at is not None or self.sent_by is not None:
            raise ValueError("Unsent operation-start message cannot contain send evidence.")
        if self.status == "rejected" and (self.decided_at is None or not self.decided_by):
            raise ValueError("Rejected operation-start message requires decision evidence.")
        return self
