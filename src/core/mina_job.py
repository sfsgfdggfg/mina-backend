from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

from src.core.models import Shipment


MinaJobStage = Literal[
    "inquiry_confirmed",
    "pricing",
    "quote_ready",
    "quote_sent",
    "negotiation",
    "accepted",
    "operations",
    "in_transit",
    "delivered",
    "lost",
    "cancelled",
]

TERMINAL_MINA_JOB_STAGES = {"delivered", "lost", "cancelled"}
MINA_CODE_RE = re.compile(r"^MINA(?P<year>\d{4})/(?P<number>[1-9]\d*)$")


class MinaJobAutomationOverrides(BaseModel):
    disable_supplier_reminders: bool = False
    disable_customer_deadline_updates: bool = False


class MinaJob(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    mina_code: str
    sequence_year: int = Field(ge=2020, le=9999)
    sequence_number: int = Field(ge=1)
    source_proposal_id: str = Field(min_length=1)
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

    @model_validator(mode="after")
    def validate_identity_and_closure(self):
        match = MINA_CODE_RE.match(self.mina_code)
        if match is None:
            raise ValueError("MINA code must use MINAYYYY/N format.")
        if int(match.group("year")) != self.sequence_year:
            raise ValueError("MINA code year must match sequence_year.")
        if int(match.group("number")) != self.sequence_number:
            raise ValueError("MINA code number must match sequence_number.")
        terminal = self.stage in TERMINAL_MINA_JOB_STAGES
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
        return self.stage in TERMINAL_MINA_JOB_STAGES


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
