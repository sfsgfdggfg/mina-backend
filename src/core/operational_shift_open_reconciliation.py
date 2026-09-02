from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.operational_shift_close_attestation import (
    evaluate_operational_shift_close_receipt_status,
)
from src.core.operational_shift_close_receipt_repository import (
    OperationalShiftCloseReceiptRepository,
)
from src.core.operational_shift_summary import SHIFT_HANDOFF_LIMIT, SHIFT_HANDOFF_WINDOW_HOURS
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    decorate_operational_work_queue,
    work_state_fingerprint,
)
from src.core.operational_work_queue import build_operational_work_queue

INCOMPLETE_HANDOFF_DISPOSITIONS = frozenset({
    "available_unassigned",
    "expired_assignment",
    "state_changed",
})


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def _work_type(work_id: str) -> str:
    return work_id.split(":", 1)[0] if ":" in work_id else "operational_work"


def _safe_work_item(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "work_id", "work_type", "resource_type", "route", "status", "next_action",
        "priority_band", "priority_score", "critical_attention_count", "blocker_count",
        "warning_count", "nearest_deadline_kind", "days_until_nearest_deadline",
        "assignment_status", "assignment_generation", "lease_status", "lease_expires_at",
        "takeover_available", "stale_assignment_present",
    )
    return {key: item[key] for key in keys if key in item}


def _event_category(entity_type: str) -> str:
    if entity_type == "operational_work_assignment":
        return "work_coordination"
    if entity_type.startswith("attachment_"):
        return "attachment_review"
    if entity_type.startswith("extraction_"):
        return "customer_extraction"
    if entity_type.startswith("supplier_"):
        return "supplier_operations"
    if entity_type.startswith("quote_") or entity_type.startswith("customer_quote"):
        return "customer_quote"
    return "other_operational"


def _change_summary(
    receipt_state_event_id: int | None,
    assignment_repository: OperationalWorkAssignmentRepository,
) -> dict[str, Any]:
    store = getattr(assignment_repository, "store", None)
    if receipt_state_event_id is None or store is None or not hasattr(store, "summarize_events_after"):
        return {
            "tracking_status": "unavailable",
            "event_count": None,
            "category_counts": {},
            "first_change_at": None,
            "last_change_at": None,
        }
    raw = store.summarize_events_after(
        receipt_state_event_id,
        exclude_entity_type="operational_shift_close_receipt",
    )
    categories: dict[str, int] = {}
    for entity_type, count in raw.get("entity_type_counts", {}).items():
        category = _event_category(str(entity_type))
        categories[category] = categories.get(category, 0) + int(count)
    return {
        "tracking_status": "available",
        "event_count": int(raw.get("event_count", 0)),
        "category_counts": dict(sorted(categories.items())),
        "first_change_at": raw.get("first_created_at"),
        "last_change_at": raw.get("last_created_at"),
    }


def _global_incomplete_handoffs(
    *,
    assignment_repository: OperationalWorkAssignmentRepository,
    raw_queue: dict[str, Any],
    decorated_queue: dict[str, Any],
    now: datetime,
) -> list[dict[str, Any]]:
    raw_by_id = {item["work_id"]: item for item in raw_queue.get("items", [])}
    decorated_by_id = {item["work_id"]: item for item in decorated_queue.get("items", [])}
    cutoff = now - timedelta(hours=SHIFT_HANDOFF_WINDOW_HOURS)
    seen_work_ids: set[str] = set()
    items: list[dict[str, Any]] = []
    for assignment in reversed(assignment_repository.list_history()):
        if (
            assignment.status != "released"
            or assignment.release_reason != "shift_handoff"
            or assignment.released_at is None
            or assignment.released_at < cutoff
            or assignment.work_id in seen_work_ids
        ):
            continue
        seen_work_ids.add(assignment.work_id)
        current_item = raw_by_id.get(assignment.work_id)
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
        if disposition not in INCOMPLETE_HANDOFF_DISPOSITIONS:
            continue
        items.append({
            "work_id": assignment.work_id,
            "work_type": _work_type(assignment.work_id),
            "released_at": assignment.released_at,
            "assignment_generation": assignment.generation,
            "current_disposition": disposition,
        })
        if len(items) >= SHIFT_HANDOFF_LIMIT:
            break
    return items


