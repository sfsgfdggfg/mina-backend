from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class OperationalShiftCloseReceipt(BaseModel):
    receipt_id: str = Field(pattern=r"^shift-close-[0-9a-f]{32}$")
    attested_by: str = Field(min_length=3, max_length=200)
    attested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    readiness_generated_at: datetime
    pending_work_count: int = Field(ge=0)
    critical_pending_count: int = Field(ge=0)
    active_assignment_count: int = Field(ge=0)
    expired_assignment_count: int = Field(ge=0)
    incomplete_handoff_count: int = Field(ge=0)
    critical_uncovered_count: int = Field(ge=0)
    close_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    state_event_id: int | None = Field(default=None, ge=0)
    evidence_version: Literal["shift_close_attestation_v1"] = "shift_close_attestation_v1"
    source: Literal["operational_shift_close_attestation"] = "operational_shift_close_attestation"
