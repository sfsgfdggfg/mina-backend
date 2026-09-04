from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


OperationExceptionImpact = Literal["deviation", "delivery_risk", "actual_delay"]
OperationExceptionStatus = Literal["open", "resolved"]
OperationExceptionType = Literal[
    "border_congestion", "breakdown", "documentation", "customs", "appointment",
    "route_deviation", "weather", "loading", "delivery", "damage", "other",
]
OperationEvidenceSource = Literal[
    "supplier_email", "supplier_phone", "whatsapp", "gps", "operator", "system", "other",
]


class OperationExecutionSnapshot(BaseModel):
    job_id: str = Field(min_length=1, max_length=100)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    supplier_confirmed_at: datetime | None = None
    vehicle_plate: str | None = Field(default=None, max_length=80)
    driver_name: str | None = Field(default=None, max_length=200)
    driver_phone: str | None = Field(default=None, max_length=80)
    vehicle_assigned_at: datetime | None = None
    loading_appointment_at: datetime | None = None
    loaded_at: datetime | None = None
    current_location: str | None = Field(default=None, max_length=300)
    current_eta: datetime | None = None
    delivery_appointment_at: datetime | None = None
    delivered_at: datetime | None = None
    pod_received_at: datetime | None = None
    cmr_received_at: datetime | None = None
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)
    source: str = "operation_execution"

    @field_validator(
        "supplier_confirmed_at", "vehicle_assigned_at", "loading_appointment_at", "loaded_at",
        "current_eta", "delivery_appointment_at", "delivered_at", "pod_received_at", "cmr_received_at",
    )
    @classmethod
    def aware_optional_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Operation execution timestamps must be timezone-aware.")
        return value

    @field_validator("updated_at")
    @classmethod
    def aware_updated_at(cls, value):
        if value.tzinfo is None:
            raise ValueError("Operation execution updated_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_evidence_order(self):
        if self.vehicle_assigned_at is not None and not (self.vehicle_plate and self.driver_name):
            raise ValueError("Vehicle assignment evidence requires plate and driver name.")
        if self.loaded_at is not None and self.delivered_at is not None and self.delivered_at < self.loaded_at:
            raise ValueError("Delivered time cannot precede loaded time.")
        if (self.pod_received_at is not None or self.cmr_received_at is not None) and self.delivered_at is None:
            raise ValueError("POD/CMR receipt evidence requires delivered_at.")
        return self


class OperationException(BaseModel):
    exception_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    job_id: str = Field(min_length=1, max_length=100)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    stage_at_report: str = Field(min_length=1, max_length=80)
    exception_type: OperationExceptionType
    impact_level: OperationExceptionImpact
    status: OperationExceptionStatus = "open"
    cause: str = Field(min_length=1, max_length=1200)
    location: str | None = Field(default=None, max_length=300)
    old_eta: datetime | None = None
    new_eta: datetime | None = None
    customer_impact_summary: str | None = Field(default=None, max_length=1200)
    next_action: str | None = Field(default=None, max_length=1200)
    source_type: OperationEvidenceSource
    source_reference: str | None = Field(default=None, max_length=300)
    reported_at: datetime
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=200)
    updated_at: datetime
    updated_by: str = Field(min_length=1, max_length=200)
    resolved_at: datetime | None = None
    resolved_by: str | None = Field(default=None, max_length=200)
    resolution_note: str | None = Field(default=None, max_length=1200)
    source: str = "operation_exception"

    @field_validator("old_eta", "new_eta", "reported_at", "created_at", "updated_at", "resolved_at")
    @classmethod
    def aware_times(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Operation exception timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_resolution(self):
        if self.updated_at < self.created_at:
            raise ValueError("Exception updated_at cannot precede created_at.")
        if self.status == "open":
            if self.resolved_at is not None or self.resolved_by is not None or self.resolution_note is not None:
                raise ValueError("Open exception cannot contain resolution evidence.")
        else:
            if self.resolved_at is None or not self.resolved_by or not self.resolution_note:
                raise ValueError("Resolved exception requires time, actor and resolution note.")
            if self.resolved_at < self.created_at:
                raise ValueError("Exception resolution cannot precede creation.")
        return self

    @computed_field
    @property
    def customer_attention_recommended(self) -> bool:
        return self.impact_level in {"delivery_risk", "actual_delay"}
