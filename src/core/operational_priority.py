from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PRIORITY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def strict_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or ISO_DATE_PATTERN.fullmatch(value.strip()) is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def age_score(age_hours: int, *, reason_prefix: str = "work_age") -> tuple[int, str | None]:
    if age_hours >= 48:
        return 30, f"{reason_prefix}_48h_plus"
    if age_hours >= 24:
        return 20, f"{reason_prefix}_24h_plus"
    if age_hours >= 12:
        return 10, f"{reason_prefix}_12h_plus"
    if age_hours >= 4:
        return 5, f"{reason_prefix}_4h_plus"
    return 0, None


def deadline_score(days: int, *, kind: str) -> tuple[int, str]:
    weights = {
        "required_delivery": (40, 35, 25, 12),
        "cargo_ready": (25, 20, 15, 8),
        "quote_validity": (35, 30, 20, 10),
        "vehicle_available": (20, 18, 12, 5),
    }
    overdue, today, soon, week = weights[kind]
    if days < 0:
        return overdue, f"{kind}_overdue"
    if days == 0:
        return today, f"{kind}_today"
    if days <= 2:
        return soon, f"{kind}_within_2d"
    if days <= 7:
        return week, f"{kind}_within_7d"
    return 0, f"{kind}_future"


def priority_band(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 20:
        return "normal"
    return "low"
