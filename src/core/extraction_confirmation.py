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
    source: str = "human_extraction_confirmation"

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
        return self


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
