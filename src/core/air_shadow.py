from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


AirObservedMode = Literal["commercial_air", "express"]
AirCargoScope = Literal["general_cargo", "special_cargo", "mixed", "unknown"]
AirModeEvidenceBasis = Literal["operator_action", "sent_quote", "customer_explicit"]


class AirRateSource(BaseModel):
    """Immutable identity for a commercial-air tariff source.

    This model deliberately does not contain parsed prices. It records which
    tariff document was available so later extraction/review can stay tied to
    exact source evidence without creating quote authority.
    """

    source_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    mode: Literal["commercial_air"] = "commercial_air"
    airline_name: str = Field(min_length=1, max_length=200)
    document_name: str = Field(min_length=1, max_length=240)
    mime_type: Literal["application/pdf"] = "application/pdf"
    sha256_hex: str = Field(pattern=r"^[0-9a-f]{64}$")
    cargo_scope: AirCargoScope = "unknown"
    origin_country: str = Field(default="Türkiye", min_length=1, max_length=100)
    origin_airport: Optional[str] = Field(default=None, min_length=3, max_length=3)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: Optional[str] = Field(default=None, max_length=2000)
    interpretation_status: Literal["registered_not_interpreted"] = "registered_not_interpreted"
    source: Literal["air_rate_source_v1"] = "air_rate_source_v1"

    @field_validator("document_name")
    @classmethod
    def require_pdf_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized.lower().endswith(".pdf"):
            raise ValueError("Commercial-air rate source must be a PDF document.")
        return normalized

    @field_validator("airline_name", "origin_country", "recorded_by", "notes", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("origin_airport")
    @classmethod
    def normalize_airport(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("Origin airport must be a 3-letter IATA code when supplied.")
        return normalized

    @field_validator("recorded_at")
    @classmethod
    def require_aware_recorded_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air rate source recorded_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_validity(self):
        if self.valid_from is not None and self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("Air rate source valid_to cannot precede valid_from.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False


class AirModeObservation(BaseModel):
    """Immutable evidence of an operator-observed air service-mode choice.

    Express is intentionally represented only as a classification observation;
    this contract has no price, rate, surcharge or express-operation fields.
    """

    observation_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    inquiry_reference: str = Field(min_length=1, max_length=300)
    selected_mode: AirObservedMode
    evidence_basis: AirModeEvidenceBasis
    observed_by: str = Field(min_length=1, max_length=200)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    customer_id: Optional[str] = Field(default=None, max_length=200)
    airline_name: Optional[str] = Field(default=None, max_length=200)
    express_provider: Optional[str] = Field(default=None, max_length=120)
    source: Literal["air_mode_observation_v1"] = "air_mode_observation_v1"

    @field_validator("inquiry_reference", "observed_by", "customer_id", "airline_name", "express_provider", mode="before")
    @classmethod
    def normalize_observation_text(cls, value):
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("observed_at")
    @classmethod
    def require_aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air mode observation observed_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def keep_mode_fields_separate(self):
        if self.selected_mode == "commercial_air" and self.express_provider is not None:
            raise ValueError("Commercial-air observation cannot carry an express provider.")
        if self.selected_mode == "express" and self.airline_name is not None:
            raise ValueError("Express observation cannot carry a commercial airline name.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False
