from __future__ import annotations

from datetime import datetime
from typing import Any

from src.core.attachment_interpretation_review_repository import AttachmentInterpretationReviewRepository
from src.core.extraction_confirmation_repository import ExtractionProposalRepository
from src.core.operational_work_queue import build_operational_work_queue
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import assignment_public_payload
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository


class OperationalWorkItemNotFoundError(ValueError):
    pass

_BLOCKER_REASON_CODES = {
    "baseline_not_apply_ready",
    "supplier_rfq_missing",
    "supplier_rfq_snapshot_stale",
    "supplier_rfq_no_longer_review_applicable",
    "supplier_follow_up_parent_rfq_missing",
    "supplier_follow_up_parent_state_stale",
    "supplier_follow_up_send_evidence_state_conflict",
    "multiple_active_supplier_follow_ups",
    "clarification_required_without_active_follow_up",
    "quote_approval_case_missing",
    "quote_approval_multiple_cases",
    "quote_approval_case_state_stale",
    "quote_sent_while_approval_pending",
}


def _cmd(*args: str, purpose: str, requires: list[str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "purpose": purpose,
        "argv": list(args),
    }
    if requires:
        payload["requires"] = list(requires)
    return payload


def _safe_common(item: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "work_id", "work_type", "resource_type", "resource_id", "route", "status",
        "next_action", "created_at", "age_hours", "priority_band", "priority_score",
        "priority_reasons", "critical_attention_count", "blocker_count", "warning_count",
        "nearest_deadline_kind", "days_until_nearest_deadline",
    )
    return {key: item[key] for key in keys if key in item}


def _attachment_detail(item, repository):
    review = repository.get(item["resource_id"])
    if review is None:
        return {"state_checks": {"resource_present": False}, "recovery_mode": "inspect_state"}, []
    commands = [
        _cmd("attachment-review", "get", review.review_id, purpose="inspect_review"),
        _cmd(
            "attachment-review", "preview", review.review_id,
            "--corrections", "{}",
            purpose="preview_without_corrections",
        ),
    ]
    return {
        "state_checks": {"resource_present": True, "review_status": review.status},
        "recovery_mode": "inspect_then_preview",
    }, commands


def _proposal_detail(item, repository):
    proposal = repository.get(item["resource_id"])
    if proposal is None:
        return {"state_checks": {"resource_present": False}, "recovery_mode": "inspect_state"}, []
    unknown = list(proposal.unknown_fields)
    safety = list(proposal.unknown_safety_fields)
    commands = [
        _cmd("proposal", "get", proposal.proposal_id, purpose="inspect_proposal"),
        _cmd(
            "proposal", "confirm", proposal.proposal_id,
            purpose="confirm_after_review",
            requires=["corrections_json_if_needed"],
        ),
    ]
    return {
        "state_checks": {
            "resource_present": True,
            "extraction_status": proposal.extraction_status,
            "resume_status": proposal.resume_status,
            "unknown_field_count": len(unknown),
            "unknown_safety_field_count": len(safety),
            "unknown_fields": unknown,
            "unknown_safety_fields": safety,
        },
        "recovery_mode": "human_confirmation_required",
    }, commands


def _follow_up_detail(item, repository):
    follow_up = repository.get_follow_up_draft(item["resource_id"])
    if follow_up is None:
        return {"state_checks": {"resource_present": False}, "recovery_mode": "inspect_state"}, []
    parent = repository.get_draft(follow_up.rfq_id)
    siblings = [
        sibling for sibling in repository.list_follow_up_drafts(follow_up.rfq_id)
        if sibling.status in {"draft", "approved", "awaiting_response"}
    ]
    send_evidence = bool(
        repository.list_follow_up_automated_sent_evidence(follow_up.follow_up_id)
        or repository.list_follow_up_manual_sent_evidence(follow_up.follow_up_id)
    )
    blocked = (
        parent is None
        or parent.status != "clarification_required"
        or len(siblings) > 1
        or send_evidence
    )
    commands = [
        _cmd("rfq", "follow-up-get", follow_up.follow_up_id, purpose="inspect_follow_up"),
    ]
    if not blocked and follow_up.status == "draft":
        commands.append(_cmd("rfq", "follow-up-approve", follow_up.follow_up_id, purpose="approve_follow_up"))
    elif not blocked and follow_up.status == "approved":
        commands.append(_cmd("rfq", "follow-up-send", follow_up.follow_up_id, purpose="send_follow_up"))
    return {
        "state_checks": {
            "resource_present": True,
            "follow_up_status": follow_up.status,
            "parent_rfq_present": parent is not None,
            "parent_rfq_status": None if parent is None else parent.status,
            "active_sibling_count": len(siblings),
            "send_evidence_present": send_evidence,
            "clarification_reason_code_count": len(follow_up.rejection_reasons),
        },
        "recovery_mode": "inspect_state" if blocked else "controlled_follow_up_action",
    }, commands


def _clarification_gap_detail(item, repository):
    draft = repository.get_draft(item["resource_id"])
    if draft is None:
        return {"state_checks": {"resource_present": False}, "recovery_mode": "inspect_state"}, []
    active = [
        follow_up for follow_up in repository.list_follow_up_drafts(draft.rfq_id)
        if follow_up.status in {"draft", "approved", "awaiting_response"}
    ]
    workflow = repository.get_workflow(draft.workflow_id)
    commands = [_cmd("rfq", "get", draft.rfq_id, purpose="inspect_rfq")]
    if workflow is not None and draft.status == "clarification_required" and not active:
        commands.append(
            _cmd(
                "workflow", "resume-quote", workflow.workflow_id,
                purpose="regenerate_controlled_follow_up_if_still_required",
            )
        )
    return {
        "state_checks": {
            "resource_present": True,
            "rfq_status": draft.status,
            "workflow_present": workflow is not None,
            "active_follow_up_count": len(active),
        },
        "recovery_mode": "controlled_workflow_resume" if workflow is not None and not active else "inspect_state",
    }, commands


def _approval_detail(item, approval_repository, quote_case_repository):
    approval = approval_repository.get(item["resource_id"])
    if approval is None:
        return {"state_checks": {"resource_present": False}, "recovery_mode": "inspect_state"}, []
    linked = [
        case for case in quote_case_repository.list_all()
        if case.quote_approval is not None and case.quote_approval.approval_id == approval.approval_id
    ]
    sent = any(case.manual_sent_evidence or case.automated_sent_evidence for case in linked)
    state_sync = (
        len(linked) == 1
        and linked[0].quote_approval is not None
        and linked[0].quote_approval.approval_status == approval.approval_status
    )
    blocked = len(linked) != 1 or sent or not state_sync
    commands = [_cmd("approval", "get", approval.approval_id, purpose="inspect_approval")]
    if not blocked:
        commands.extend([
            _cmd("approval", "approve", approval.approval_id, purpose="approve_after_review"),
            _cmd(
                "approval", "reject", approval.approval_id,
                purpose="reject_after_review",
                requires=["rejection_reason"],
            ),
        ])
    return {
        "state_checks": {
            "resource_present": True,
            "approval_status": approval.approval_status,
            "linked_case_count": len(linked),
            "case_state_synced": state_sync,
            "prior_send_evidence_present": sent,
        },
        "recovery_mode": "inspect_state" if blocked else "human_decision_required",
    }, commands


def build_operational_work_item_detail(
    *,
    work_id: str,
    attachment_repository: AttachmentInterpretationReviewRepository,
    proposal_repository: ExtractionProposalRepository,
    supplier_repository: SupplierRFQRepository,
    approval_repository: QuoteApprovalRepository,
    quote_case_repository: QuoteCaseRepository,
    assignment_repository: OperationalWorkAssignmentRepository | None = None,
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
        raise OperationalWorkItemNotFoundError(f"Operational work item not found: {work_id}")

    if item["work_type"] == "attachment_review":
        detail, commands = _attachment_detail(item, attachment_repository)
    elif item["work_type"] == "customer_extraction_confirmation":
        detail, commands = _proposal_detail(item, proposal_repository)
    elif item["work_type"] == "supplier_follow_up":
        detail, commands = _follow_up_detail(item, supplier_repository)
    elif item["work_type"] == "supplier_clarification_gap":
        detail, commands = _clarification_gap_detail(item, supplier_repository)
    elif item["work_type"] == "quote_approval":
        detail, commands = _approval_detail(item, approval_repository, quote_case_repository)
    else:
        detail, commands = ({"state_checks": {}, "recovery_mode": "inspect_state"}, [])

    reason_codes = list(item.get("priority_reasons", []))
    assignment = (
        assignment_public_payload(assignment_repository.get(work_id), item=item)
        if assignment_repository is not None
        else {"assignment_status": "unassigned"}
    )
    return {
        "work_item": _safe_common(item),
        "assignment": assignment,
        "why_waiting": reason_codes,
        "blocking_reasons": [code for code in reason_codes if code in _BLOCKER_REASON_CODES],
        "diagnostics": detail,
        "operator_commands": commands,
        "authority": {
            "detail_is_read_only": True,
            "next_action_is_informational": True,
            "existing_workflow_guards_remain_authoritative": True,
        },
    }
