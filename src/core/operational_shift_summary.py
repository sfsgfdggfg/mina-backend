from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    build_my_operational_work_view,
    decorate_operational_work_queue,
    work_state_fingerprint,
)
from src.core.operational_work_queue import build_operational_work_queue

SHIFT_HANDOFF_WINDOW_HOURS = 12
SHIFT_HANDOFF_LIMIT = 20


def _safe_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "work_id", "work_type", "resource_type", "route", "status", "next_action",
        "created_at", "age_hours", "priority_band", "priority_score", "priority_reasons",
        "critical_attention_count", "blocker_count", "warning_count",
        "nearest_deadline_kind", "days_until_nearest_deadline",
    )
    return {key: item[key] for key in keys if key in item}


def _handoff_work_type(work_id: str) -> str:
    return work_id.split(":", 1)[0] if ":" in work_id else "operational_work"


def build_operational_shift_summary(
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
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    raw_queue = build_operational_work_queue(
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=current,
    )
    queue = decorate_operational_work_queue(raw_queue, assignment_repository, now=current)
    queue_by_id = {item["work_id"]: item for item in raw_queue.get("items", [])}
    decorated_by_id = {item["work_id"]: item for item in queue.get("items", [])}

    my_work = build_my_operational_work_view(
        operator_name=operator_name,
        assignment_repository=assignment_repository,
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=current,
    )

    cutoff = current - timedelta(hours=SHIFT_HANDOFF_WINDOW_HOURS)
    handoffs: list[dict[str, Any]] = []
    for assignment in reversed(assignment_repository.list_history()):
        if (
            assignment.status != "released"
            or assignment.release_reason != "shift_handoff"
            or assignment.released_by != operator_name
            or assignment.released_at is None
            or assignment.released_at < cutoff
        ):
            continue
        current_item = queue_by_id.get(assignment.work_id)
        if current_item is None:
            disposition = "resolved_or_inactive"
        elif assignment.work_state_sha256 != work_state_fingerprint(current_item):
            disposition = "state_changed"
        else:
            assignment_status = decorated_by_id[assignment.work_id].get("assignment_status")
            disposition = {
                "unassigned": "available_unassigned",
                "assigned": "claimed",
                "acknowledged": "claimed",
                "expired": "expired_assignment",
            }.get(assignment_status, "state_changed")
        handoffs.append({
            "work_id": assignment.work_id,
            "work_type": _handoff_work_type(assignment.work_id),
            "released_at": assignment.released_at,
            "assignment_generation": assignment.generation,
            "current_disposition": disposition,
        })
        if len(handoffs) >= SHIFT_HANDOFF_LIMIT:
            break

    critical_unassigned = [
        _safe_queue_item(item)
        for item in queue.get("items", [])
        if item.get("priority_band") == "critical"
        and item.get("assignment_status") == "unassigned"
    ]

    return {
        "generated_at": current,
        "scope": "authenticated_operator",
        "handoff_window_hours": SHIFT_HANDOFF_WINDOW_HOURS,
        "overview": {
            "pending_count": raw_queue.get("pending_count", 0),
            "critical_pending_count": raw_queue.get("priority_counts", {}).get("critical", 0),
            "my_active_count": my_work["active_count"],
            "my_expiring_soon_count": my_work["expiring_soon_count"],
            "recent_handoff_count": len(handoffs),
            "critical_unassigned_count": len(critical_unassigned),
        },
        "my_work": my_work,
        "recent_handoffs": {"count": len(handoffs), "items": handoffs},
        "critical_unassigned": {"count": len(critical_unassigned), "items": critical_unassigned},
        "authority": {
            "summary_is_read_only": True,
            "assignment_is_coordination_only": True,
            "existing_workflow_guards_remain_authoritative": True,
        },
    }
