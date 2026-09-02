from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


AutomationActionType = Literal[
    "supplier_no_response_reminder",
    "supplier_acknowledged_reminder",
    "customer_deadline_update",
]
AutomationActionStatus = Literal["reserved", "sent", "failed", "cancelled"]


class ScheduledAutomationAction(BaseModel):
    action_key: str = Field(min_length=1, max_length=300)
    action_type: AutomationActionType
    workflow_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    due_at: datetime
    status: AutomationActionStatus = "reserved"
    reserved_at: datetime
    completed_at: Optional[datetime] = None
    provider_name: Optional[str] = None
    provider_message_id: Optional[str] = None
    failure_code: Optional[str] = None
    source: str = "scheduled_outbound_automation"

    @field_validator("due_at", "reserved_at", "completed_at")
    @classmethod
    def require_timezone(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Scheduled automation timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_status_evidence(self):
        if self.status == "reserved":
            if any(
                value is not None
                for value in (
                    self.completed_at,
                    self.provider_name,
                    self.provider_message_id,
                    self.failure_code,
                )
            ):
                raise ValueError("Reserved automation cannot contain completion evidence.")
        elif self.status == "sent":
            if (
                self.completed_at is None
                or not self.provider_message_id
                or self.failure_code is not None
            ):
                raise ValueError("Sent automation requires provider completion evidence.")
        elif self.status in {"failed", "cancelled"}:
            if self.completed_at is None or not self.failure_code:
                raise ValueError(
                    "Failed/cancelled automation requires a reason code and completion time."
                )
            if self.provider_name is not None or self.provider_message_id is not None:
                raise ValueError(
                    "Failed/cancelled automation cannot contain successful provider evidence."
                )
        return self
