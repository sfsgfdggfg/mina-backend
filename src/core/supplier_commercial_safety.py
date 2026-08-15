from __future__ import annotations

from datetime import date, timedelta
from math import ceil
import re
from typing import Literal

from pydantic import BaseModel, Field

from src.core.models import Shipment
from src.core.supplier_rfq import SupplierRFQResponse


TransitUnit = Literal[
    "hours",
    "calendar_days",
    "business_days",
    "weeks",
]


class ParsedTransit(BaseModel):
    maximum_value: int
    unit: TransitUnit
    scoring_days: int


class SupplierCommercialSafety(BaseModel):
    eligible_for_customer_quote: bool
    reasons: list[str] = Field(default_factory=list)

    transit_days: int | None = None
    validity_date: date | None = None
    vehicle_available_date: date | None = None
    projected_delivery_date: date | None = None
    delivery_deadline_met: bool | None = None

    source: str = "supplier_commercial_safety_engine"


_TRANSIT_PATTERN = re.compile(
    r"(?P<first>\d+)"
    r"(?:\s*[-–—]\s*(?P<second>\d+))?"
    r"\s*"
    r"(?P<unit>"
    r"business\s*days?|working\s*days?|"
    r"iş\s*günü|is\s*gunu|"
    r"days?|gün|gun|"
    r"hours?|hrs?|saat|"
    r"weeks?|hafta"
    r")",
    flags=re.IGNORECASE,
)


def parse_commercial_date(value: str | None) -> date | None:
    if not value:
        return None

    normalized = str(value).strip()

    for separator in ("T", " "):
        if separator in normalized:
            normalized = normalized.split(separator, 1)[0]

    formats = (
        "%Y-%m-%d",
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%d-%m-%Y",
    )

    from datetime import datetime

    for date_format in formats:
        try:
            return datetime.strptime(
                normalized,
                date_format,
            ).date()
        except ValueError:
            continue

    return None


def parse_transit_time(
    value: str | None,
) -> ParsedTransit | None:
    if not value:
        return None

    match = _TRANSIT_PATTERN.search(
        str(value).strip().lower()
    )

    if match is None:
        return None

    first = int(match.group("first"))
    second = match.group("second")

    maximum = max(
        first,
        int(second) if second is not None else first,
    )

    raw_unit = match.group("unit").lower()

    if raw_unit in {
        "hour",
        "hours",
        "hr",
        "hrs",
        "saat",
    }:
        return ParsedTransit(
            maximum_value=maximum,
            unit="hours",
            scoring_days=max(1, ceil(maximum / 24)),
        )

    if raw_unit in {
        "week",
        "weeks",
        "hafta",
    }:
        return ParsedTransit(
            maximum_value=maximum,
            unit="weeks",
            scoring_days=maximum * 7,
        )

    if (
        "business" in raw_unit
        or "working" in raw_unit
        or "iş" in raw_unit
        or "is " in raw_unit
    ):
        return ParsedTransit(
            maximum_value=maximum,
            unit="business_days",
            scoring_days=maximum,
        )

    return ParsedTransit(
        maximum_value=maximum,
        unit="calendar_days",
        scoring_days=maximum,
    )


def _add_business_days(
    start: date,
    business_days: int,
) -> date:
    current = start
    remaining = business_days

    while remaining > 0:
        current += timedelta(days=1)

        if current.weekday() < 5:
            remaining -= 1

    return current


def projected_delivery_date(
    start: date,
    transit: ParsedTransit,
) -> date:
    if transit.unit == "business_days":
        return _add_business_days(
            start,
            transit.maximum_value,
        )

    if transit.unit == "hours":
        return start + timedelta(
            days=max(
                1,
                ceil(transit.maximum_value / 24),
            )
        )

    if transit.unit == "weeks":
        return start + timedelta(
            days=transit.maximum_value * 7
        )

    return start + timedelta(
        days=transit.maximum_value
    )


