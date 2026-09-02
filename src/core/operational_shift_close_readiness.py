from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.operational_shift_summary import build_operational_shift_summary
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import decorate_operational_work_queue
from src.core.operational_work_queue import build_operational_work_queue

INCOMPLETE_HANDOFF_DISPOSITIONS = frozenset({
    "available_unassigned",
    "expired_assignment",
    "state_changed",
})


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def _safe_active_item(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "work_id", "work_type", "resource_type", "route", "status", "next_action",
        "priority_band", "priority_score", "critical_attention_count", "blocker_count",
        "warning_count", "assignment_status", "assignment_generation", "lease_status",
        "lease_expires_at", "lease_seconds_remaining", "lease_attention",
    )
    return {key: item[key] for key in keys if key in item}


def _safe_expired_item(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "work_id", "work_type", "resource_type", "route", "status", "next_action",
        "priority_band", "priority_score", "critical_attention_count", "blocker_count",
        "warning_count", "assignment_status", "assignment_generation", "lease_status",
        "lease_expires_at", "legacy_lease_missing", "takeover_available",
    )
    return {key: item[key] for key in keys if key in item}


def build_operational_shift_close_readiness(
    *,
    operator_name: str,
    assignment_repository: OperationalWorkAssignmentRepository,
    attachment_repository,
    proposal_repository,
    supplier_repository,
    approval_repository,
    quote_case_repository,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _utc(now)
    args = {
        "assignment_repository": assignment_repository,
        "attachment_repository": attachment_repository,
        "proposal_repository": proposal_repository,
        "supplier_repository": supplier_repository,
        "approval_repository": approval_repository,
        "quote_case_repository": quote_case_repository,
    }
    summary = build_operational_shift_summary(operator_name=operator_name, now=current, **args)
    raw_queue = build_operational_work_queue(
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=current,
    )
    decorated = decorate_operational_work_queue(raw_queue, assignment_repository, now=current)

    active_items = [_safe_active_item(item) for item in summary["my_work"]["items"]]
    expired_items = [
        _safe_expired_item(item)
        for item in decorated.get("items", [])
        if item.get("assignment_status") == "expired"
        and item.get("assigned_to") == operator_name
    ]
    incomplete_handoffs = [
        dict(item)
        for item in summary["recent_handoffs"]["items"]
        if item.get("current_disposition") in INCOMPLETE_HANDOFF_DISPOSITIONS
    ]
    critical_unassigned = [
        _safe_expired_item(item)
        for item in decorated.get("items", [])
        if item.get("priority_band") == "critical"
        and not (
            item.get("assignment_status") in {"assigned", "acknowledged"}
            and item.get("lease_status") == "active"
        )
    ]

    blocker_codes: list[str] = []
    if active_items:
        blocker_codes.append("active_assignments_remaining")
    if expired_items:
        blocker_codes.append("expired_assignments_require_recovery")
    if incomplete_handoffs:
        blocker_codes.append("recent_handoffs_incomplete")
    if critical_unassigned:
        blocker_codes.append("critical_unassigned_work_requires_coverage")

    warning_codes: list[str] = []
    if summary["overview"]["my_expiring_soon_count"]:
        warning_codes.append("active_assignment_lease_expiring_soon")

    return {
        "generated_at": current,
        "scope": "authenticated_operator",
        "readiness": "ready" if not blocker_codes else "blocked",
        "ready_to_close": not blocker_codes,
        "blocker_count": len(blocker_codes),
        "blocker_codes": blocker_codes,
        "warning_codes": warning_codes,
        "checks": {
            "active_assignments_cleared": {"passed": not active_items, "count": len(active_items)},
            "expired_assignments_recovered": {"passed": not expired_items, "count": len(expired_items)},
            "recent_handoffs_complete": {"passed": not incomplete_handoffs, "count": len(incomplete_handoffs)},
            "critical_unassigned_covered": {"passed": not critical_unassigned, "count": len(critical_unassigned)},
        },
        "active_work": {"count": len(active_items), "items": active_items},
        "expired_work": {"count": len(expired_items), "items": expired_items},
        "incomplete_handoffs": {"count": len(incomplete_handoffs), "items": incomplete_handoffs},
        "critical_unassigned": {"count": len(critical_unassigned), "items": critical_unassigned},
        "remediation": {
            "active_assignments_remaining": ["work get", "work handoff", "work release"],
            "expired_assignments_require_recovery": ["work get", "work takeover", "work handoff", "work release"],
            "recent_handoffs_incomplete": ["work queue", "work get", "work assign"],
            "critical_unassigned_work_requires_coverage": ["work queue", "work get", "work assign"],
        },
        "authority": {
            "readiness_is_read_only": True,
            "readiness_does_not_close_shift": True,
            "assignment_is_coordination_only": True,
            "existing_workflow_guards_remain_authoritative": True,
        },
    }
