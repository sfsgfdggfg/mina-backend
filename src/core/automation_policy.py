from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


AutomationMode = Literal["manual", "approval_required", "automatic"]
AutomationPolicyAction = Literal[
    "supplier_reminder",
    "customer_deadline_update",
]
AutomationPolicySource = Literal[
    "job",
    "job_legacy_disable",
    "customer",
    "agency",
    "legacy_dispatch",
]


class AgencyAutomationPolicy(BaseModel):
    supplier_reminder_mode: AutomationMode | None = None
    customer_deadline_update_mode: AutomationMode | None = None
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)
    source: str = "agency_automation_policy"

    @model_validator(mode="after")
    def validate_timestamp(self):
        if self.updated_at.tzinfo is None:
            raise ValueError("Agency automation policy timestamp must be timezone-aware.")
        return self


class CustomerAutomationPolicy(BaseModel):
    supplier_reminder_mode: AutomationMode | None = None
    customer_deadline_update_mode: AutomationMode | None = None


class EffectiveAutomationPolicy(BaseModel):
    action: AutomationPolicyAction
    effective_mode: AutomationMode
    resolved_from: AutomationPolicySource
    job_mode: AutomationMode | None = None
    legacy_job_disabled: bool = False
    customer_mode: AutomationMode | None = None
    customer_id: str | None = None
    agency_mode: AutomationMode | None = None
    legacy_dispatch_enabled: bool
    source: str = "automation_policy_resolver"