def _normalize_equipment(value: str | None) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ç", "c")
        .replace("Ç", "c")
        .replace("ğ", "g")
        .replace("Ğ", "g")
    )


def _equipment_family(value: str | None) -> str:
    normalized = _normalize_equipment(value)

    families = (
        (
            "tenteli",
            (
                "tenteli",
                "curtainsider",
                "curtain sider",
                "curtain",
            ),
        ),
        ("mega", ("mega",)),
        (
            "reefer",
            (
                "reefer",
                "frigo",
                "refrigerated",
            ),
        ),
        (
            "lowbed",
            (
                "lowbed",
                "low bed",
            ),
        ),
        (
            "box",
            (
                "box",
                "kapali",
                "closed body",
            ),
        ),
    )

    for family, signals in families:
        if any(signal in normalized for signal in signals):
            return family

    return normalized


def equipment_matches(
    expected: str | None,
    offered: str | None,
) -> bool:
    if not expected or not offered:
        return False

    return (
        _equipment_family(expected)
        == _equipment_family(offered)
    )


def evaluate_supplier_commercial_safety(
    *,
    response: SupplierRFQResponse,
    shipment: Shipment,
    expected_equipment: str | None,
    as_of: date | None = None,
) -> SupplierCommercialSafety:
    reasons: list[str] = []
    reference_date = as_of or date.today()

    if not response.is_price_usable:
        reasons.append("supplier_price_not_usable")

    transit = parse_transit_time(
        response.transit_time
    )

    if transit is None:
        reasons.append(
            "supplier_transit_missing_or_unparseable"
        )

    validity = parse_commercial_date(
        response.validity_date
    )

    if validity is None:
        reasons.append(
            "supplier_validity_date_missing_or_invalid"
        )
    elif validity < reference_date:
        reasons.append("supplier_quote_expired")

    vehicle_available = parse_commercial_date(
        response.vehicle_available_date
    )

    if vehicle_available is None:
        reasons.append(
            "supplier_vehicle_availability_missing_or_invalid"
        )

    if not response.equipment_type:
        reasons.append("supplier_equipment_missing")
    elif not equipment_matches(
        expected_equipment,
        response.equipment_type,
    ):
        reasons.append("supplier_equipment_mismatch")

    if response.pricing_basis != "all_in":
        reasons.append(
            "supplier_price_not_confirmed_all_in"
        )

    if response.included_costs is None:
        reasons.append(
            "supplier_included_costs_unknown"
        )

    if response.excluded_costs is None:
        reasons.append(
            "supplier_excluded_costs_unknown"
        )
    elif response.excluded_costs:
        reasons.append(
            "supplier_has_excluded_costs"
        )

    cargo_ready = parse_commercial_date(
        shipment.cargo_ready_date
    )
    required_delivery = parse_commercial_date(
        shipment.required_delivery_date
    )

    projected = None
    deadline_met = None

    if cargo_ready is None:
        reasons.append(
            "cargo_ready_date_missing_or_invalid"
        )

    if required_delivery is None:
        reasons.append(
            "required_delivery_date_missing_or_invalid"
        )

    if (
        cargo_ready is not None
        and required_delivery is not None
        and vehicle_available is not None
        and transit is not None
    ):
        transport_start = max(
            cargo_ready,
            vehicle_available,
        )

        projected = projected_delivery_date(
            transport_start,
            transit,
        )

        deadline_met = (
            projected <= required_delivery
        )

        if not deadline_met:
            reasons.append(
                "required_delivery_date_not_achievable"
            )

    return SupplierCommercialSafety(
        eligible_for_customer_quote=not reasons,
        reasons=reasons,
        transit_days=(
            transit.scoring_days
            if transit is not None
            else None
        ),
        validity_date=validity,
        vehicle_available_date=vehicle_available,
        projected_delivery_date=projected,
        delivery_deadline_met=deadline_met,
    )
