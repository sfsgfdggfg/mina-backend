from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.supplier_rfq import (
    SupplierRFQAcknowledgementEvidence,
    SupplierRFQDraft,
    SupplierSecondaryDispatchAuthorization,
)
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.core.supplier_commercial_safety import evaluate_supplier_commercial_safety
from src.core.sqlite_repositories import atomic_repository_transaction


class SupplierAcknowledgementError(ValueError):
    pass


class SupplierSecondaryDispatchBlockedError(ValueError):
    pass


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)


def _workflow_drafts(repository: SupplierRFQRepository, workflow_id: str) -> list[SupplierRFQDraft]:
    return [draft for draft in repository.list_drafts() if draft.workflow_id == workflow_id]


def _latest_response(repository: SupplierRFQRepository, rfq_id: str):
    responses = repository.list_responses(rfq_id)
    if not responses:
        return None
    return max(responses, key=lambda item: _utc(item.received_at))


def _latest_response_status(repository: SupplierRFQRepository, rfq_id: str) -> str | None:
    response = _latest_response(repository, rfq_id)
    return None if response is None else response.status


def _primary_resolution(repository: SupplierRFQRepository, workflow_id: str) -> dict[str, Any]:
    workflow = repository.get_workflow(workflow_id)
    if workflow is None:
        raise SupplierSecondaryDispatchBlockedError("Supplier RFQ workflow not found.")
    primaries = [
        draft for draft in _workflow_drafts(repository, workflow_id)
        if draft.dispatch_tier == "primary"
    ]
    latest_responses = [
        _latest_response(repository, draft.rfq_id) for draft in primaries
    ]
    statuses = [
        None if response is None else response.status
        for response in latest_responses
    ]
    deadline_incompatible: list[bool] = []
    for response in latest_responses:
        if response is None or response.status != "quoted":
            deadline_incompatible.append(False)
            continue
        safety = evaluate_supplier_commercial_safety(
            response=response,
            shipment=workflow.shipment,
            expected_equipment=workflow.shipment.equipment_type,
        )
        deadline_incompatible.append(
            "required_delivery_date_not_achievable" in safety.reasons
        )
    all_terminal = bool(primaries) and all(
        status in {"quoted", "no_capacity", "declined"}
        for status in statuses
    )
    all_explicitly_unavailable = bool(primaries) and all(
        status in {"no_capacity", "declined"}
        for status in statuses
    )
    all_operationally_unavailable = bool(primaries) and all(
        status in {"no_capacity", "declined"} or deadline_miss
        for status, deadline_miss in zip(statuses, deadline_incompatible)
    )
    any_quoted = any(status == "quoted" for status in statuses)
    return {
        "primary_count": len(primaries),
        "statuses": statuses,
        "all_terminal": all_terminal,
        "all_unavailable": all_explicitly_unavailable,
        "all_operationally_unavailable": all_operationally_unavailable,
        "any_delivery_incompatible": any(deadline_incompatible),
        "any_quoted": any_quoted,
    }


def secondary_dispatch_gate(repository: SupplierRFQRepository, workflow_id: str) -> dict[str, Any]:
    workflow = repository.get_workflow(workflow_id)
    if workflow is None:
        raise SupplierSecondaryDispatchBlockedError("Supplier RFQ workflow not found.")
    resolution = _primary_resolution(repository, workflow_id)
    authorization = repository.get_secondary_dispatch_authorization(workflow_id)
    commercial_release = (
        authorization is not None
        and resolution["all_terminal"]
        and resolution["any_quoted"]
        and workflow.dispatch_policy.secondary_after_primary_price_negotiation_exhausted
    )
    capacity_release = (
        resolution["all_operationally_unavailable"]
        and workflow.dispatch_policy.secondary_after_all_primary_unavailable
    )
    allowed = capacity_release or commercial_release
    reason = (
        (
            "all_primary_unavailable_or_delivery_incompatible"
            if resolution["any_delivery_incompatible"]
            else "all_primary_explicitly_unavailable"
        )
        if capacity_release
        else "primary_price_negotiation_exhausted"
        if commercial_release
        else "primary_group_not_exhausted"
    )
    return {
        "allowed": allowed,
        "reason": reason,
        "primary_count": resolution["primary_count"],
        "all_primary_terminal": resolution["all_terminal"],
        "all_primary_unavailable": resolution["all_unavailable"],
        "commercial_release_recorded": authorization is not None,
        "silence_never_counts_as_unavailable": True,
        "customer_urgency_never_bypasses_primary": True,
    }


