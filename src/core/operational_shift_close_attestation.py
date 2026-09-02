from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from src.core.operational_shift_close_readiness import build_operational_shift_close_readiness
from src.core.operational_shift_close_receipt import OperationalShiftCloseReceipt
from src.core.operational_shift_close_receipt_repository import OperationalShiftCloseReceiptRepository
from src.core.operational_shift_summary import build_operational_shift_summary
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import decorate_operational_work_queue
from src.core.operational_work_queue import build_operational_work_queue
from src.core.sqlite_repositories import atomic_repository_transaction

SHIFT_CLOSE_RECEIPT_LIMIT = 20


class OperationalShiftCloseAttestationBlockedError(RuntimeError):
    pass


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def _stable_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def _stable_work_item(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "work_id", "work_type", "resource_type", "route", "status", "next_action",
        "priority_band", "priority_score", "critical_attention_count", "blocker_count",
        "warning_count", "nearest_deadline_kind", "days_until_nearest_deadline",
        "assignment_status", "assignment_generation", "assigned_to", "lease_status",
        "lease_expires_at", "takeover_available", "stale_assignment_present",
    )
    return {key: _stable_value(item[key]) for key in keys if key in item}


def _state_event_id(assignment_repository: OperationalWorkAssignmentRepository) -> int | None:
    store = getattr(assignment_repository, "store", None)
    if store is None:
        return None
    return store.latest_event_id(
        exclude_entity_type="operational_shift_close_receipt"
    )


def _close_state(
    *,
    operator_name: str,
    assignment_repository: OperationalWorkAssignmentRepository,
    attachment_repository,
    proposal_repository,
    supplier_repository,
    approval_repository,
    quote_case_repository,
    now: datetime,
) -> tuple[dict[str, Any], str, dict[str, Any], int | None]:
    args = {
        "assignment_repository": assignment_repository,
        "attachment_repository": attachment_repository,
        "proposal_repository": proposal_repository,
        "supplier_repository": supplier_repository,
        "approval_repository": approval_repository,
        "quote_case_repository": quote_case_repository,
    }
    readiness = build_operational_shift_close_readiness(
        operator_name=operator_name,
        now=now,
        **args,
    )
    raw_queue = build_operational_work_queue(
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=now,
    )
    decorated = decorate_operational_work_queue(raw_queue, assignment_repository, now=now)
    summary = build_operational_shift_summary(operator_name=operator_name, now=now, **args)
    state_event_id = _state_event_id(assignment_repository)
    projection = {
        "operator_scope": operator_name,
        "state_event_id": state_event_id,
        "queue": sorted(
            (_stable_work_item(item) for item in decorated.get("items", [])),
            key=lambda item: str(item.get("work_id", "")),
        ),
        "recent_handoffs": sorted(
            (
                {
                    "work_id": item.get("work_id"),
                    "assignment_generation": item.get("assignment_generation"),
                    "released_at": _stable_value(item.get("released_at")),
                    "current_disposition": item.get("current_disposition"),
                }
                for item in summary["recent_handoffs"]["items"]
            ),
            key=lambda item: (
                str(item.get("released_at", "")),
                str(item.get("work_id", "")),
            ),
        ),
        "readiness": readiness.get("readiness"),
        "blocker_codes": list(readiness.get("blocker_codes", [])),
        "warning_codes": list(readiness.get("warning_codes", [])),
        "checks": readiness.get("checks", {}),
    }
    encoded = json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return readiness, hashlib.sha256(encoded).hexdigest(), raw_queue, state_event_id


def _receipt_id(operator_name: str, close_state_sha256: str) -> str:
    encoded = f"shift_close_attestation_v1\n{operator_name}\n{close_state_sha256}".encode("utf-8")
    return "shift-close-" + hashlib.sha256(encoded).hexdigest()[:32]


