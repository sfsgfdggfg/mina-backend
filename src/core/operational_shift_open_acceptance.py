from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from src.core.operational_shift_close_receipt_repository import OperationalShiftCloseReceiptRepository
from src.core.operational_shift_open_acceptance_receipt import OperationalShiftOpenAcceptanceReceipt
from src.core.operational_shift_open_acceptance_receipt_repository import OperationalShiftOpenAcceptanceReceiptRepository
from src.core.operational_shift_open_reconciliation import build_operational_shift_open_reconciliation
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.sqlite_repositories import atomic_repository_transaction

SHIFT_OPEN_ACCEPTANCE_LIMIT = 20


class OperationalShiftOpenAcceptanceBlockedError(RuntimeError):
    pass


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def _stable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(key): _stable(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def _acceptance_state(
    *,
    operator_name: str,
    receipt_repository: OperationalShiftCloseReceiptRepository,
    assignment_repository: OperationalWorkAssignmentRepository,
    attachment_repository,
    proposal_repository,
    supplier_repository,
    approval_repository,
    quote_case_repository,
    now: datetime,
) -> tuple[dict[str, Any], str]:
    reconciliation = build_operational_shift_open_reconciliation(
        operator_name=operator_name,
        receipt_repository=receipt_repository,
        assignment_repository=assignment_repository,
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=now,
    )
    projection = {
        "operator_scope": operator_name,
        "reconciliation_status": reconciliation.get("reconciliation_status"),
        "review_required": reconciliation.get("review_required"),
        "attention_codes": reconciliation.get("attention_codes", []),
        "prior_shift_close": reconciliation.get("prior_shift_close", {}),
        "changes_since_close": reconciliation.get("changes_since_close", {}),
        "current_overview": reconciliation.get("current_overview", {}),
        "critical_uncovered": reconciliation.get("critical_uncovered", {}),
        "incomplete_handoffs": reconciliation.get("incomplete_handoffs", {}),
    }
    encoded = json.dumps(
        _stable(projection),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return reconciliation, hashlib.sha256(encoded).hexdigest()


def _receipt_id(operator_name: str, acceptance_state_sha256: str) -> str:
    encoded = f"shift_open_acceptance_v1\n{operator_name}\n{acceptance_state_sha256}".encode("utf-8")
    return "shift-open-" + hashlib.sha256(encoded).hexdigest()[:32]


def _public_receipt(
    receipt: OperationalShiftOpenAcceptanceReceipt,
    *,
    current_state_sha256: str,
    current_clear: bool,
) -> dict[str, Any]:
    current = current_clear and receipt.acceptance_state_sha256 == current_state_sha256
    return {
        "receipt_id": receipt.receipt_id,
        "accepted_at": receipt.accepted_at,
        "reconciliation_generated_at": receipt.reconciliation_generated_at,
        "source_close_receipt_id": receipt.source_close_receipt_id,
        "evidence_version": receipt.evidence_version,
        "evidence_counts": {
            "pending_work_count": receipt.pending_work_count,
            "critical_pending_count": receipt.critical_pending_count,
            "incomplete_handoff_count": receipt.incomplete_handoff_count,
            "critical_uncovered_count": receipt.critical_uncovered_count,
        },
        "current_status": "current" if current else "stale",
        "current_for_open_state": current,
        "authority": {
            "receipt_is_audit_evidence_only": True,
            "receipt_does_not_open_or_authorize_shift": True,
            "receipt_does_not_authorize_workflow_actions": True,
            "fresh_reconciliation_is_always_required": True,
        },
    }


def evaluate_operational_shift_open_acceptance_status(
    receipt: OperationalShiftOpenAcceptanceReceipt,
    *,
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
    reconciliation, current_state_sha256 = _acceptance_state(
        operator_name=receipt.accepted_by,
        receipt_repository=receipt_repository,
        assignment_repository=assignment_repository,
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=timestamp,
    )
    current_clear = (
        reconciliation.get("reconciliation_status") == "clear"
        and reconciliation.get("review_required") is False
    )
    current = current_clear and receipt.acceptance_state_sha256 == current_state_sha256
    return {
        "current_status": "current" if current else "stale",
        "current_for_open_state": current,
        "current_reconciliation_clear": current_clear,
    }


def attest_operational_shift_open_acceptance(
    *,
    operator_name: str,
    acceptance_repository: OperationalShiftOpenAcceptanceReceiptRepository,
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
        acceptance_repository, receipt_repository, assignment_repository, attachment_repository,
        proposal_repository, supplier_repository, approval_repository, quote_case_repository,
    )
    with atomic_repository_transaction(*repositories):
        reconciliation, acceptance_state_sha256 = _acceptance_state(
            operator_name=operator_name,
            receipt_repository=receipt_repository,
            assignment_repository=assignment_repository,
            attachment_repository=attachment_repository,
            proposal_repository=proposal_repository,
            supplier_repository=supplier_repository,
            approval_repository=approval_repository,
            quote_case_repository=quote_case_repository,
            now=timestamp,
        )
        if reconciliation.get("reconciliation_status") != "clear" or reconciliation.get("review_required") is not False:
            raise OperationalShiftOpenAcceptanceBlockedError(
                "Shift open acceptance requires current reconciliation_status=clear."
            )
        prior = reconciliation.get("prior_shift_close", {})
        source_close_receipt_id = prior.get("receipt_id")
        if prior.get("status") != "available" or not isinstance(source_close_receipt_id, str):
            raise OperationalShiftOpenAcceptanceBlockedError(
                "Shift open acceptance requires a current prior shift-close receipt."
            )
        receipt_id = _receipt_id(operator_name, acceptance_state_sha256)
        existing = acceptance_repository.get(receipt_id)
        if existing is not None:
            return _public_receipt(
                existing,
                current_state_sha256=acceptance_state_sha256,
                current_clear=True,
            )
        overview = reconciliation.get("current_overview", {})
        receipt = OperationalShiftOpenAcceptanceReceipt(
            receipt_id=receipt_id,
            accepted_by=operator_name,
            accepted_at=timestamp,
            reconciliation_generated_at=reconciliation["generated_at"],
            source_close_receipt_id=source_close_receipt_id,
            pending_work_count=int(overview.get("pending_count", 0)),
            critical_pending_count=int(overview.get("priority_counts", {}).get("critical", 0)),
            incomplete_handoff_count=int(overview.get("incomplete_handoff_count", 0)),
            critical_uncovered_count=int(overview.get("critical_uncovered_count", 0)),
            acceptance_state_sha256=acceptance_state_sha256,
        )
        stored = acceptance_repository.save_if_absent(receipt)
        return _public_receipt(
            stored,
            current_state_sha256=acceptance_state_sha256,
            current_clear=True,
        )


def list_operational_shift_open_acceptances(
    *,
    operator_name: str,
    acceptance_repository: OperationalShiftOpenAcceptanceReceiptRepository,
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
    reconciliation, acceptance_state_sha256 = _acceptance_state(
        operator_name=operator_name,
        receipt_repository=receipt_repository,
        assignment_repository=assignment_repository,
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=timestamp,
    )
    current_clear = reconciliation.get("reconciliation_status") == "clear" and reconciliation.get("review_required") is False
    receipts = sorted(
        (item for item in acceptance_repository.list_all() if item.accepted_by == operator_name),
        key=lambda item: (item.accepted_at, item.receipt_id),
        reverse=True,
    )[:SHIFT_OPEN_ACCEPTANCE_LIMIT]
    items = [
        _public_receipt(
            receipt,
            current_state_sha256=acceptance_state_sha256,
            current_clear=current_clear,
        )
        for receipt in receipts
    ]
    return {
        "scope": "authenticated_incoming_operator",
        "count": len(items),
        "current_count": sum(1 for item in items if item["current_for_open_state"]),
        "items": items,
        "authority": {
            "acceptances_are_audit_evidence_only": True,
            "fresh_reconciliation_is_always_required": True,
            "existing_assignment_and_workflow_guards_remain_authoritative": True,
        },
    }
