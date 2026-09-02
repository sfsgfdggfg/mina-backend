from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def _parse_clock(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _local(value: datetime, timezone_name: str) -> datetime:
    zone = ZoneInfo(timezone_name)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).astimezone(zone)
    return value.astimezone(zone)


def is_business_time(value: datetime, policy) -> bool:
    local = _local(value, policy.business_timezone)
    if local.weekday() not in set(policy.business_weekdays):
        return False
    start = _parse_clock(policy.business_day_start)
    end = _parse_clock(policy.business_day_end)
    clock = local.timetz().replace(tzinfo=None)
    return start <= clock < end


def next_business_open(value: datetime, policy) -> datetime:
    local = _local(value, policy.business_timezone)
    start = _parse_clock(policy.business_day_start)
    end = _parse_clock(policy.business_day_end)
    weekdays = set(policy.business_weekdays)
    for offset in range(0, 15):
        day = (local + timedelta(days=offset)).date()
        if day.weekday() not in weekdays:
            continue
        opening = datetime.combine(day, start, tzinfo=local.tzinfo)
        closing = datetime.combine(day, end, tzinfo=local.tzinfo)
        if offset == 0:
            if local < opening:
                return opening.astimezone(timezone.utc)
            if local < closing:
                return local.astimezone(timezone.utc)
            continue
        return opening.astimezone(timezone.utc)
    raise ValueError("No business opening found within the supported calendar window.")


def previous_business_close(value: datetime, policy) -> datetime:
    local = _local(value, policy.business_timezone)
    start = _parse_clock(policy.business_day_start)
    end = _parse_clock(policy.business_day_end)
    weekdays = set(policy.business_weekdays)
    for offset in range(0, 15):
        day = (local - timedelta(days=offset)).date()
        if day.weekday() not in weekdays:
            continue
        opening = datetime.combine(day, start, tzinfo=local.tzinfo)
        closing = datetime.combine(day, end, tzinfo=local.tzinfo)
        if offset == 0:
            if local > closing:
                return closing.astimezone(timezone.utc)
            if local >= opening:
                return local.astimezone(timezone.utc)
            continue
        return closing.astimezone(timezone.utc)
    raise ValueError("No prior business close found within the supported calendar window.")


def add_business_minutes(anchor: datetime, minutes: int, policy) -> datetime:
    if minutes < 0:
        raise ValueError("Business minutes must be non-negative.")
    current = next_business_open(anchor, policy)
    remaining = int(minutes)
    if remaining == 0:
        return current
    zone = ZoneInfo(policy.business_timezone)
    end = _parse_clock(policy.business_day_end)
    while remaining > 0:
        local = current.astimezone(zone)
        closing = datetime.combine(local.date(), end, tzinfo=zone)
        available = max(0, int((closing - local).total_seconds() // 60))
        if remaining <= available:
            return (local + timedelta(minutes=remaining)).astimezone(timezone.utc)
        remaining -= available
        current = next_business_open(closing + timedelta(seconds=1), policy)
    return current


def proactive_customer_update_due(deadline: datetime, lead_minutes: int, policy) -> datetime:
    local_deadline = _local(deadline, policy.business_timezone)
    raw_due = local_deadline - timedelta(minutes=lead_minutes)
    if is_business_time(raw_due, policy):
        return raw_due.astimezone(timezone.utc)

    start = _parse_clock(policy.business_day_start)
    end = _parse_clock(policy.business_day_end)
    weekdays = set(policy.business_weekdays)
    if local_deadline.weekday() in weekdays:
        opening = datetime.combine(local_deadline.date(), start, tzinfo=local_deadline.tzinfo)
        closing = datetime.combine(local_deadline.date(), end, tzinfo=local_deadline.tzinfo)
        if local_deadline >= closing:
            return (closing - timedelta(minutes=lead_minutes)).astimezone(timezone.utc)
        if local_deadline >= opening and raw_due < opening:
            prior = previous_business_close(opening - timedelta(seconds=1), policy)
            return prior - timedelta(minutes=lead_minutes)

    prior = previous_business_close(local_deadline, policy)
    return prior - timedelta(minutes=lead_minutes)
