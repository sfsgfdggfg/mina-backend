from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirRateStructureCandidateKind = Literal[
    "weight_break",
    "surcharge_label",
    "currency",
    "volumetric_divisor",
    "cargo_scope_hint",
]
AirRateStructureCandidateStatus = Literal["proposed", "confirmed", "rejected"]
AirRateStructureReviewStatus = Literal[
    "pending", "partially_reviewed", "completed", "no_candidates"
]


class AirRateStructureCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=12, max_length=64)
    kind: AirRateStructureCandidateKind
    value: str = Field(min_length=1, max_length=120)
    occurrence_count: int = Field(ge=1, le=5000)
    source_line_numbers: list[int] = Field(default_factory=list, max_length=20)
    detection_method: Literal["deterministic_text_v1"] = "deterministic_text_v1"
    status: AirRateStructureCandidateStatus = "proposed"
    reviewed_by: Optional[str] = Field(default=None, max_length=200)
    reviewed_at: Optional[datetime] = None
    review_note: Optional[str] = Field(default=None, max_length=800)

    @field_validator("value", "reviewed_by", "review_note", mode="before")
    @classmethod
    def normalize_text(cls, value):
        if value is None:
            return None
        normalized = " ".join(str(value).strip().split())
        return normalized or None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_review_time(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is not None and value.tzinfo is None:
            raise ValueError("Air rate candidate review timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def validate_review_evidence(self):
        if self.status == "proposed":
            if self.reviewed_by is not None or self.reviewed_at is not None or self.review_note is not None:
                raise ValueError("Proposed air-rate structure candidate cannot carry review evidence.")
        elif not self.reviewed_by or self.reviewed_at is None or not self.review_note:
            raise ValueError("Reviewed air-rate structure candidate requires actor, time and note.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False


class AirRateStructureReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extracted_text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    extracted_character_count: int = Field(ge=1, le=100_000)
    extractor_version: Literal["air_rate_structure_v1"] = "air_rate_structure_v1"
    ai_parser_called: Literal[False] = False
    candidates: list[AirRateStructureCandidate] = Field(default_factory=list, max_length=100)
    status: AirRateStructureReviewStatus = "pending"
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
            raise ValueError("Air rate structure review created_at must be timezone-aware.")
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
            raise ValueError("Air rate structure review status does not match candidate states.")
        return self

    @property
    def runtime_authoritative(self) -> bool:
        return False
