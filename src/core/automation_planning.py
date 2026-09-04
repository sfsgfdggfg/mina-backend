from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from src.core.automation_action_repository import AutomationActionRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.automation_policy_service import resolve_effective_automation_policy
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
    if draft.status != "awaiting_response" or draft.sent_at is None:
        return {"state": "not_waiting_for_response"}
    if not draft.recipient_email:
        return {"state": "missing_supplier_recipient_manual_attention"}
    if latest_supplier_response_status(supplier_repository, draft.rfq_id) is not None:
        return {"state": "commercial_response_present"}

    acknowledgements = supplier_repository.list_acknowledgements(draft.rfq_id)
    try:
        if acknowledgements:
            anchor = max(aware_utc(item.acknowledged_at) for item in acknowledgements)
            action_type = "supplier_acknowledged_reminder"
            due_at = add_supplier_business_minutes(
                anchor, workflow.dispatch_policy.acknowledged_grace_minutes
            )
        else:
            action_type = "supplier_no_response_reminder"
            due_at = add_supplier_business_minutes(
                aware_utc(draft.sent_at),
                workflow.dispatch_policy.no_response_reminder_minutes,
            )
    except SupplierHolidayCalendarCoverageError as exc:
        return {
            "state": "supplier_calendar_unavailable_manual_attention",
            "reason": str(exc),
        }

    action_key = supplier_action_key(draft.rfq_id, action_type)
    action = action_repository.get(action_key)
    current = aware_utc(now)
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
    )
    state = {
        "manual": "manual_reminder_due",
        "approval_required": "approval_required_supplier_reminder_due",
        "automatic": "automatic_reminder_due",
    }[policy.effective_mode]
    return {
        "state": state,
        "action_type": action_type,
        "action_key": action_key,
        "due_at": due_at,
        "automation_policy": policy.model_dump(),
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
