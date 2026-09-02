from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_TURKIYE_TZ = ZoneInfo("Europe/Istanbul")


def _normalize(text: str | None) -> str:
    return (
        str(text or "")
        .replace("İ", "i")
        .replace("I", "i")
        .lower()
        .replace("ı", "i")
        .replace("ü", "u")
        .replace("ö", "o")
        .replace("ş", "s")
        .replace("ç", "c")
        .replace("ğ", "g")
    )


def _reference_date(received_at: datetime | None):
    if received_at is None:
        return None
    if received_at.tzinfo is not None:
        return received_at.astimezone(_TURKIYE_TZ).date()
    return received_at.date()


def _positive_relative_availability(text: str | None) -> int | None:
    normalized = _normalize(text)
    if not normalized:
        return None

    # Explicit negative availability must never become a positive date.
    negative = (
        r"(?:hazir|musait|uygun|available).{0,12}(?:degil|yok|not\s+available)",
        r"(?:arac|tir|kamyon|yuk|malzeme|urun).{0,25}(?:hazir|musait).{0,12}(?:degil|yok)",
    )
    if any(re.search(pattern, normalized) for pattern in negative):
        return None

    availability = r"(?:hazir|musait|uygun|available|yuklenebilir|yukleme\s+yapabilir)"
    subject = r"(?:arac(?:imiz)?|tir|kamyon|yuk|malzeme|urun)"

    tomorrow_patterns = (
        rf"(?:yarin|tomorrow).{{0,30}}{availability}",
        rf"{availability}.{{0,30}}(?:yarin|tomorrow)",
    )
    if any(re.search(pattern, normalized) for pattern in tomorrow_patterns):
        return 1

    today_patterns = (
        rf"(?:bugun|today|hemen).{{0,30}}{availability}",
        rf"{availability}.{{0,30}}(?:bugun|today|hemen)",
        rf"{subject}.{{0,18}}{availability}",
        r"hemen\s+yukleme\s+yapabilir",
    )
    if any(re.search(pattern, normalized) for pattern in today_patterns):
        return 0

    return None


def infer_customer_cargo_ready_date(
    text: str | None, received_at: datetime | None
) -> str | None:
    base = _reference_date(received_at)
    offset = _positive_relative_availability(text)
    if base is None or offset is None:
        return None
    return (base + timedelta(days=offset)).isoformat()


def infer_supplier_vehicle_available_date(
    text: str | None, received_at: datetime | None
) -> str | None:
    base = _reference_date(received_at)
    offset = _positive_relative_availability(text)
    if base is None or offset is None:
        return None
    return (base + timedelta(days=offset)).isoformat()


_QUOTE_CONTEXT_PATTERN = re.compile(
    r"(?:fiyat|teklif|navlun|price|quote|rate|quotation)"
)


def _reference_datetime(received_at: datetime | None) -> datetime | None:
    if received_at is None:
        return None
    if received_at.tzinfo is None:
        return received_at.replace(tzinfo=_TURKIYE_TZ)
    return received_at.astimezone(_TURKIYE_TZ)


def infer_customer_quote_deadline(
    text: str | None,
    received_at: datetime | None,
) -> datetime | None:
    """Resolve only explicit quote-response timing evidence.

    Urgency words alone never create a deadline. Relative expressions are
    anchored to the actual inbound message time in Europe/Istanbul.
    """

    normalized = _normalize(text)
    base = _reference_datetime(received_at)
    if not normalized or base is None:
        return None
    if _QUOTE_CONTEXT_PATTERN.search(normalized) is None:
        return None

    duration_patterns = (
        (r"(\d{1,3})\s*(?:dakika|dk)\s*icinde", "minutes"),
        (r"(\d{1,2})\s*saat\s*icinde", "hours"),
        (r"within\s+(\d{1,3})\s*(?:minutes?|mins?)", "minutes"),
        (r"within\s+(\d{1,2})\s*(?:hours?|hrs?)", "hours"),
    )
    for pattern, unit in duration_patterns:
        match = re.search(pattern, normalized)
        if match is not None:
            amount = int(match.group(1))
            if amount <= 0:
                return None
            delta = timedelta(**{unit: amount})
            return base + delta

    time_pattern = (
        r"(?<!\d)(?P<hour>(?:[01]?\d|2[0-3]))"
        r"[:.](?P<minute>[0-5]\d)(?!\d)"
    )
    until = r"\s*(?:['’]?[ea])?\s*(?:kadar|by|before)"

    dated_patterns = (
        rf"(?P<day>0?[1-9]|[12]\d|3[01])[./-](?P<month>0?[1-9]|1[0-2])[./-](?P<year>20\d{{2}}).{{0,20}}{time_pattern}.{{0,12}}{until}",
        rf"(?P<year>20\d{{2}})-(?P<month>0?[1-9]|1[0-2])-(?P<day>0?[1-9]|[12]\d|3[01]).{{0,20}}{time_pattern}.{{0,12}}{until}",
    )
    for pattern in dated_patterns:
        match = re.search(pattern, normalized)
        if match is not None:
            try:
                candidate = datetime(
                    int(match.group("year")),
                    int(match.group("month")),
                    int(match.group("day")),
                    int(match.group("hour")),
                    int(match.group("minute")),
                    tzinfo=_TURKIYE_TZ,
                )
            except ValueError:
                return None
            return candidate if candidate > base else None

    relative_day_patterns = (
        ("today", 0), ("bugun", 0), ("tomorrow", 1), ("yarin", 1),
    )
    for token, offset in relative_day_patterns:
        match = re.search(
            rf"{token}.{{0,20}}{time_pattern}.{{0,12}}{until}",
            normalized,
        )
        if match is not None:
            target_date = base.date() + timedelta(days=offset)
            candidate = datetime(
                target_date.year,
                target_date.month,
                target_date.day,
                int(match.group("hour")),
                int(match.group("minute")),
                tzinfo=_TURKIYE_TZ,
            )
            return candidate if candidate > base else None

    if re.search(r"(?:ogle|noon).{0,12}(?:kadar|by|before)", normalized):
        candidate = base.replace(hour=12, minute=0, second=0, microsecond=0)
        return candidate if candidate > base else None

    match = re.search(rf"{time_pattern}.{{0,12}}{until}", normalized)
    if match is not None:
        candidate = base.replace(
            hour=int(match.group("hour")),
            minute=int(match.group("minute")),
            second=0,
            microsecond=0,
        )
        return candidate if candidate > base else None

    return None
