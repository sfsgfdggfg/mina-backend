from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

SUPPLIER_TIMEZONE = "Europe/Istanbul"
SUPPLIER_DAY_START = "09:00"
SUPPLIER_DAY_END = "18:30"
SUPPLIER_HALF_DAY_END = "13:00"
SUPPLIER_WEEKDAYS = (0, 1, 2, 3, 4)
SUPPLIER_HOLIDAY_COVERAGE_YEARS = (2026, 2027, 2028)

_FIXED_FULL_HOLIDAYS = {
    (1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29),
}
_FIXED_HALF_HOLIDAYS = {(10, 28)}
_RELIGIOUS_FULL_HOLIDAYS = {
    2026: {(3, 20), (3, 21), (3, 22), (5, 27), (5, 28), (5, 29), (5, 30)},
    2027: {(3, 9), (3, 10), (3, 11), (5, 16), (5, 17), (5, 18), (5, 19)},
    2028: {(2, 26), (2, 27), (2, 28), (5, 5), (5, 6), (5, 7), (5, 8)},
}
_RELIGIOUS_HALF_HOLIDAYS = {
    2026: {(3, 19), (5, 26)},
    2027: {(3, 8), (5, 15)},
    2028: {(2, 25), (5, 4)},
}


class SupplierHolidayCalendarCoverageError(RuntimeError):
    pass


def _clock(value: str) -> time:
    hour, minute = map(int, value.split(":"))
    return time(hour=hour, minute=minute)


def _local(value: datetime) -> datetime:
    zone = ZoneInfo(SUPPLIER_TIMEZONE)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone(zone)
    return value.astimezone(zone)


def supplier_calendar_metadata() -> dict:
    return {
        "timezone": SUPPLIER_TIMEZONE,
        "start": SUPPLIER_DAY_START,
        "end": SUPPLIER_DAY_END,
        "weekdays": list(SUPPLIER_WEEKDAYS),
        "holiday_country": "TR",
        "holiday_source": "official_2429_and_diyanet_verified_calendar",
        "holiday_coverage_years": list(SUPPLIER_HOLIDAY_COVERAGE_YEARS),
        "half_day_close": SUPPLIER_HALF_DAY_END,
        "configurable": False,
    }


def _require_holiday_coverage(day: date) -> None:
    if day.year not in SUPPLIER_HOLIDAY_COVERAGE_YEARS:
        raise SupplierHolidayCalendarCoverageError(
            f"Turkey supplier holiday calendar is not verified for {day.year}."
        )


def _day_window(day: date) -> tuple[time, time] | None:
    if day.weekday() not in SUPPLIER_WEEKDAYS:
        return None
    _require_holiday_coverage(day)
    key = (day.month, day.day)
    if key in _FIXED_FULL_HOLIDAYS or key in _RELIGIOUS_FULL_HOLIDAYS[day.year]:
        return None
    end = (
        _clock(SUPPLIER_HALF_DAY_END)
        if key in _FIXED_HALF_HOLIDAYS or key in _RELIGIOUS_HALF_HOLIDAYS[day.year]
        else _clock(SUPPLIER_DAY_END)
    )
    return _clock(SUPPLIER_DAY_START), end


def is_supplier_business_time(value: datetime) -> bool:
    local = _local(value)
    window = _day_window(local.date())
    if window is None:
        return False
    start, end = window
    clock = local.timetz().replace(tzinfo=None)
    return start <= clock < end


def next_supplier_business_open(value: datetime) -> datetime:
    local = _local(value)
    zone = ZoneInfo(SUPPLIER_TIMEZONE)
    for offset in range(0, 370):
        day = (local + timedelta(days=offset)).date()
        window = _day_window(day)
        if window is None:
            continue
        start, end = window
        opening = datetime.combine(day, start, tzinfo=zone)
        closing = datetime.combine(day, end, tzinfo=zone)
        if offset == 0:
            if local < opening:
                return opening.astimezone(timezone.utc)
            if local < closing:
                return local.astimezone(timezone.utc)
            continue
        return opening.astimezone(timezone.utc)
    raise SupplierHolidayCalendarCoverageError(
        "No verified supplier business opening found in calendar coverage."
    )


def add_supplier_business_minutes(anchor: datetime, minutes: int) -> datetime:
    if minutes < 0:
        raise ValueError("Supplier business minutes must be non-negative.")
    current = next_supplier_business_open(anchor)
    remaining = int(minutes)
    if remaining == 0:
        return current
    zone = ZoneInfo(SUPPLIER_TIMEZONE)
    while remaining > 0:
        local = current.astimezone(zone)
        window = _day_window(local.date())
        if window is None:
            current = next_supplier_business_open(local + timedelta(days=1))
            continue
        _, end = window
        closing = datetime.combine(local.date(), end, tzinfo=zone)
        available = max(0, int((closing - local).total_seconds() // 60))
        if remaining <= available:
            return (local + timedelta(minutes=remaining)).astimezone(timezone.utc)
        remaining -= available
        current = next_supplier_business_open(closing + timedelta(seconds=1))
    return current