def _public_receipt(
    receipt: OperationalShiftCloseReceipt,
    *,
    current_state_sha256: str,
    current_ready: bool,
) -> dict[str, Any]:
    current = current_ready and receipt.close_state_sha256 == current_state_sha256
    return {
        "receipt_id": receipt.receipt_id,
        "attested_at": receipt.attested_at,
        "readiness_generated_at": receipt.readiness_generated_at,
        "evidence_version": receipt.evidence_version,
        "evidence_counts": {
            "pending_work_count": receipt.pending_work_count,
            "critical_pending_count": receipt.critical_pending_count,
            "active_assignment_count": receipt.active_assignment_count,
            "expired_assignment_count": receipt.expired_assignment_count,
            "incomplete_handoff_count": receipt.incomplete_handoff_count,
            "critical_uncovered_count": receipt.critical_uncovered_count,
        },
        "current_status": "current" if current else "stale",
        "current_for_close_state": current,
        "authority": {
            "receipt_is_audit_evidence_only": True,
            "receipt_does_not_authorize_workflow_actions": True,
            "receipt_does_not_keep_readiness_current": True,
        },
    }


def attest_operational_shift_close(
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
    timestamp = _utc(now)
    repositories = (
        receipt_repository,
        assignment_repository,
        attachment_repository,
        proposal_repository,
        supplier_repository,
        approval_repository,
        quote_case_repository,
    )
    with atomic_repository_transaction(*repositories):
        readiness, close_state_sha256, raw_queue, state_event_id = _close_state(
            operator_name=operator_name,
            assignment_repository=assignment_repository,
            attachment_repository=attachment_repository,
            proposal_repository=proposal_repository,
            supplier_repository=supplier_repository,
            approval_repository=approval_repository,
            quote_case_repository=quote_case_repository,
            now=timestamp,
        )
        if not readiness.get("ready_to_close"):
            raise OperationalShiftCloseAttestationBlockedError(
                "Shift close attestation requires current ready_to_close=true."
            )
        receipt_id = _receipt_id(operator_name, close_state_sha256)
        existing = receipt_repository.get(receipt_id)
        if existing is not None:
            return _public_receipt(
                existing,
                current_state_sha256=close_state_sha256,
                current_ready=True,
            )
        receipt = OperationalShiftCloseReceipt(
            receipt_id=receipt_id,
            attested_by=operator_name,
            attested_at=timestamp,
            readiness_generated_at=readiness["generated_at"],
            pending_work_count=int(raw_queue.get("pending_count", 0)),
            critical_pending_count=int(raw_queue.get("priority_counts", {}).get("critical", 0)),
            active_assignment_count=readiness["active_work"]["count"],
            expired_assignment_count=readiness["expired_work"]["count"],
            incomplete_handoff_count=readiness["incomplete_handoffs"]["count"],
            critical_uncovered_count=readiness["critical_unassigned"]["count"],
            close_state_sha256=close_state_sha256,
            state_event_id=state_event_id,
        )
        stored = receipt_repository.save_if_absent(receipt)
        return _public_receipt(
            stored,
            current_state_sha256=close_state_sha256,
            current_ready=True,
        )


def list_operational_shift_close_receipts(
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
    timestamp = _utc(now)
    readiness, close_state_sha256, _, _ = _close_state(
        operator_name=operator_name,
        assignment_repository=assignment_repository,
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=timestamp,
    )
    receipts = sorted(
        (item for item in receipt_repository.list_all() if item.attested_by == operator_name),
        key=lambda item: (item.attested_at, item.receipt_id),
        reverse=True,
    )[:SHIFT_CLOSE_RECEIPT_LIMIT]
    items = [
        _public_receipt(
            receipt,
            current_state_sha256=close_state_sha256,
            current_ready=bool(readiness.get("ready_to_close")),
        )
        for receipt in receipts
    ]
    return {
        "scope": "authenticated_operator",
        "count": len(items),
        "current_count": sum(1 for item in items if item["current_for_close_state"]),
        "items": items,
        "authority": {
            "receipts_are_audit_evidence_only": True,
            "current_readiness_must_be_rechecked": True,
            "existing_workflow_guards_remain_authoritative": True,
        },
    }
