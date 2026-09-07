from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.automation_action_repository import AutomationActionRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.automation_policy_service import find_supplier_policy_profile, resolve_effective_automation_policy
from src.core.automation_policy_repository import AgencyAutomationPolicyRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.business_calendar import (
    SupplierHolidayCalendarCoverageError,
    add_supplier_business_minutes,
    is_supplier_business_time,
    next_supplier_business_open,
)
from src.core.supplier_commercial_safety import evaluate_supplier_commercial_safety
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import SupplierRFQRepository


def aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def supplier_action_key(rfq_id: str, action_type: str) -> str:
    return f"{action_type}:{rfq_id}"


def customer_deadline_action_key(workflow_id: str) -> str:
    return f"customer_deadline_update:{workflow_id}"


def latest_supplier_response_status(
    repository: SupplierRFQRepository, rfq_id: str
) -> str | None:
    responses = repository.list_responses(rfq_id)
    if not responses:
        return None
    return max(responses, key=lambda item: aware_utc(item.received_at)).status


def supplier_reminder_plan(
    *,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    draft: SupplierRFQDraft,
    now: datetime,
    mina_job_repository: MinaJobRepository | None = None,
    master_data_repository: MasterDataRepository | None = None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None = None,
) -> dict[str, Any]:
    workflow = supplier_repository.get_workflow(draft.workflow_id)
    if workflow is None or workflow.automation_timing_version < 1:
        return {"state": "not_automation_eligible"}
    if mina_job_repository is not None and workflow.mina_job_id:
        linked_job = mina_job_repository.get(workflow.mina_job_id)
        if linked_job is not None and linked_job.stage in {
            "accepted", "operations", "operation_opened", "supplier_confirmation_pending",
            "vehicle_details_pending", "vehicle_assigned", "pre_loading_check",
            "ready_for_loading", "loaded", "in_transit", "delivery", "delivered",
            "pod_cmr_pending", "closing_review", "completed", "lost", "cancelled",
        }:
            return {"state": "procurement_closed"}
    if draft.status != "awaiting_response" or draft.sent_at is None:
        return {"state": "not_waiting_for_response"}
    if not draft.recipient_email:
        return {"state": "missing_supplier_recipient_manual_attention"}
    if latest_supplier_response_status(supplier_repository, draft.rfq_id) is not None:
        return {"state": "commercial_response_present"}

    supplier_profile = find_supplier_policy_profile(master_data_repository, draft.supplier_name)
    relationship = None if supplier_profile is None else supplier_profile.relationship
    first_reminder_minutes = (
        relationship.first_reminder_minutes
        if relationship is not None and relationship.first_reminder_minutes is not None
        else workflow.dispatch_policy.no_response_reminder_minutes
    )
    acknowledged_wait_minutes = (
        relationship.acknowledged_wait_minutes
        if relationship is not None and relationship.acknowledged_wait_minutes is not None
        else workflow.dispatch_policy.acknowledged_grace_minutes
    )

    acknowledgements = supplier_repository.list_acknowledgements(draft.rfq_id)
    try:
        if acknowledgements:
            anchor = max(aware_utc(item.acknowledged_at) for item in acknowledgements)
            action_type = "supplier_acknowledged_reminder"
            due_at = add_supplier_business_minutes(anchor, acknowledged_wait_minutes)
        else:
            action_type = "supplier_no_response_reminder"
            due_at = add_supplier_business_minutes(aware_utc(draft.sent_at), first_reminder_minutes)
    except SupplierHolidayCalendarCoverageError as exc:
        return {
            "state": "supplier_calendar_unavailable_manual_attention",
            "reason": str(exc),
        }

    action_key = supplier_action_key(draft.rfq_id, action_type)
    action = action_repository.get(action_key)
    current = aware_utc(now)
    preferred_channels = ["email", "phone", "whatsapp"] if relationship is None else relationship.preferred_contact_channels
    max_email_reminders = None if relationship is None else relationship.max_email_reminders

    if action is not None:
        if action.status == "sent":
            try:
                if not is_supplier_business_time(current):
                    return {
                        "state": "outside_business_hours_waiting",
                        "action_type": action_type,
                        "action_key": action_key,
                        "due_at": due_at,
                        "resume_at": next_supplier_business_open(current),
                    }
            except SupplierHolidayCalendarCoverageError as exc:
                return {
                    "state": "supplier_calendar_unavailable_manual_attention",
                    "reason": str(exc),
                }
            escalation_candidates = []
            if relationship is not None:
                if "phone" in preferred_channels and relationship.phone_escalation_after_minutes is not None:
                    escalation_candidates.append(("phone", relationship.phone_escalation_after_minutes))
                if "whatsapp" in preferred_channels and relationship.whatsapp_escalation_after_minutes is not None:
                    escalation_candidates.append(("whatsapp", relationship.whatsapp_escalation_after_minutes))
            if escalation_candidates and action.completed_at is not None:
                channel, delay_minutes = min(escalation_candidates, key=lambda item: item[1])
                try:
                    escalation_due_at = add_supplier_business_minutes(
                        aware_utc(action.completed_at), delay_minutes
                    )
                except SupplierHolidayCalendarCoverageError as exc:
                    return {
                        "state": "supplier_calendar_unavailable_manual_attention",
                        "reason": str(exc),
                    }
                if current < escalation_due_at:
                    return {
                        "state": "waiting_supplier_contact_escalation",
                        "action_type": action_type,
                        "action_key": action_key,
                        "due_at": due_at,
                        "escalation_due_at": escalation_due_at,
                        "preferred_escalation_channel": channel,
                        "preferred_contact_channels": preferred_channels,
                    }
            return {
                "state": "human_contact_required",
                "action_type": action_type,
                "action_key": action_key,
                "due_at": due_at,
                "reason": (
                    "no_response_after_reminder"
                    if action_type == "supplier_no_response_reminder"
                    else "no_commercial_response_after_acknowledged_reminder"
                ),
                "preferred_contact_channels": preferred_channels,
                "management_escalation_allowed": (
                    None if relationship is None else relationship.management_escalation_allowed
                ),
            }
        if action.status == "cancelled" and action.failure_code == "operator_rejected":
            return {
                "state": "approval_rejected_no_send",
                "action_type": action_type,
                "action_key": action_key,
                "due_at": due_at,
                "automation_status": action.status,
            }
        return {
            "state": (
                "automation_cancelled_manual_attention"
                if action.status == "cancelled"
                else "automation_delivery_attention"
            ),
            "action_type": action_type,
            "action_key": action_key,
            "due_at": due_at,
            "automation_status": action.status,
        }
    if current < due_at:
        return {
            "state": "waiting",
            "action_type": action_type,
            "action_key": action_key,
            "due_at": due_at,
        }
    if max_email_reminders == 0 or "email" not in preferred_channels:
        return {
            "state": "human_contact_required",
            "action_type": action_type,
            "action_key": action_key,
            "due_at": due_at,
            "reason": "supplier_email_reminders_disabled",
            "preferred_contact_channels": preferred_channels,
            "management_escalation_allowed": (
                None if relationship is None else relationship.management_escalation_allowed
            ),
        }
    try:
        if not is_supplier_business_time(current):
            return {
                "state": "outside_business_hours_waiting",
                "action_type": action_type,
                "action_key": action_key,
                "due_at": due_at,
                "resume_at": next_supplier_business_open(current),
            }
    except SupplierHolidayCalendarCoverageError as exc:
        return {
            "state": "supplier_calendar_unavailable_manual_attention",
            "reason": str(exc),
        }
    policy = resolve_effective_automation_policy(
        action="supplier_reminder",
        legacy_dispatch_enabled=workflow.dispatch_policy.automatic_supplier_reminders_enabled,
        mina_job_repository=mina_job_repository,
        job_id=workflow.mina_job_id,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_policy_repository,
        supplier_name=draft.supplier_name,
    )
    state = {
        "manual": "manual_reminder_due",
        "approval_required": "approval_required_supplier_reminder_due",
        "automatic": "automatic_reminder_due",
    }[policy.effective_mode]
    if (
        relationship is not None
        and relationship.automatic_contact_blocked
        and policy.effective_mode == "automatic"
    ):
        state = "approval_required_supplier_reminder_due"
    return {
        "state": state,
        "action_type": action_type,
        "action_key": action_key,
        "due_at": due_at,
        "automation_policy": policy.model_dump(),
        "supplier_relationship": {
            "supplier_id": None if supplier_profile is None else supplier_profile.supplier_id,
            "first_reminder_minutes": first_reminder_minutes,
            "acknowledged_wait_minutes": acknowledged_wait_minutes,
            "max_email_reminders": max_email_reminders,
            "current_flow_effective_email_reminder_limit": (
                None if max_email_reminders is None else min(max_email_reminders, 1)
            ),
            "automatic_contact_blocked": False if relationship is None else relationship.automatic_contact_blocked,
            "phone_escalation_after_minutes": None if relationship is None else relationship.phone_escalation_after_minutes,
            "whatsapp_escalation_after_minutes": None if relationship is None else relationship.whatsapp_escalation_after_minutes,
            "management_escalation_allowed": None if relationship is None else relationship.management_escalation_allowed,
            "preferred_contact_channels": ["email", "phone", "whatsapp"] if relationship is None else relationship.preferred_contact_channels,
        },
    }


