from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.automation_action_repository import AutomationActionRepository
from src.core.business_calendar import (
    add_business_minutes,
    is_business_time,
    next_business_open,
    proactive_customer_update_due,
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
    if acknowledgements:
        anchor = max(aware_utc(item.acknowledged_at) for item in acknowledgements)
        action_type = "supplier_acknowledged_reminder"
        due_at = add_business_minutes(
            anchor, workflow.dispatch_policy.acknowledged_grace_minutes,
            workflow.dispatch_policy,
        )
    else:
        action_type = "supplier_no_response_reminder"
        due_at = add_business_minutes(
            aware_utc(draft.sent_at),
            workflow.dispatch_policy.no_response_reminder_minutes,
            workflow.dispatch_policy,
        )

    action_key = supplier_action_key(draft.rfq_id, action_type)
    action = action_repository.get(action_key)
    current = aware_utc(now)
    if action is not None:
        if action.status == "sent":
            if not is_business_time(current, workflow.dispatch_policy):
                return {
                    "state": "outside_business_hours_waiting",
                    "action_type": action_type,
                    "action_key": action_key,
                    "due_at": due_at,
                    "resume_at": next_business_open(current, workflow.dispatch_policy),
                }
            return {
                "state": "human_contact_required",
                "action_type": action_type,
                "action_key": action_key,
                "due_at": due_at,
                "reason": (
                    "no_response_after_automatic_reminder"
                    if action_type == "supplier_no_response_reminder"
                    else "no_commercial_response_after_acknowledged_reminder"
                ),
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
    if not is_business_time(current, workflow.dispatch_policy):
        return {
            "state": "outside_business_hours_waiting",
            "action_type": action_type,
            "action_key": action_key,
            "due_at": due_at,
            "resume_at": next_business_open(current, workflow.dispatch_policy),
        }
    if not workflow.dispatch_policy.automatic_supplier_reminders_enabled:
        return {
            "state": "manual_reminder_due",
            "action_type": action_type,
            "action_key": action_key,
            "due_at": due_at,
        }
    return {
        "state": "automatic_reminder_due",
        "action_type": action_type,
        "action_key": action_key,
        "due_at": due_at,
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
    due_at = proactive_customer_update_due(
        deadline,
        workflow.dispatch_policy.customer_deadline_proactive_minutes,
        workflow.dispatch_policy,
    )
    action_key = customer_deadline_action_key(workflow.workflow_id)
    action = action_repository.get(action_key)
    if action is not None:
        if action.status == "sent":
            return {"state": "customer_update_sent", "due_at": due_at}
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
    if not is_business_time(current, workflow.dispatch_policy):
        return {
            "state": "outside_business_hours_waiting",
            "due_at": due_at,
            "deadline_at": deadline_utc,
            "resume_at": next_business_open(current, workflow.dispatch_policy),
        }
    if current >= deadline_utc:
        return {
            "state": "deadline_passed_manual_attention",
            "due_at": due_at,
            "deadline_at": deadline_utc,
        }
    if not workflow.dispatch_policy.automatic_customer_deadline_updates_enabled:
        return {"state": "manual_customer_update_due", "due_at": due_at}
    return {
        "state": "automatic_customer_update_due",
        "action_key": action_key,
        "due_at": due_at,
        "deadline_at": deadline_utc,
    }