def require_secondary_dispatch_allowed(repository: SupplierRFQRepository, draft: SupplierRFQDraft) -> None:
    if draft.dispatch_tier != "secondary":
        return
    gate = secondary_dispatch_gate(repository, draft.workflow_id)
    if not gate["allowed"]:
        raise SupplierSecondaryDispatchBlockedError(
            "Secondary supplier dispatch is blocked until the primary group is explicitly exhausted."
        )


def record_supplier_acknowledgement(
    *,
    repository: SupplierRFQRepository,
    rfq_id: str,
    channel: str,
    recorded_by: str | None = None,
    acknowledged_at: datetime | None = None,
) -> dict[str, Any]:
    normalized_channel = channel.strip().lower()
    if normalized_channel not in {"email", "phone", "whatsapp", "manual"}:
        raise SupplierAcknowledgementError("Unsupported supplier acknowledgement channel.")
    actor = None if recorded_by is None else recorded_by.strip()
    if normalized_channel != "email" and not actor:
        raise SupplierAcknowledgementError(
            "Manual supplier acknowledgement requires authenticated operator evidence."
        )
    evidence = SupplierRFQAcknowledgementEvidence(
        rfq_id=rfq_id,
        acknowledged_at=acknowledged_at or datetime.utcnow(),
        channel=normalized_channel,
        recorded_by=actor,
    )
    with atomic_repository_transaction(repository):
        draft = repository.get_draft(rfq_id)
        if draft is None:
            raise SupplierAcknowledgementError("Supplier RFQ not found.")
        if draft.status != "awaiting_response":
            raise SupplierAcknowledgementError(
                "Supplier acknowledgement requires an RFQ awaiting response."
            )
        if repository.list_responses(rfq_id):
            raise SupplierAcknowledgementError(
                "Supplier acknowledgement cannot replace an existing commercial response."
            )
        stored = repository.save_acknowledgement(evidence)
    return {
        "rfq_id": stored.rfq_id,
        "acknowledged_at": stored.acknowledged_at,
        "channel": stored.channel,
        "effect": "supplier_seen_confirmed_non_commercial",
        "commercial_response_recorded": False,
    }


def authorize_secondary_after_price_negotiation(
    *,
    repository: SupplierRFQRepository,
    workflow_id: str,
    authorized_by: str,
    authorized_at: datetime | None = None,
) -> dict[str, Any]:
    actor = authorized_by.strip()
    if not actor:
        raise SupplierSecondaryDispatchBlockedError("Authenticated operator is required.")
    evidence = SupplierSecondaryDispatchAuthorization(
        workflow_id=workflow_id,
        authorized_by=actor,
        authorized_at=authorized_at or datetime.utcnow(),
    )
    with atomic_repository_transaction(repository):
        if repository.get_workflow(workflow_id) is None:
            raise SupplierSecondaryDispatchBlockedError("Supplier RFQ workflow not found.")
        resolution = _primary_resolution(repository, workflow_id)
        if not resolution["all_terminal"] or not resolution["any_quoted"]:
            raise SupplierSecondaryDispatchBlockedError(
                "Price-negotiation release requires a final result from every primary supplier and at least one primary quote."
            )
        stored = repository.save_secondary_dispatch_authorization(evidence)
    return {
        "workflow_id": stored.workflow_id,
        "authorized_at": stored.authorized_at,
        "reason": stored.reason,
        "secondary_dispatch_allowed": True,
        "customer_target_price_disclosed": False,
    }


