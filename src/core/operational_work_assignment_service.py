from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from src.core.attachment_interpretation_review_repository import AttachmentInterpretationReviewRepository
from src.core.extraction_confirmation_repository import ExtractionProposalRepository
from src.core.operational_work_assignment import OperationalWorkAssignment
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.operational_work_queue import build_operational_work_queue
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_rfq_repository import SupplierRFQRepository


class OperationalWorkAssignmentConflictError(RuntimeError):
    pass


class OperationalWorkAssignmentTransitionError(RuntimeError):
    pass


class OperationalWorkAssignmentNotFoundError(ValueError):
    pass


def work_state_fingerprint(item: dict[str, Any]) -> str:
    created = item.get("created_at")
    payload = {
        "work_id": item.get("work_id"),
        "work_type": item.get("work_type"),
        "resource_type": item.get("resource_type"),
        "status": item.get("status"),
        "next_action": item.get("next_action"),
        "created_at": created.isoformat() if isinstance(created, datetime) else created,
        "critical_attention_count": item.get("critical_attention_count", 0),
        "blocker_count": item.get("blocker_count", 0),
        "warning_count": item.get("warning_count", 0),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _current_item(
    *,
    work_id: str,
    attachment_repository: AttachmentInterpretationReviewRepository,
    proposal_repository: ExtractionProposalRepository,
    supplier_repository: SupplierRFQRepository,
    approval_repository: QuoteApprovalRepository,
    quote_case_repository: QuoteCaseRepository,
    now: datetime | None = None,
) -> dict[str, Any]:
    queue = build_operational_work_queue(
        attachment_repository=attachment_repository,
        proposal_repository=proposal_repository,
        supplier_repository=supplier_repository,
        approval_repository=approval_repository,
        quote_case_repository=quote_case_repository,
        now=now,
    )
    item = next((entry for entry in queue["items"] if entry["work_id"] == work_id), None)
    if item is None:
        raise OperationalWorkAssignmentNotFoundError(f"Operational work item not found: {work_id}")
    return item


def _now(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _repo_args(assignment_repository, attachment_repository, proposal_repository, supplier_repository, approval_repository, quote_case_repository):
    return (
        assignment_repository,
        attachment_repository,
        proposal_repository,
        supplier_repository,
        approval_repository,
        quote_case_repository,
    )


def assign_operational_work_to_me(
    *,
    work_id: str,
    operator_name: str,
    assignment_repository: OperationalWorkAssignmentRepository,
    attachment_repository: AttachmentInterpretationReviewRepository,
    proposal_repository: ExtractionProposalRepository,
    supplier_repository: SupplierRFQRepository,
    approval_repository: QuoteApprovalRepository,
    quote_case_repository: QuoteCaseRepository,
    now: datetime | None = None,
) -> OperationalWorkAssignment:
    timestamp = _now(now)
    with atomic_repository_transaction(*_repo_args(assignment_repository, attachment_repository, proposal_repository, supplier_repository, approval_repository, quote_case_repository)):
        item = _current_item(
            work_id=work_id,
            attachment_repository=attachment_repository,
            proposal_repository=proposal_repository,
            supplier_repository=supplier_repository,
            approval_repository=approval_repository,
            quote_case_repository=quote_case_repository,
            now=timestamp,
        )
        fingerprint = work_state_fingerprint(item)
        current = assignment_repository.get(work_id)
        if current is not None and current.status != "released" and getattr(current, "work_state_sha256", None) == fingerprint:
            if current.assigned_to == operator_name:
                return current
            raise OperationalWorkAssignmentConflictError("Operational work item is already assigned to another operator.")
        generation = 1 if current is None else current.generation + 1
        assignment = OperationalWorkAssignment(
            work_id=work_id,
            assigned_to=operator_name,
            assigned_at=timestamp,
            generation=generation,
            work_state_sha256=fingerprint,
        )
        return assignment_repository.save(assignment)


def acknowledge_operational_work(
    *,
    work_id: str,
    operator_name: str,
    assignment_repository: OperationalWorkAssignmentRepository,
    attachment_repository: AttachmentInterpretationReviewRepository,
    proposal_repository: ExtractionProposalRepository,
    supplier_repository: SupplierRFQRepository,
    approval_repository: QuoteApprovalRepository,
    quote_case_repository: QuoteCaseRepository,
    now: datetime | None = None,
) -> OperationalWorkAssignment:
    timestamp = _now(now)
    with atomic_repository_transaction(*_repo_args(assignment_repository, attachment_repository, proposal_repository, supplier_repository, approval_repository, quote_case_repository)):
        item = _current_item(
            work_id=work_id,
            attachment_repository=attachment_repository,
            proposal_repository=proposal_repository,
            supplier_repository=supplier_repository,
            approval_repository=approval_repository,
            quote_case_repository=quote_case_repository,
            now=timestamp,
        )
        current = assignment_repository.get(work_id)
        if current is None or current.status == "released" or getattr(current, "work_state_sha256", None) != work_state_fingerprint(item):
            raise OperationalWorkAssignmentTransitionError("Operational work item must be assigned before acknowledgement.")
        if current.assigned_to != operator_name:
            raise OperationalWorkAssignmentConflictError("Only the assigned operator may acknowledge this work item.")
        if current.status == "acknowledged":
            return current
        updated = current.model_copy(update={"status": "acknowledged", "acknowledged_at": timestamp})
        return assignment_repository.save(updated)


def release_operational_work(
    *,
    work_id: str,
    operator_name: str,
    assignment_repository: OperationalWorkAssignmentRepository,
    now: datetime | None = None,
) -> OperationalWorkAssignment:
    timestamp = _now(now)
    with atomic_repository_transaction(assignment_repository):
        current = assignment_repository.get(work_id)
        if current is None or current.status == "released":
            raise OperationalWorkAssignmentTransitionError("Operational work item has no active assignment.")
        if current.assigned_to != operator_name:
            raise OperationalWorkAssignmentConflictError("Only the assigned operator may release this work item.")
        updated = current.model_copy(
            update={"status": "released", "released_at": timestamp, "released_by": operator_name}
        )
        return assignment_repository.save(updated)


def assignment_public_payload(assignment: OperationalWorkAssignment | None, *, item: dict[str, Any] | None = None) -> dict[str, Any]:
    if assignment is None or assignment.status == "released":
        return {"assignment_status": "unassigned"}
    if item is not None and getattr(assignment, "work_state_sha256", None) != work_state_fingerprint(item):
        return {"assignment_status": "unassigned", "stale_assignment_present": True}
    payload: dict[str, Any] = {
        "assignment_status": assignment.status,
        "assigned_to": assignment.assigned_to,
        "assigned_at": assignment.assigned_at,
        "assignment_generation": assignment.generation,
    }
    if assignment.acknowledged_at is not None:
        payload["acknowledged_at"] = assignment.acknowledged_at
    return payload


def decorate_operational_work_queue(
    queue: dict[str, Any],
    assignment_repository: OperationalWorkAssignmentRepository,
) -> dict[str, Any]:
    decorated = dict(queue)
    items = []
    assigned_count = 0
    acknowledged_count = 0
    for source in queue.get("items", []):
        item = dict(source)
        assignment = assignment_repository.get(item["work_id"])
        metadata = assignment_public_payload(assignment, item=item)
        item.update(metadata)
        if metadata["assignment_status"] in {"assigned", "acknowledged"}:
            assigned_count += 1
        if metadata["assignment_status"] == "acknowledged":
            acknowledged_count += 1
        items.append(item)
    decorated["items"] = items
    decorated["assignment_counts"] = {
        "assigned_or_acknowledged": assigned_count,
        "acknowledged": acknowledged_count,
        "unassigned": max(0, len(items) - assigned_count),
    }
    return decorated
