from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from src.core.models import Shipment
from src.core.automation_policy import AutomationMode


MinaJobLifecycleVersion = Literal[1, 2]
MinaJobKind = Literal["price_request", "approved_job"]
MinaJobIntakeChannel = Literal[
    "email", "phone", "whatsapp", "portal", "face_to_face", "other"
]
MinaJobStage = Literal[
    "inquiry_confirmed",
    "pricing",
    "quote_ready",
    "quote_sent",
    "negotiation",
    "accepted",
    "operations",
    "operation_opened",
    "supplier_confirmation_pending",
    "vehicle_details_pending",
    "vehicle_assigned",
    "pre_loading_check",
    "ready_for_loading",
    "loaded",
    "in_transit",
    "delivery",
    "delivered",
    "pod_cmr_pending",
    "closing_review",
    "completed",
    "lost",
    "cancelled",
]

V1_MINA_JOB_STAGES = {
    "inquiry_confirmed", "pricing", "quote_ready", "quote_sent", "negotiation",
    "accepted", "operations", "in_transit", "delivered", "lost", "cancelled",
}
V2_MINA_JOB_STAGES = {
    "inquiry_confirmed", "pricing", "quote_ready", "quote_sent", "negotiation",
    "accepted", "operation_opened", "supplier_confirmation_pending",
    "vehicle_details_pending", "vehicle_assigned", "pre_loading_check",
    "ready_for_loading", "loaded", "in_transit", "delivery", "delivered",
    "pod_cmr_pending", "closing_review", "completed", "lost", "cancelled",
}
V1_TERMINAL_MINA_JOB_STAGES = {"delivered", "lost", "cancelled"}
V2_TERMINAL_MINA_JOB_STAGES = {"completed", "lost", "cancelled"}
MINA_CODE_RE = re.compile(r"^MINA(?P<year>\d{4})/(?P<number>[1-9]\d*)$")


class MinaJobAutomationOverrides(BaseModel):
    # Legacy disable flags remain readable/writable for backward compatibility.
    disable_supplier_reminders: bool = False
    disable_customer_deadline_updates: bool = False
    supplier_reminder_mode: AutomationMode | None = None
    customer_deadline_update_mode: AutomationMode | None = None


class MinaJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    mina_code: str
    sequence_year: int = Field(ge=2020, le=9999)
    sequence_number: int = Field(ge=1)

    # Persisted records created before P2-01 do not contain this field. Defaulting
    # to v1 preserves their original state-machine and closure semantics.
    lifecycle_version: MinaJobLifecycleVersion = 1
    job_kind: MinaJobKind = "price_request"
    intake_channel: MinaJobIntakeChannel = "email"
    source_proposal_id: Optional[str] = Field(default=None, min_length=1, max_length=300)
    manual_intake_id: Optional[str] = Field(default=None, min_length=1, max_length=300)

    sales_owner: Optional[str] = Field(default=None, min_length=1, max_length=200)
    operations_owner: Optional[str] = Field(default=None, min_length=1, max_length=200)

    shipment: Shipment
    stage: MinaJobStage = "inquiry_confirmed"
    supplier_rfq_workflow_id: Optional[str] = None
    quote_case_id: Optional[str] = None
    automation_overrides: MinaJobAutomationOverrides = Field(
        default_factory=MinaJobAutomationOverrides
    )
    opened_by: str = Field(min_length=1, max_length=200)
    opened_at: datetime
    updated_at: datetime
    closed_at: Optional[datetime] = None
    source: str = "mina_job"

    @field_validator("opened_at", "updated_at", "closed_at")
    @classmethod
    def require_aware_time(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("MINA job timestamps must be timezone-aware.")
        return value

    @field_validator(
        "source_proposal_id", "manual_intake_id", "sales_owner", "operations_owner",
        mode="before",
    )
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_identity_and_closure(self):
        match = MINA_CODE_RE.match(self.mina_code)
        if match is None:
            raise ValueError("MINA code must use MINAYYYY/N format.")
        if int(match.group("year")) != self.sequence_year:
            raise ValueError("MINA code year must match sequence_year.")
        if int(match.group("number")) != self.sequence_number:
            raise ValueError("MINA code number must match sequence_number.")

        if self.lifecycle_version == 1:
            if self.stage not in V1_MINA_JOB_STAGES:
                raise ValueError("Legacy MINA lifecycle contains an unsupported stage.")
            if not self.source_proposal_id:
                raise ValueError("Legacy MINA jobs require source_proposal_id.")
            if self.manual_intake_id is not None:
                raise ValueError("Legacy MINA jobs cannot contain manual_intake_id.")
            if self.job_kind != "price_request" or self.intake_channel != "email":
                raise ValueError("Legacy MINA jobs must preserve price-request email semantics.")
            terminal_stages = V1_TERMINAL_MINA_JOB_STAGES
        else:
            if self.stage not in V2_MINA_JOB_STAGES:
                raise ValueError("MINA lifecycle v2 contains an unsupported stage.")
            if bool(self.source_proposal_id) == bool(self.manual_intake_id):
                raise ValueError(
                    "MINA lifecycle v2 requires exactly one intake identity: "
                    "source_proposal_id or manual_intake_id."
                )
            if self.source_proposal_id and self.intake_channel != "email":
                raise ValueError("Proposal-backed MINA lifecycle v2 jobs must use email intake.")
            if self.job_kind == "approved_job" and self.stage in {
                "quote_ready", "quote_sent", "negotiation", "accepted"
            }:
                raise ValueError("Approved jobs cannot enter customer quote lifecycle stages.")
            terminal_stages = V2_TERMINAL_MINA_JOB_STAGES

        terminal = self.stage in terminal_stages
        if terminal and self.closed_at is None:
            raise ValueError("Terminal MINA job stage requires closed_at.")
        if not terminal and self.closed_at is not None:
            raise ValueError("Open MINA job stage must not contain closed_at.")
        if self.updated_at < self.opened_at:
            raise ValueError("MINA job updated_at cannot precede opened_at.")
        return self

    @computed_field
    @property
    def is_closed(self) -> bool:
        terminal_stages = (
            V1_TERMINAL_MINA_JOB_STAGES
            if self.lifecycle_version == 1
            else V2_TERMINAL_MINA_JOB_STAGES
        )
        return self.stage in terminal_stages


class MinaJobEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str = Field(min_length=1)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    event_type: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    actor: Optional[str] = Field(default=None, max_length=200)
    resource_type: Optional[str] = Field(default=None, max_length=100)
    resource_id: Optional[str] = Field(default=None, max_length=300)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "mina_job_timeline"

    @field_validator("occurred_at")
    @classmethod
    def require_aware_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("MINA job event time must be timezone-aware.")
        return value
