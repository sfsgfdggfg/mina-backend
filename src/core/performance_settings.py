from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


class PerformanceSettings(BaseModel):
    first_look_target_minutes: int | None = Field(default=15, ge=1, le=240)
    decision_target_minutes: int | None = Field(default=15, ge=1, le=480)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_by: str = Field(default="system_default", min_length=1, max_length=200)
    source: str = "agency_performance_settings"

    @field_validator("updated_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Performance settings timestamp must be timezone-aware.")
        return value


def default_performance_settings() -> PerformanceSettings:
    return PerformanceSettings()
