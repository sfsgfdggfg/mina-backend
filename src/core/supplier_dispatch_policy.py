from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


AGENCY_SUPPLIER_DISPATCH_POLICY_ENV = "MINAI_SUPPLIER_DISPATCH_POLICY_JSON"

DispatchMode = Literal["sequential", "parallel"]


class SupplierDispatchPolicy(BaseModel):
    mode: DispatchMode = "sequential"
    initial_supplier_count: int = Field(default=1, ge=1, le=3)
    source: str = "agency_supplier_dispatch_policy"
    primary_group_strategy: Literal["parallel_all"] = "parallel_all"
    no_response_reminder_minutes: int = Field(default=30, ge=5, le=240)
    acknowledged_grace_minutes: int = Field(default=120, ge=15, le=480)
    customer_deadline_proactive_minutes: int = Field(default=5, ge=1, le=30)
    automatic_supplier_reminders_enabled: bool = True
    automatic_customer_deadline_updates_enabled: bool = True
    business_timezone: str = "Europe/Istanbul"
    business_day_start: str = "09:00"
    business_day_end: str = "18:30"
    business_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    silence_counts_as_capacity_failure: bool = False
    urgent_customer_bypasses_primary_group: bool = False
    secondary_after_all_primary_unavailable: bool = True
    secondary_after_primary_price_negotiation_exhausted: bool = True


    @field_validator("business_day_start", "business_day_end")
    @classmethod
    def validate_business_clock(cls, value: str) -> str:
        normalized = value.strip()
        parts = normalized.split(":")
        if len(parts) != 2:
            raise ValueError("Business clock must use HH:MM format.")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValueError("Business clock must use HH:MM format.") from exc
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Business clock is outside the valid daily range.")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("business_weekdays")
    @classmethod
    def validate_business_weekdays(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        normalized = tuple(sorted(set(value)))
        if not normalized or any(day < 0 or day > 6 for day in normalized):
            raise ValueError("Business weekdays must contain day indexes 0 through 6.")
        return normalized

    @model_validator(mode="after")
    def validate_mode_count(self):
        start_hour, start_minute = map(int, self.business_day_start.split(":"))
        end_hour, end_minute = map(int, self.business_day_end.split(":"))
        if (start_hour, start_minute) >= (end_hour, end_minute):
            raise ValueError("Business day start must be earlier than business day end.")
        if self.business_timezone != "Europe/Istanbul":
            raise ValueError("P1-73 pilot supports Europe/Istanbul business timezone only.")
        if self.mode == "sequential" and self.initial_supplier_count != 1:
            raise ValueError(
                "Sequential supplier dispatch requires initial_supplier_count=1."
            )
        if self.mode == "parallel" and self.initial_supplier_count < 2:
            raise ValueError(
                "Parallel supplier dispatch requires initial_supplier_count >= 2."
            )
        return self


def resolve_supplier_dispatch_policy(
    environ: Mapping[str, str] | None = None,
) -> SupplierDispatchPolicy:
    env = environ if environ is not None else os.environ
    raw = (env.get(AGENCY_SUPPLIER_DISPATCH_POLICY_ENV) or "").strip()
    if not raw:
        return SupplierDispatchPolicy()
    try:
        payload = json.loads(raw)
        return SupplierDispatchPolicy.model_validate(payload)
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        raise ValueError(
            f"Agency supplier dispatch policy configuration is invalid: {exc}"
        ) from exc