def build_supplier_dispatch_status(
    *,
    repository: SupplierRFQRepository,
    workflow_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    workflow = repository.get_workflow(workflow_id)
    if workflow is None:
        raise SupplierSecondaryDispatchBlockedError("Supplier RFQ workflow not found.")
    current = _utc(now)
    gate = secondary_dispatch_gate(repository, workflow_id)
    items: list[dict[str, Any]] = []
    drafts = sorted(
        _workflow_drafts(repository, workflow_id),
        key=lambda item: (item.dispatch_tier != "primary", item.priority, item.supplier_name),
    )
    for draft in drafts:
        response_status = _latest_response_status(repository, draft.rfq_id)
        acknowledgements = repository.list_acknowledgements(draft.rfq_id)
        acknowledged_at = (
            max((_utc(item.acknowledged_at) for item in acknowledgements), default=None)
        )
        next_action = "inspect_supplier_rfq"
        reminder_due_at = None
        if response_status == "quoted":
            next_action = "quote_available"
        elif response_status in {"no_capacity", "declined"}:
            next_action = "supplier_unavailable_confirmed"
        elif response_status == "needs_clarification":
            next_action = "resolve_supplier_clarification"
        elif draft.dispatch_tier == "secondary" and draft.status == "draft":
            next_action = "approve_secondary_rfq" if gate["allowed"] else "hold_secondary_rfq"
        elif draft.status == "draft":
            next_action = "approve_primary_rfq"
        elif draft.status == "approved":
            next_action = "send_primary_rfq" if draft.dispatch_tier == "primary" else (
                "send_secondary_rfq" if gate["allowed"] else "hold_secondary_rfq"
            )
        elif draft.status == "awaiting_response" and acknowledged_at is not None:
            reminder_due_at = acknowledged_at + timedelta(
                minutes=workflow.dispatch_policy.acknowledged_grace_minutes
            )
            next_action = (
                "send_acknowledged_reminder"
                if current >= reminder_due_at
                else "wait_acknowledged_supplier"
            )
        elif draft.status == "awaiting_response" and draft.sent_at is not None:
            reminder_due_at = _utc(draft.sent_at) + timedelta(
                minutes=workflow.dispatch_policy.no_response_reminder_minutes
            )
            next_action = (
                "send_no_response_reminder"
                if current >= reminder_due_at
                else "wait_for_supplier_acknowledgement"
            )
        items.append({
            "rfq_id": draft.rfq_id,
            "supplier_name": draft.supplier_name,
            "dispatch_tier": draft.dispatch_tier,
            "supplier_role": draft.supplier_role,
            "rfq_status": draft.status,
            "response_state": response_status or (
                "acknowledged" if acknowledged_at is not None else "no_response"
            ),
            "acknowledged_at": acknowledged_at,
            "reminder_due_at": reminder_due_at,
            "next_action": next_action,
            "human_contact_required_if_still_silent_after_reminder": (
                next_action == "send_no_response_reminder"
            ),
        })
    return {
        "workflow_id": workflow_id,
        "generated_at": current,
        "policy": {
            "primary_group_strategy": workflow.dispatch_policy.primary_group_strategy,
            "no_response_reminder_minutes": workflow.dispatch_policy.no_response_reminder_minutes,
            "acknowledged_grace_minutes": workflow.dispatch_policy.acknowledged_grace_minutes,
            "customer_deadline_proactive_minutes": workflow.dispatch_policy.customer_deadline_proactive_minutes,
        },
        "secondary_gate": gate,
        "items": items,
        "rules": {
            "all_selected_primary_suppliers_are_parallel": True,
            "acknowledgement_is_not_a_quote": True,
            "silence_is_not_no_capacity": True,
            "phone_or_whatsapp_is_human_escalation": True,
            "customer_urgency_does_not_auto_release_secondary": True,
            "customer_target_price_must_not_be_disclosed_to_supplier": True,
        },
    }
