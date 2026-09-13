from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirRateSurchargeBasis = Literal["flat", "per_kg"]
AirRateSurchargeApplicationBasis = Literal["actual_weight", "chargeable_weight", "pivot_billed_weight", "flat"]
AirRateSurchargeCandidateStatus = Literal["proposed", "confirmed", "rejected"]
AirRateSurchargeReviewStatus = Literal["pending", "partially_reviewed", "completed", "no_candidates"]


class AirRateSurchargeCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=12, max_length=64)
    surcharge_code: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,39}$")
    amount: Decimal
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    basis: AirRateSurchargeBasis
    source_line_number: int = Field(ge=1)
    source_line_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    detection_method: Literal["deterministic_surcharge_v1"] = "deterministic_surcharge_v1"
    status: AirRateSurchargeCandidateStatus = "proposed"
    reviewed_by: Optional[str] = Field(default=None, max_length=200)
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = Field(default=None, max_length=800)
    application_basis: Optional[AirRateSurchargeApplicationBasis] = None
    application_basis_reviewed_by: Optional[str] = Field(default=None, max_length=200)
    application_basis_reviewed_at: Optional[datetime] = None
    application_basis_review_note: Optional[str] = Field(default=None, max_length=800)

    @field_validator("surcharge_code", "currency", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return str(value or "").strip().upper()

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0 or value > Decimal("1000000"):
            raise ValueError("Air surcharge amount must be finite, positive and bounded.")
        return value

    @field_validator("reviewed_by", "review_note", "application_basis_reviewed_by", "application_basis_review_note", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        normalized = " ".join(str(value).strip().split())
        return normalized or None

    @field_validator("reviewed_at", "application_basis_reviewed_at")
    @classmethod
    def require_aware_review_time(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Air surcharge review timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_review_evidence(self):
        if self.status == "proposed":
            if self.reviewed_by is not None or self.reviewed_at is not None or self.review_note is not None:
                raise ValueError("Proposed air surcharge candidate cannot carry review evidence.")
        elif not self.reviewed_by or self.reviewed_at is None or not self.review_note:
            raise ValueError("Reviewed air surcharge candidate requires actor, time and note.")
        basis_evidence = (
            self.application_basis,
            self.application_basis_reviewed_by,
            self.application_basis_reviewed_at,
            self.application_basis_review_note,
        )
        if any(item is not None for item in basis_evidence):
            if self.status != "confirmed":
                raise ValueError("Only confirmed air surcharge candidates may carry application-basis review evidence.")
            if not all(item is not None for item in basis_evidence):
                raise ValueError("Air surcharge application basis requires basis, actor, time and note.")
            if self.basis == "flat" and self.application_basis != "flat":
                raise ValueError("Flat air surcharge may only use flat application basis.")
            if self.basis == "per_kg" and self.application_basis not in {"actual_weight", "chargeable_weight", "pivot_billed_weight"}:
                raise ValueError("Per-kg air surcharge requires an explicit weight application basis.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False


class AirRateSurchargeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    structure_review_id: str = Field(min_length=1, max_length=200)
    extracted_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extractor_version: Literal["air_rate_surcharge_v1"] = "air_rate_surcharge_v1"
    ai_parser_called: Literal[False] = False
    candidates: list[AirRateSurchargeCandidate] = Field(default_factory=list, max_length=100)
    status: AirRateSurchargeReviewStatus = "pending"
    requested_by: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("requested_by", mode="before")
    @classmethod
    def normalize_actor(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air surcharge review created_at must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_status(self):
        proposed = sum(item.status == "proposed" for item in self.candidates)
        if not self.candidates:
            expected = "no_candidates"
        elif proposed == len(self.candidates):
            expected = "pending"
        elif proposed:
            expected = "partially_reviewed"
        else:
            expected = "completed"
        if self.status != expected:
            raise ValueError("Air surcharge review status does not match candidate states.")
        if len({item.candidate_id for item in self.candidates}) != len(self.candidates):
            raise ValueError("Air surcharge candidate identifiers must be unique.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False
