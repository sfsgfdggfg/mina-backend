from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.air_quote_context import AirQuoteContextSnapshot


AirTariffUsage = Literal["used_as_quoted", "used_with_correction", "not_used"]
AirLearningEvidenceSource = Literal[
    "airline_invoice", "airline_booking_confirmation", "airline_email", "portal", "operator", "other"
]
AirCorrectionCategory = Literal[
    "chargeable_weight", "base_rate", "surcharge", "local_cost", "fx", "airline",
    "routing", "service_date", "delivery_date", "other",
]


class AirLearningFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    job_id: str = Field(min_length=1, max_length=100)
    mina_code: str = Field(pattern=r"^MINA\d{4}/[1-9]\d*$")
    handoff_id: str = Field(min_length=1, max_length=100)
    supersedes_feedback_id: str | None = Field(default=None, max_length=100)
    quoted_air_context: AirQuoteContextSnapshot

    tariff_usage: AirTariffUsage
    actual_airline_name: str = Field(min_length=1, max_length=200)
    actual_routing_context: Literal["direct", "connecting"]
    actual_via_airport: str | None = Field(default=None, min_length=3, max_length=3)
    actual_service_date: date | None = None
    actual_delivery_date: date | None = None
    actual_chargeable_weight_kg: Decimal | None = Field(default=None, gt=0)
    actual_cost_amount: Decimal | None = Field(default=None, gt=0)
    actual_cost_currency: str | None = Field(default=None, min_length=3, max_length=3)
    correction_categories: list[AirCorrectionCategory] = Field(default_factory=list, max_length=10)

    evidence_source: AirLearningEvidenceSource
    source_reference: str = Field(min_length=1, max_length=300)
    note: str = Field(min_length=3, max_length=1200)
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    source: Literal["air_learning_feedback_v1"] = "air_learning_feedback_v1"

    @field_validator("actual_airline_name", "source_reference", "note", "recorded_by", mode="before")
    @classmethod
    def normalize_text(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("actual_via_airport", "actual_cost_currency", mode="before")
    @classmethod
    def normalize_code(cls, value):
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized or None

    @field_validator("recorded_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air learning feedback timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_feedback(self):
        if self.actual_routing_context == "direct" and self.actual_via_airport is not None:
            raise ValueError("Direct air learning outcome cannot carry a via airport.")
        if self.actual_routing_context == "connecting" and self.actual_via_airport is None:
            raise ValueError("Connecting air learning outcome requires a via airport.")
        if (self.actual_cost_amount is None) != (self.actual_cost_currency is None):
            raise ValueError("Actual air cost amount and currency must be supplied together.")
        if self.actual_service_date and self.actual_delivery_date and self.actual_delivery_date < self.actual_service_date:
            raise ValueError("Actual air delivery date cannot precede actual service date.")
        if len(set(self.correction_categories)) != len(self.correction_categories):
            raise ValueError("Air correction categories must be unique.")
        if self.tariff_usage == "used_as_quoted" and self.correction_categories:
            raise ValueError("Tariff used as quoted cannot carry correction categories.")
        if self.tariff_usage == "used_with_correction" and not self.correction_categories:
            raise ValueError("Tariff used with correction requires at least one correction category.")
        if self.supersedes_feedback_id == self.feedback_id:
            raise ValueError("Air learning feedback cannot supersede itself.")
        return self
