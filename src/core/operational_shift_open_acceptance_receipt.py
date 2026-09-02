from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class OperationalShiftOpenAcceptanceReceipt(BaseModel):
    receipt_id: str = Field(pattern=r"^shift-open-[0-9a-f]{32}$")
    accepted_by: str = Field(min_length=3, max_length=200)
    accepted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reconciliation_generated_at: datetime
    source_close_receipt_id: str = Field(pattern=r"^shift-close-[0-9a-f]{32}$")
    pending_work_count: int = Field(ge=0)
    critical_pending_count: int = Field(ge=0)
    incomplete_handoff_count: int = Field(ge=0)
    critical_uncovered_count: int = Field(ge=0)
    acceptance_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_version: Literal["shift_open_acceptance_v1"] = "shift_open_acceptance_v1"
    source: Literal["operational_shift_open_acceptance"] = "operational_shift_open_acceptance"
