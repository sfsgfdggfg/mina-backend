from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from src.core.attachment_interpretation_review_repository import (
    AttachmentInterpretationReviewRepository,
)
from src.core.attachment_review_queue import build_attachment_review_queue
from src.core.extraction_confirmation import ShipmentExtractionProposal
from src.core.extraction_confirmation_repository import ExtractionProposalRepository
from src.core.operational_priority import (
    PRIORITY_RANK,
    age_score,
    aware_utc,
    deadline_score,
    priority_band,
    strict_iso_date,
)
from src.core.quote_approval import QuoteApproval
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.quote_approval_repository import QuoteApprovalRepository
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQFollowUpDraft
from src.core.supplier_rfq_repository import SupplierRFQRepository

_HUMAN_ACTION_BASE_SCORE = 20
_ACTIVE_FOLLOW_UP_STATUSES = {"draft", "approved", "awaiting_response"}
_HUMAN_FOLLOW_UP_STATUSES = {"draft", "approved"}


def _age_hours(created_at: datetime | None, *, now: datetime) -> int | None:
    if created_at is None:
        return None
    return max(0, int((aware_utc(now) - aware_utc(created_at)).total_seconds() // 3600))


def _add_age(score: int, reasons: list[str], age_hours: int | None) -> int:
    if age_hours is None:
        reasons.append("work_age_unavailable")
        return score
    points, reason = age_score(age_hours)
    if points:
        score += points
    if reason:
        reasons.append(reason)
    return score


def _date_pairs(*pairs: tuple[str, Any]) -> list[tuple[str, date]]:
    result: list[tuple[str, date]] = []
    for kind, raw in pairs:
        parsed = strict_iso_date(raw)
        if parsed is not None:
            result.append((kind, parsed))
    return result


def _add_deadlines(
    score: int,
    reasons: list[str],
    pairs: list[tuple[str, date]],
    *,
    now: datetime,
) -> tuple[int, str | None, int | None]:
    nearest_kind = None
    nearest_days = None
    for kind, deadline in pairs:
        days = (deadline - aware_utc(now).date()).days
        points, reason = deadline_score(days, kind=kind)
        if points:
            score += points
            reasons.append(reason)
        if nearest_days is None or days < nearest_days:
            nearest_kind, nearest_days = kind, days
    return score, nearest_kind, nearest_days


def _final_item(
    *,
    work_type: str,
    resource_type: str,
    resource_id: str,
    route: str,
    status: str,
    next_action: str,
    created_at: datetime | None,
    age_hours: int | None,
    score: int,
    reasons: list[str],
    critical_attention_count: int = 0,
    blocker_count: int = 0,
    warning_count: int = 0,
    nearest_deadline_kind: str | None = None,
    days_until_nearest_deadline: int | None = None,
) -> dict[str, Any]:
    bounded = min(100, max(0, score))
    item = {
        "work_id": f"{work_type}:{resource_id}",
        "work_type": work_type,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "route": route,
        "status": status,
        "next_action": next_action,
        "created_at": created_at,
        "age_hours": age_hours,
        "priority_band": priority_band(bounded),
        "priority_score": bounded,
        "priority_reasons": sorted(set(reasons)),
        "critical_attention_count": critical_attention_count,
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "nearest_deadline_kind": nearest_deadline_kind,
        "days_until_nearest_deadline": days_until_nearest_deadline,
    }
    return {key: value for key, value in item.items() if value is not None}


def _attachment_items(
    *,
    attachment_repository: AttachmentInterpretationReviewRepository,
    supplier_repository: SupplierRFQRepository,
    now: datetime,
) -> list[dict[str, Any]]:
    queue = build_attachment_review_queue(
        repository=attachment_repository,
        supplier_repository=supplier_repository,
        now=now,
    )
    items = []
    for source in queue["items"]:
        score = min(100, source["priority_score"] + 10)
        reasons = [*source["priority_reasons"], "human_action_pending"]
        items.append(
            _final_item(
                work_type="attachment_review",
                resource_type="attachment_review",
                resource_id=source["review_id"],
                route=source["route"],
                status=source["status"],
                next_action="inspect_attachment_review",
                created_at=source.get("created_at"),
                age_hours=source.get("age_hours"),
                score=score,
                reasons=reasons,
                critical_attention_count=source["critical_attention_count"],
                blocker_count=source["blocker_count"],
                warning_count=source["warning_count"],
                nearest_deadline_kind=source.get("nearest_deadline_kind"),
                days_until_nearest_deadline=source.get("days_until_nearest_deadline"),
            )
        )
    return items


def _proposal_item(proposal: ShipmentExtractionProposal, *, now: datetime) -> dict[str, Any]:
    created_at = proposal.inbound_mail.received_at
    age_hours = _age_hours(created_at, now=now)
    score = _HUMAN_ACTION_BASE_SCORE
    reasons = ["customer_extraction_confirmation_pending"]
    score = _add_age(score, reasons, age_hours)

    safety_unknown = len(proposal.unknown_safety_fields)
    unknown_total = len(proposal.unknown_fields)
    non_safety_unknown = max(0, unknown_total - safety_unknown)
    if safety_unknown:
        score += min(45, safety_unknown * 15)
        reasons.append("customer_safety_fields_unknown")
    if non_safety_unknown:
        score += min(12, non_safety_unknown * 2)
        reasons.append("customer_fields_unknown")

    shipment = proposal.proposed_shipment
    score, nearest_kind, nearest_days = _add_deadlines(
        score,
        reasons,
        _date_pairs(
            ("required_delivery", shipment.required_delivery_date),
            ("cargo_ready", shipment.cargo_ready_date),
        ),
        now=now,
    )
    return _final_item(
        work_type="customer_extraction_confirmation",
        resource_type="extraction_proposal",
        resource_id=proposal.proposal_id,
        route="customer",
        status=proposal.extraction_status,
        next_action="confirm_extraction",
        created_at=created_at,
        age_hours=age_hours,
        score=score,
        reasons=reasons,
        critical_attention_count=safety_unknown,
        warning_count=non_safety_unknown,
        nearest_deadline_kind=nearest_kind,
        days_until_nearest_deadline=nearest_days,
    )


def _follow_up_dates(
    follow_up: SupplierRFQFollowUpDraft,
    *,
    supplier_repository: SupplierRFQRepository,
) -> list[tuple[str, date]]:
    workflow = supplier_repository.get_workflow(follow_up.workflow_id)
    if workflow is None:
        return []
    shipment = workflow.shipment
    return _date_pairs(
        ("required_delivery", shipment.required_delivery_date),
        ("cargo_ready", shipment.cargo_ready_date),
    )


def _follow_up_item(
    follow_up: SupplierRFQFollowUpDraft,
    *,
    supplier_repository: SupplierRFQRepository,
    active_sibling_count: int,
    now: datetime,
) -> dict[str, Any]:
    age_hours = _age_hours(follow_up.created_at, now=now)
    score = _HUMAN_ACTION_BASE_SCORE
    reasons = ["supplier_follow_up_human_action_pending"]
    score = _add_age(score, reasons, age_hours)
    blocker_count = 0
    warning_count = 0

    parent = supplier_repository.get_draft(follow_up.rfq_id)
    if parent is None:
        score += 60
        blocker_count += 1
        reasons.append("supplier_follow_up_parent_rfq_missing")
    elif parent.status != "clarification_required":
        score += 45
        blocker_count += 1
        reasons.append("supplier_follow_up_parent_state_stale")

    if follow_up.status == "approved":
        score += 10
        reasons.append("supplier_follow_up_approved_ready_to_send")
        next_action = "send_supplier_follow_up"
    else:
        next_action = "approve_supplier_follow_up"

    sent_evidence_count = len(
        supplier_repository.list_follow_up_automated_sent_evidence(follow_up.follow_up_id)
    ) + len(
        supplier_repository.list_follow_up_manual_sent_evidence(follow_up.follow_up_id)
    )
    if sent_evidence_count:
        score += 60
        blocker_count += 1
        reasons.append("supplier_follow_up_send_evidence_state_conflict")
    if active_sibling_count > 1:
        score += 50
        blocker_count += 1
        reasons.append("multiple_active_supplier_follow_ups")
    if blocker_count:
        next_action = "inspect_supplier_follow_up"

    if follow_up.rejection_reasons:
        warning_count += len(follow_up.rejection_reasons)
        score += min(15, len(follow_up.rejection_reasons) * 5)
        reasons.append("supplier_clarification_reasons_present")

    workflow = supplier_repository.get_workflow(follow_up.workflow_id)
    if workflow is None:
        warning_count += 1
        score += 10
        reasons.append("supplier_follow_up_workflow_missing")

    score, nearest_kind, nearest_days = _add_deadlines(
        score,
        reasons,
        _follow_up_dates(follow_up, supplier_repository=supplier_repository),
        now=now,
    )
    return _final_item(
        work_type="supplier_follow_up",
        resource_type="supplier_rfq_follow_up",
        resource_id=follow_up.follow_up_id,
        route="supplier",
        status=follow_up.status,
        next_action=next_action,
        created_at=follow_up.created_at,
        age_hours=age_hours,
        score=score,
        reasons=reasons,
        blocker_count=blocker_count,
        warning_count=warning_count,
        nearest_deadline_kind=nearest_kind,
        days_until_nearest_deadline=nearest_days,
    )


def _rfq_dates(
    draft: SupplierRFQDraft,
    *,
    supplier_repository: SupplierRFQRepository,
) -> list[tuple[str, date]]:
    workflow = supplier_repository.get_workflow(draft.workflow_id)
    if workflow is None:
        return []
    shipment = workflow.shipment
    return _date_pairs(
        ("required_delivery", shipment.required_delivery_date),
        ("cargo_ready", shipment.cargo_ready_date),
    )


def _clarification_gap_item(
    draft: SupplierRFQDraft,
    *,
    supplier_repository: SupplierRFQRepository,
    now: datetime,
) -> dict[str, Any]:
    created_at = draft.responded_at or draft.created_at
    age_hours = _age_hours(created_at, now=now)
    score = _HUMAN_ACTION_BASE_SCORE + 60
    reasons = ["clarification_required_without_active_follow_up"]
    score = _add_age(score, reasons, age_hours)
    score, nearest_kind, nearest_days = _add_deadlines(
        score,
        reasons,
        _rfq_dates(draft, supplier_repository=supplier_repository),
        now=now,
    )
    return _final_item(
        work_type="supplier_clarification_gap",
        resource_type="supplier_rfq",
        resource_id=draft.rfq_id,
        route="supplier",
        status=draft.status,
        next_action="inspect_supplier_clarification",
        created_at=created_at,
        age_hours=age_hours,
        score=score,
        reasons=reasons,
        blocker_count=1,
        nearest_deadline_kind=nearest_kind,
        days_until_nearest_deadline=nearest_days,
    )


def _quote_approval_item(
    approval: QuoteApproval,
    *,
    linked_cases: list[QuoteCase],
    now: datetime,
) -> dict[str, Any]:
    age_hours = _age_hours(approval.created_at, now=now)
    score = _HUMAN_ACTION_BASE_SCORE
    reasons = ["quote_approval_decision_pending"]
    score = _add_age(score, reasons, age_hours)
    blocker_count = 0
    warning_count = 0
    next_action = "decide_quote_approval"
    if not linked_cases:
        score += 55
        blocker_count += 1
        reasons.append("quote_approval_case_missing")
    elif len(linked_cases) > 1:
        score += 55
        blocker_count += 1
        reasons.append("quote_approval_multiple_cases")
    else:
        case = linked_cases[0]
        case_approval = case.quote_approval
        if case_approval is None or case_approval.approval_status != approval.approval_status:
            score += 45
            blocker_count += 1
            reasons.append("quote_approval_case_state_stale")
        if case.manual_sent_evidence or case.automated_sent_evidence:
            score += 60
            blocker_count += 1
            reasons.append("quote_sent_while_approval_pending")
    if blocker_count:
        next_action = "inspect_quote_approval_state"

    snapshot = approval.quote_snapshot
    score, nearest_kind, nearest_days = _add_deadlines(
        score,
        reasons,
        _date_pairs(
            ("quote_validity", snapshot.supplier_validity_date),
            ("vehicle_available", snapshot.supplier_vehicle_available_date),
        ),
        now=now,
    )
    return _final_item(
        work_type="quote_approval",
        resource_type="quote_approval",
        resource_id=approval.approval_id,
        route="commercial",
        status=approval.approval_status,
        next_action=next_action,
        created_at=approval.created_at,
        age_hours=age_hours,
        score=score,
        reasons=reasons,
        blocker_count=blocker_count,
        warning_count=warning_count,
        nearest_deadline_kind=nearest_kind,
        days_until_nearest_deadline=nearest_days,
    )


def build_operational_work_queue(
    *,
    attachment_repository: AttachmentInterpretationReviewRepository,
    proposal_repository: ExtractionProposalRepository,
    supplier_repository: SupplierRFQRepository,
    approval_repository: QuoteApprovalRepository,
    quote_case_repository: QuoteCaseRepository,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = aware_utc(now or datetime.now(timezone.utc))
    items: list[dict[str, Any]] = []
    items.extend(
        _attachment_items(
            attachment_repository=attachment_repository,
            supplier_repository=supplier_repository,
            now=current,
        )
    )
    items.extend(
        _proposal_item(proposal, now=current)
        for proposal in proposal_repository.list_all()
        if proposal.extraction_status == "proposed"
    )

    follow_ups = supplier_repository.list_follow_up_drafts()
    active_follow_up_counts: dict[str, int] = {}
    for follow_up in follow_ups:
        if follow_up.status in _ACTIVE_FOLLOW_UP_STATUSES:
            active_follow_up_counts[follow_up.rfq_id] = (
                active_follow_up_counts.get(follow_up.rfq_id, 0) + 1
            )
    items.extend(
        _follow_up_item(
            follow_up,
            supplier_repository=supplier_repository,
            active_sibling_count=active_follow_up_counts.get(follow_up.rfq_id, 0),
            now=current,
        )
        for follow_up in follow_ups
        if follow_up.status in _HUMAN_FOLLOW_UP_STATUSES
    )
    active_follow_up_rfq_ids = {
        follow_up.rfq_id
        for follow_up in follow_ups
        if follow_up.status in _ACTIVE_FOLLOW_UP_STATUSES
    }
    items.extend(
        _clarification_gap_item(
            draft,
            supplier_repository=supplier_repository,
            now=current,
        )
        for draft in supplier_repository.list_drafts()
        if draft.status == "clarification_required"
        and draft.rfq_id not in active_follow_up_rfq_ids
    )
    quote_cases = quote_case_repository.list_all()
    approval_cases: dict[str, list[QuoteCase]] = {}
    for case in quote_cases:
        if case.quote_approval is not None:
            approval_cases.setdefault(case.quote_approval.approval_id, []).append(case)
    items.extend(
        _quote_approval_item(
            approval,
            linked_cases=approval_cases.get(approval.approval_id, []),
            now=current,
        )
        for approval in approval_repository.list_all()
        if approval.approval_status == "pending"
    )

    def sort_created(item: dict[str, Any]) -> datetime:
        value = item.get("created_at")
        if isinstance(value, datetime):
            return aware_utc(value)
        return datetime.max.replace(tzinfo=timezone.utc)

    items.sort(
        key=lambda item: (
            PRIORITY_RANK[item["priority_band"]],
            -item["priority_score"],
            item.get("days_until_nearest_deadline", 10**9),
            sort_created(item),
            item["work_id"],
        )
    )
    priority_counts = {band: 0 for band in ("critical", "high", "normal", "low")}
    work_type_counts: dict[str, int] = {}
    for item in items:
        priority_counts[item["priority_band"]] += 1
        work_type_counts[item["work_type"]] = work_type_counts.get(item["work_type"], 0) + 1
    return {
        "generated_at": current,
        "pending_count": len(items),
        "priority_counts": priority_counts,
        "work_type_counts": dict(sorted(work_type_counts.items())),
        "items": items,
    }
