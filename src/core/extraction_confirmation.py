from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    computed_field,
    model_validator,
)

from src.core.mail import InboundMailEnvelope
from src.core.models import Shipment


SafetySensitiveField = Literal[
    "is_adr",
    "is_temperature_controlled",
    "is_high_value",
]
ExtractionStatus = Literal["proposed", "confirmed"]
ExtractionResumeStatus = Literal[
    "not_started",
    "in_progress",
    "provenance_blocked",
    "completed",
]

SAFETY_SENSITIVE_FIELDS: tuple[SafetySensitiveField, ...] = (
    "is_adr",
    "is_temperature_controlled",
    "is_high_value",
)


class ShipmentProposalSnapshot(Shipment):
    """Normalized extraction facts that have no operational authority yet."""

    model_config = ConfigDict(extra="forbid")

    is_adr: Optional[StrictBool] = None
    is_temperature_controlled: Optional[StrictBool] = None
    is_high_value: Optional[StrictBool] = None


def require_operational_shipment(shipment: Shipment) -> None:
    if isinstance(shipment, ShipmentProposalSnapshot):
        raise TypeError(
            "Operational engine requires a human-confirmed Shipment snapshot."
        )


class ShipmentExtractionProposal(BaseModel):
    """Preserves MINAI's first extraction and the later human snapshot."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=lambda: str(uuid4()))
    inbound_mail: InboundMailEnvelope
    proposed_shipment: ShipmentProposalSnapshot
    extraction_status: ExtractionStatus = "proposed"

    confirmed_shipment: Optional[Shipment] = None
    operator_corrections: dict[str, Any] = Field(default_factory=dict)
    changed_fields: list[str] = Field(default_factory=list)
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None

    resume_started_at: Optional[datetime] = None
    resumed_at: Optional[datetime] = None
    downstream_result_type: Optional[str] = None
    resume_status: ExtractionResumeStatus = "not_started"
    resume_attempt_count: int = Field(default=0, ge=0)
    last_resume_blocked_at: Optional[datetime] = None
    last_resume_blocked_result_type: Optional[str] = None
    source: str = "human_extraction_confirmation"

    @model_validator(mode="before")
    @classmethod
    def infer_legacy_resume_status(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "resume_status" in value:
            return value
        normalized = dict(value)
        if normalized.get("resumed_at") is not None:
            normalized["resume_status"] = "completed"
        elif normalized.get("resume_started_at") is not None:
            normalized["resume_status"] = "in_progress"
        if (
            normalized.get("resume_started_at") is not None
            and "resume_attempt_count" not in normalized
        ):
            normalized["resume_attempt_count"] = 1
        return normalized

    @computed_field
    @property
    def unknown_fields(self) -> list[str]:
        proposed_data = self.proposed_shipment.model_dump()
        return sorted(
            field_name
            for field_name, value in proposed_data.items()
            if value is None
        )

    @computed_field
    @property
    def unknown_safety_fields(self) -> list[SafetySensitiveField]:
        return [
            field_name
            for field_name in SAFETY_SENSITIVE_FIELDS
            if getattr(self.proposed_shipment, field_name) is None
        ]

    @model_validator(mode="after")
    def validate_confirmation_state(self):
        confirmation_metadata = (
            self.confirmed_shipment,
            self.confirmed_by,
            self.confirmed_at,
        )
        if self.extraction_status == "proposed":
            if any(value is not None for value in confirmation_metadata):
                raise ValueError(
                    "Proposed extraction must not contain confirmation metadata."
                )
            if self.operator_corrections or self.changed_fields:
                raise ValueError(
                    "Proposed extraction must not contain operator corrections."
                )
            if (
                self.resume_started_at is not None
                or self.resumed_at is not None
                or self.downstream_result_type is not None
                or self.resume_status != "not_started"
                or self.resume_attempt_count != 0
                or self.last_resume_blocked_at is not None
                or self.last_resume_blocked_result_type is not None
            ):
                raise ValueError(
                    "Proposed extraction must not contain downstream metadata."
                )
        else:
            if any(value is None for value in confirmation_metadata):
                raise ValueError(
                    "Confirmed extraction requires shipment, operator, and time."
                )
        if (
            self.resume_started_at is not None
            and self.extraction_status != "confirmed"
        ):
            raise ValueError(
                "Only a confirmed extraction may start operational resume."
            )
        if self.resumed_at is not None and self.resume_started_at is None:
            raise ValueError(
                "Completed operational resume requires a durable start marker."
            )
        if (self.resumed_at is None) != (self.downstream_result_type is None):
            raise ValueError(
                "Resume time and downstream result type must be recorded together."
            )
        if self.resume_status == "not_started" and self.resume_started_at is not None:
            raise ValueError("A not-started resume cannot have a start time.")
        if self.resume_status in {
            "in_progress",
            "provenance_blocked",
            "completed",
        } and self.resume_started_at is None:
            raise ValueError("A started resume requires a start time.")
        if self.resume_status == "provenance_blocked":
            if (
                self.last_resume_blocked_at is None
                or self.last_resume_blocked_result_type
                != "data_provenance_blocked"
            ):
                raise ValueError(
                    "A provenance-blocked resume requires durable block evidence."
                )
            if self.resumed_at is not None:
                raise ValueError(
                    "A provenance-blocked resume cannot be marked completed."
                )
        if self.resume_status == "completed" and self.resumed_at is None:
            raise ValueError("A completed resume requires a completion time.")
        return self


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
