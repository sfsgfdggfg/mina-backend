from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

LearningSubjectType = Literal["customer", "supplier", "route", "operation"]
LearningFactStatus = Literal["proposed", "confirmed", "rejected", "superseded"]
LearningSourceType = Literal[
    "manual", "excel_import", "email", "operation_history", "portal", "system", "minai_inference"
]
LearningFactValue = str | int | float | bool | list[str]


class LearningEvidence(BaseModel):
    source_type: LearningSourceType
    source_reference: str = Field(min_length=1, max_length=300)
    observed_at: datetime
    summary: str = Field(min_length=1, max_length=1000)
    dataset_key: str | None = Field(default=None, max_length=120)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")

    @field_validator("observed_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Learning evidence time must be timezone-aware.")
        return value


class LearningFact(BaseModel):
    fact_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    subject_type: LearningSubjectType
    subject_id: str = Field(min_length=1, max_length=300)
    subject_label: str = Field(min_length=1, max_length=300)
    fact_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{1,119}$")
    value: LearningFactValue
    value_unit: str | None = Field(default=None, max_length=80)
    confidence: float = Field(ge=0, le=1)
    source_type: LearningSourceType
    evidence: list[LearningEvidence] = Field(min_length=1, max_length=20)
    status: LearningFactStatus = "proposed"
    supersedes_fact_id: str | None = Field(default=None, max_length=100)
    superseded_by_fact_id: str | None = Field(default=None, max_length=100)
    superseded_at: datetime | None = None
    superseded_by: str | None = Field(default=None, max_length=200)
    supersession_note: str | None = Field(default=None, max_length=1200)
    created_at: datetime
    created_by: str = Field(min_length=1, max_length=200)
    updated_at: datetime
    reviewed_at: datetime | None = None
    reviewed_by: str | None = Field(default=None, max_length=200)
    review_note: str | None = Field(default=None, max_length=1200)
    source: str = "learning_fact"

    @field_validator("created_at", "updated_at", "reviewed_at", "superseded_at")
    @classmethod
    def require_aware_times(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Learning fact timestamps must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_lifecycle(self):
        if self.updated_at < self.created_at:
            raise ValueError("Learning fact updated_at cannot precede created_at.")
        if isinstance(self.value, str):
            if not self.value.strip() or len(self.value) > 2000:
                raise ValueError("Learning fact text value must contain 1-2000 characters.")
        if isinstance(self.value, list):
            if (
                not self.value or len(self.value) > 50
                or any(not item.strip() or len(item) > 300 for item in self.value)
            ):
                raise ValueError("Learning fact list value must contain 1-50 bounded non-empty strings.")
        supersession_values = (
            self.superseded_by_fact_id, self.superseded_at, self.superseded_by, self.supersession_note
        )
        if self.status == "proposed":
            if self.reviewed_at or self.reviewed_by or self.review_note or any(supersession_values):
                raise ValueError("Proposed fact cannot contain review or supersession evidence.")
        elif self.status in {"confirmed", "rejected"}:
            if self.reviewed_at is None or not self.reviewed_by or not self.review_note:
                raise ValueError("Reviewed learning fact requires time, actor and note.")
            if any(supersession_values):
                raise ValueError("Only superseded facts may contain supersession evidence.")
        else:
            if self.reviewed_at is None or not self.reviewed_by or not self.review_note:
                raise ValueError("Superseded learning fact must preserve its original review evidence.")
            if not all(supersession_values):
                raise ValueError("Superseded learning fact requires replacement id, time, actor and note.")
            if self.superseded_at < self.reviewed_at:
                raise ValueError("Fact supersession cannot precede original confirmation.")
        return self

    @computed_field
    @property
    def confidence_band(self) -> str:
        if self.confidence >= 0.85:
            return "high"
        if self.confidence >= 0.60:
            return "medium"
        return "low"

    @computed_field
    @property
    def runtime_authoritative(self) -> bool:
        return self.status == "confirmed"
