from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any

from src.core.attachment_interpretation_review import AttachmentInterpretationReview
from src.core.attachment_interpretation_review_repository import (
    AttachmentInterpretationReviewRepository,
)
from src.core.attachment_interpretation_review_service import (
    build_attachment_review_preview,
    supplier_rfq_review_snapshot_sha256,
)
from src.core.supplier_rfq_repository import SupplierRFQRepository

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PRIORITY_RANK = {"critical": 0, "high": 1, "normal": 2, "low": 3}


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _strict_date(value: Any) -> date | None:
    if not isinstance(value, str) or _ISO_DATE.fullmatch(value.strip()) is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _age_score(age_hours: int) -> tuple[int, str | None]:
    if age_hours >= 48:
        return 30, "review_age_48h_plus"
    if age_hours >= 24:
        return 20, "review_age_24h_plus"
    if age_hours >= 12:
        return 10, "review_age_12h_plus"
    if age_hours >= 4:
        return 5, "review_age_4h_plus"
    return 0, None


def _deadline_score(days: int, *, kind: str) -> tuple[int, str]:
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


def _priority_band(score: int) -> str:
    if score >= 70:
        return "critical"
    if score >= 45:
        return "high"
    if score >= 20:
        return "normal"
    return "low"


def _candidate_dates(review: AttachmentInterpretationReview) -> list[tuple[str, date]]:
    pairs: list[tuple[str, date]] = []
    if review.route == "customer" and review.customer_candidate is not None:
        raw = (
            ("required_delivery", review.customer_candidate.required_delivery_date),
            ("cargo_ready", review.customer_candidate.cargo_ready_date),
        )
    elif review.supplier_candidate is not None:
        raw = (
            ("quote_validity", review.supplier_candidate.validity_date),
            ("vehicle_available", review.supplier_candidate.vehicle_available_date),
        )
    else:
        raw = ()
    for kind, value in raw:
        parsed = _strict_date(value)
        if parsed is not None:
            pairs.append((kind, parsed))
    return pairs


def build_attachment_review_queue_item(
    review: AttachmentInterpretationReview,
    *,
    supplier_repository: SupplierRFQRepository,
    now: datetime,
) -> dict[str, Any]:
    current = _aware_utc(now)
    created = _aware_utc(review.created_at)
    age_hours = max(0, int((current - created).total_seconds() // 3600))
    score = 10
    reasons: list[str] = []

    age_points, age_reason = _age_score(age_hours)
    score += age_points
    if age_reason:
        reasons.append(age_reason)

    preview = build_attachment_review_preview(review, {})
    blocker_count = len(preview["blockers"])
    warning_count = len(preview["warnings"])
    critical_attention_count = int(preview["critical_attention_count"])
    if blocker_count:
        score += min(30, blocker_count * 30)
        reasons.append("baseline_not_apply_ready")
    if critical_attention_count:
        score += min(45, critical_attention_count * 15)
        reasons.append("critical_fields_need_attention")
    if warning_count:
        score += min(20, warning_count * 5)
        reasons.append("review_warnings_present")

    if review.route == "supplier":
        draft = supplier_repository.get_draft(review.rfq_id or "")
        if draft is None:
            score += 60
            reasons.append("supplier_rfq_missing")
        elif review.expected_rfq_snapshot_sha256 != supplier_rfq_review_snapshot_sha256(draft):
            score += 60
            reasons.append("supplier_rfq_snapshot_stale")
        elif draft.status not in {"awaiting_response", "clarification_required"}:
            score += 40
            reasons.append("supplier_rfq_no_longer_review_applicable")

    nearest_kind = None
    nearest_days = None
    for kind, deadline in _candidate_dates(review):
        days = (deadline - current.date()).days
        points, reason = _deadline_score(days, kind=kind)
        score += points
        if points:
            reasons.append(reason)
        if nearest_days is None or days < nearest_days:
            nearest_kind, nearest_days = kind, days

    score = min(100, score)
    band = _priority_band(score)
    return {
        "review_id": review.review_id,
        "route": review.route,
        "status": review.status,
        "created_at": review.created_at,
        "age_hours": age_hours,
        "priority_band": band,
        "priority_score": score,
        "priority_reasons": sorted(set(reasons)),
        "critical_attention_count": critical_attention_count,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "nearest_deadline_kind": nearest_kind,
        "days_until_nearest_deadline": nearest_days,
        "rfq_id": review.rfq_id,
    }


def build_attachment_review_queue(
    *,
    repository: AttachmentInterpretationReviewRepository,
    supplier_repository: SupplierRFQRepository,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _aware_utc(now or datetime.now(timezone.utc))
    items = [
        build_attachment_review_queue_item(
            review,
            supplier_repository=supplier_repository,
            now=current,
        )
        for review in repository.list_all()
        if review.status == "pending"
    ]
    items.sort(
        key=lambda item: (
            _PRIORITY_RANK[item["priority_band"]],
            -item["priority_score"],
            item["days_until_nearest_deadline"] if item["days_until_nearest_deadline"] is not None else 10**9,
            _aware_utc(item["created_at"]),
            item["review_id"],
        )
    )
    counts = {band: 0 for band in ("critical", "high", "normal", "low")}
    for item in items:
        counts[item["priority_band"]] += 1
    return {
        "generated_at": current,
        "pending_count": len(items),
        "priority_counts": counts,
        "items": items,
    }