def build_operational_shift_open_reconciliation(
    *,
    operator_name: str,
    receipt_repository: OperationalShiftCloseReceiptRepository,
    assignment_repository: OperationalWorkAssignmentRepository,
    attachment_repository,
    proposal_repository,
    supplier_repository,
    approval_repository,
    quote_case_repository,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _utc(now)
    raw_queue = build_operational_work_queue(
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=current,
    )
    decorated = decorate_operational_work_queue(raw_queue, assignment_repository, now=current)
    critical_uncovered = [
        _safe_work_item(item)
        for item in decorated.get("items", [])
        if item.get("priority_band") == "critical"
        and not (
            item.get("assignment_status") in {"assigned", "acknowledged"}
            and item.get("lease_status") == "active"
        )
    ]
    incomplete_handoffs = _global_incomplete_handoffs(
        assignment_repository=assignment_repository,
        raw_queue=raw_queue,
        decorated_queue=decorated,
        now=current,
    )

    receipts = sorted(
        receipt_repository.list_all(),
        key=lambda item: (item.attested_at, item.receipt_id),
        reverse=True,
    )
    latest = receipts[0] if receipts else None
    attention_codes: list[str] = []
    prior_close: dict[str, Any]
    changes: dict[str, Any]
    if latest is None:
        prior_close = {"status": "missing"}
        changes = {
            "tracking_status": "unavailable",
            "event_count": None,
            "category_counts": {},
            "first_change_at": None,
            "last_change_at": None,
        }
        attention_codes.extend(("no_prior_shift_close_receipt", "change_tracking_unavailable"))
    else:
        receipt_status = evaluate_operational_shift_close_receipt_status(
            latest,
            assignment_repository=assignment_repository,
            attachment_repository=attachment_repository,
            proposal_repository=proposal_repository,
            supplier_repository=supplier_repository,
            approval_repository=approval_repository,
            quote_case_repository=quote_case_repository,
            now=current,
        )
        prior_close = {
            "status": "available",
            "receipt_id": latest.receipt_id,
            "attested_at": latest.attested_at,
            "readiness_generated_at": latest.readiness_generated_at,
            "evidence_version": latest.evidence_version,
            "evidence_counts": {
                "pending_work_count": latest.pending_work_count,
                "critical_pending_count": latest.critical_pending_count,
                "active_assignment_count": latest.active_assignment_count,
                "expired_assignment_count": latest.expired_assignment_count,
                "incomplete_handoff_count": latest.incomplete_handoff_count,
                "critical_uncovered_count": latest.critical_uncovered_count,
            },
            **receipt_status,
        }
        changes = _change_summary(latest.state_event_id, assignment_repository)
        if receipt_status["current_status"] == "stale":
            attention_codes.append("prior_shift_close_receipt_stale")
        if changes["tracking_status"] == "unavailable":
            attention_codes.append("change_tracking_unavailable")
        elif int(changes["event_count"] or 0) > 0:
            attention_codes.append("operational_changes_since_close")
        elif receipt_status["current_status"] == "stale":
            attention_codes.append("time_or_state_change_since_close")

    if incomplete_handoffs:
        attention_codes.append("incomplete_handoffs_require_reconciliation")
    if critical_uncovered:
        attention_codes.append("critical_uncovered_work_requires_coverage")

    return {
        "generated_at": current,
        "scope": "authenticated_incoming_operator",
        "reconciliation_status": "clear" if not attention_codes else "review_required",
        "review_required": bool(attention_codes),
        "attention_codes": attention_codes,
        "prior_shift_close": prior_close,
        "changes_since_close": changes,
        "current_overview": {
            "pending_count": raw_queue.get("pending_count", 0),
            "priority_counts": raw_queue.get("priority_counts", {}),
            "critical_uncovered_count": len(critical_uncovered),
            "incomplete_handoff_count": len(incomplete_handoffs),
        },
        "critical_uncovered": {"count": len(critical_uncovered), "items": critical_uncovered},
        "incomplete_handoffs": {"count": len(incomplete_handoffs), "items": incomplete_handoffs},
        "remediation": {
            "incomplete_handoffs_require_reconciliation": ["work queue", "work get", "work assign"],
            "critical_uncovered_work_requires_coverage": ["work queue", "work get", "work assign"],
            "prior_shift_close_receipt_stale": ["work shift-summary", "work close-readiness"],
            "no_prior_shift_close_receipt": ["work shift-summary", "work close-readiness"],
        },
        "authority": {
            "reconciliation_is_read_only": True,
            "reconciliation_does_not_open_shift": True,
            "prior_receipt_is_audit_evidence_only": True,
            "assignment_is_coordination_only": True,
            "existing_workflow_guards_remain_authoritative": True,
        },
    }
