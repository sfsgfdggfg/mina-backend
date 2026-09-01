from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class OperationalWorkAssignment(BaseModel):
    work_id: str = Field(min_length=3, max_length=512)
    assigned_to: str = Field(min_length=3, max_length=200)
    status: Literal["assigned", "acknowledged", "released"] = "assigned"
    assigned_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    acknowledged_at: datetime | None = None
    last_renewed_at: datetime | None = None
    lease_expires_at: datetime | None = None
    released_at: datetime | None = None
    released_by: str | None = Field(default=None, min_length=3, max_length=200)
    release_reason: Literal["operator_release", "shift_handoff"] | None = None
    generation: int = Field(default=1, ge=1)
    work_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    source: Literal["operational_work_assignment"] = "operational_work_assignment"
