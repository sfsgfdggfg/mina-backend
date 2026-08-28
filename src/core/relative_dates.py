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
