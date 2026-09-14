from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


AirCostScopeCategory = Literal[
    "pickup",
    "origin_handling",
    "origin_terminal",
    "documentation",
    "customs_service_fee",
    "destination_handling",
    "destination_terminal",
    "delivery",
    "other",
]
AirCostScopeStatus = Literal["required", "not_applicable", "unresolved"]

AIR_COST_SCOPE_CATEGORIES = (
    "pickup",
    "origin_handling",
    "origin_terminal",
    "documentation",
    "customs_service_fee",
    "destination_handling",
    "destination_terminal",
    "delivery",
    "other",
)


class AirCostScopeRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: AirCostScopeCategory
    status: AirCostScopeStatus
    rationale: str = Field(min_length=1, max_length=800)

    @field_validator("rationale", mode="before")
    @classmethod
    def normalize_rationale(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None


class AirCostScopeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    inquiry_reference: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=200)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    requirements: list[AirCostScopeRequirement] = Field(min_length=9, max_length=9)
    review_note: str = Field(min_length=1, max_length=1200)
    reviewed_by: str = Field(min_length=1, max_length=200)
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source: Literal["air_cost_scope_review_v1"] = "air_cost_scope_review_v1"

    @field_validator("entry_id", "inquiry_reference", "review_note", "reviewed_by", mode="before")
    @classmethod
    def normalize_text(cls, value):
        normalized = " ".join(str(value or "").strip().split())
        return normalized or None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Air cost-scope review timestamp must be timezone-aware.")
        return value

    @model_validator(mode="after")
    def require_exact_category_set(self):
        categories = [item.category for item in self.requirements]
        if len(categories) != len(set(categories)):
            raise ValueError("Air cost-scope review categories must be unique.")
        if set(categories) != set(AIR_COST_SCOPE_CATEGORIES):
            raise ValueError("Air cost-scope review must classify every supported category exactly once.")
        return self

    @property
    def scope_classification_complete(self) -> bool:
        return all(item.status != "unresolved" for item in self.requirements)

    @property
    def required_categories(self) -> list[str]:
        return [item.category for item in self.requirements if item.status == "required"]

    @property
    def not_applicable_categories(self) -> list[str]:
        return [item.category for item in self.requirements if item.status == "not_applicable"]

    @property
    def unresolved_categories(self) -> list[str]:
        return [item.category for item in self.requirements if item.status == "unresolved"]

    @property
    def runtime_authoritative(self) -> bool:
        return False

    @property
    def pricing_authority(self) -> bool:
        return False

    @property
    def cost_completeness_authority(self) -> bool:
        return False
