from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirAvailabilityCapacityStatus = Literal["available", "unavailable"]
AirAvailabilityScheduleStatus = Literal["confirmed", "not_confirmed"]
AirAvailabilityEvidenceChannel = Literal["email", "phone", "whatsapp", "portal", "other"]
AirAvailabilityRoutingContext = Literal["direct", "connecting"]


class AirServiceAvailabilityConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    inquiry_reference: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=300)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    airline_name: str = Field(min_length=1, max_length=200)
    destination_code: str = Field(min_length=3, max_length=3)
    routing_context: AirAvailabilityRoutingContext
    via_airport: Optional[str] = Field(default=None, min_length=3, max_length=3)
    service_date: date
    expected_delivery_date: Optional[date] = None
    capacity_status: AirAvailabilityCapacityStatus
    schedule_status: AirAvailabilityScheduleStatus
    flight_reference: Optional[str] = Field(default=None, max_length=120)
    evidence_channel: AirAvailabilityEvidenceChannel
    evidence_reference: str = Field(min_length=1, max_length=300)
    evidence_note: str = Field(min_length=1, max_length=1200)
    confirmed_by: str = Field(min_length=1, max_length=200)
    confirmed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["air_service_availability_confirmation_v1"] = "air_service_availability_confirmation_v1"

    @field_validator(
        "entry_id", "inquiry_reference", "airline_name", "flight_reference",
        "evidence_reference", "evidence_note", "confirmed_by", mode="before",
    )
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("destination_code", "via_airport")
    @classmethod
    def normalize_airport(cls, value):
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Air availability airport codes must be 3-letter IATA codes.")
        return normalized

    @field_validator("confirmed_at")
    @classmethod
    def require_aware_confirmed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air availability confirmed_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_routing_and_schedule(self):
        if self.routing_context == "direct" and self.via_airport is not None:
            raise ValueError("Direct air availability confirmation cannot carry a via airport.")
        if self.schedule_status == "not_confirmed" and (
            self.flight_reference is not None or self.expected_delivery_date is not None
        ):
            raise ValueError("Unconfirmed air schedule cannot carry flight or expected-delivery evidence.")
        if self.expected_delivery_date is not None and self.expected_delivery_date < self.service_date:
            raise ValueError("Expected delivery date cannot be before air service date.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False

    @property
    def booking_authority(self) -> bool:
        return False
