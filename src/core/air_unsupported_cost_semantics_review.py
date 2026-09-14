from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirUnsupportedCostSemantic = Literal[
    "weight_based_additional_cost",
    "percentage_additional_cost",
    "minimum_tiered_formula_additional_cost",
    "customs_duties_taxes",
    "other_unmodeled_cost",
]
AirUnsupportedCostSemanticStatus = Literal[
    "unresolved", "not_applicable", "applicable_unresolved"
]

AIR_UNSUPPORTED_COST_SEMANTICS = (
    "weight_based_additional_cost",
    "percentage_additional_cost",
    "minimum_tiered_formula_additional_cost",
    "customs_duties_taxes",
    "other_unmodeled_cost",
)


class AirUnsupportedCostSemanticRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic: AirUnsupportedCostSemantic
    status: AirUnsupportedCostSemanticStatus
    rationale: str = Field(min_length=1, max_length=800)

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_rationale(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None


class AirUnsupportedCostSemanticsReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    inquiry_reference: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements: list[AirUnsupportedCostSemanticRequirement] = Field(min_length=5, max_length=5)
    review_note: str = Field(min_length=1, max_length=1200)
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["air_unsupported_cost_semantics_review_v1"] = "air_unsupported_cost_semantics_review_v1"

    @field_validator("entry_id", "inquiry_reference", "review_note", "reviewed_by", mode="before")
    @classmethod
    def normalize_text(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air unsupported-cost semantics review timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def require_exact_semantic_set(self):
        semantics = [item.semantic for item in self.requirements]
        if len(semantics) != len(set(semantics)):
            raise ValueError("Air unsupported-cost semantic categories must be unique.")
        if set(semantics) != set(AIR_UNSUPPORTED_COST_SEMANTICS):
            raise ValueError("Air unsupported-cost review must classify every supported semantic exactly once.")
        return self

    @property
    def semantics_classification_complete(self) -> bool:
        return all(item.status != "unresolved" for item in self.requirements)

    @property
    def applicable_unresolved_semantics(self) -> list[str]:
        return [item.semantic for item in self.requirements if item.status == "applicable_unresolved"]

    @property
    def unresolved_semantics(self) -> list[str]:
        return [item.semantic for item in self.requirements if item.status == "unresolved"]

    @property
    def unsupported_semantics_cleared(self) -> bool:
        return self.semantics_classification_complete and not self.applicable_unresolved_semantics