def workflow_has_usable_supplier_price(
    *,
    supplier_repository: SupplierRFQRepository,
    workflow: SupplierRFQWorkflow,
    now: datetime,
) -> bool:
    for draft in supplier_repository.list_drafts():
        if draft.workflow_id != workflow.workflow_id:
            continue
        responses = supplier_repository.list_responses(draft.rfq_id)
        if not responses:
            continue
        response = max(responses, key=lambda item: aware_utc(item.received_at))
        if response.status != "quoted" or not response.is_price_usable:
            continue
        safety = evaluate_supplier_commercial_safety(
            response=response,
            shipment=workflow.shipment,
            expected_equipment=workflow.shipment.equipment_type,
            as_of=aware_utc(now).date(),
        )
        if safety.eligible_for_customer_quote:
            return True
    return False


def customer_deadline_plan(
    *,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    workflow: SupplierRFQWorkflow,
    now: datetime,
    mina_job_repository: MinaJobRepository | None = None,
    master_data_repository: MasterDataRepository | None = None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None = None,
) -> dict[str, Any]:
    if workflow.automation_timing_version < 1:
        return {"state": "not_automation_eligible"}
    if mina_job_repository is not None and workflow.mina_job_id:
        linked_job = mina_job_repository.get(workflow.mina_job_id)
        if linked_job is not None and linked_job.stage in {
            "accepted", "operations", "operation_opened", "supplier_confirmation_pending",
            "vehicle_details_pending", "vehicle_assigned", "pre_loading_check",
            "ready_for_loading", "loaded", "in_transit", "delivery", "delivered",
            "pod_cmr_pending", "closing_review", "completed", "lost", "cancelled",
        }:
            return {"state": "customer_quote_lifecycle_closed"}
    deadline = workflow.shipment.customer_quote_deadline_at
    if deadline is None:
        return {"state": "no_explicit_customer_deadline"}
    if not workflow.sender_address:
        return {"state": "missing_customer_recipient_manual_attention"}
    if workflow_has_usable_supplier_price(
        supplier_repository=supplier_repository,
        workflow=workflow,
        now=now,
    ):
        return {"state": "usable_price_available"}

    current = aware_utc(now)
    deadline_utc = aware_utc(deadline)
    due_at = deadline_utc - timedelta(
        minutes=workflow.dispatch_policy.customer_deadline_proactive_minutes
    )
    action_key = customer_deadline_action_key(workflow.workflow_id)
    action = action_repository.get(action_key)
    if action is not None:
        if action.status == "sent":
            return {"state": "customer_update_sent", "action_key": action_key, "due_at": due_at}
        if action.status == "cancelled" and action.failure_code == "operator_rejected":
            return {
                "state": "approval_rejected_no_send",
                "action_key": action_key,
                "due_at": due_at,
                "automation_status": action.status,
            }
        return {
            "state": (
                "automation_cancelled_manual_attention"
                if action.status == "cancelled"
                else "automation_delivery_attention"
            ),
            "action_key": action_key,
            "due_at": due_at,
            "automation_status": action.status,
        }
    if current < due_at:
        return {"state": "waiting", "due_at": due_at}
    if current >= deadline_utc:
        return {
            "state": "deadline_passed_manual_attention",
            "due_at": due_at,
            "deadline_at": deadline_utc,
        }
    policy = resolve_effective_automation_policy(
        action="customer_deadline_update",
        legacy_dispatch_enabled=workflow.dispatch_policy.automatic_customer_deadline_updates_enabled,
        mina_job_repository=mina_job_repository,
        job_id=workflow.mina_job_id,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_policy_repository,
    )
    state = {
        "manual": "manual_customer_update_due",
        "approval_required": "approval_required_customer_update_due",
        "automatic": "automatic_customer_update_due",
    }[policy.effective_mode]
    result = {
        "state": state,
        "action_key": action_key,
        "due_at": due_at,
        "deadline_at": deadline_utc,
        "automation_policy": policy.model_dump(),
    }
    return result
