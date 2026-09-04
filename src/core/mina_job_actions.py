from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.automation_action import ScheduledAutomationAction
from src.core.automation_action_repository import AutomationActionRepository
from src.core.automation_policy_repository import AgencyAutomationPolicyRepository
from src.core.automation_policy_service import resolve_effective_automation_policy
from src.core.master_data_repository import MasterDataRepository
from src.core.automation_planning import (
    aware_utc,
    latest_supplier_response_status,
    supplier_action_key,
)
from src.core.business_calendar import (
    SupplierHolidayCalendarCoverageError,
    add_supplier_business_minutes,
    is_supplier_business_time,
    next_supplier_business_open,
)
from src.core.mail import MailSendResult, OutboundMailSender
from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import get_mina_job_or_raise
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_rfq import SupplierRFQDraft
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.workflow.automation_scheduler import build_supplier_reminder_request
from src.workflow.mail_delivery import dispatch_outbound_mail


class MinaJobActionError(ValueError):
    pass


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    return aware_utc(current)


def _load_job_draft_workflow(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    mina_code: str, rfq_id: str,
):
    job = get_mina_job_or_raise(mina_job_repository, mina_code=mina_code)
    if job.is_closed:
        raise MinaJobActionError("Closed MINA job cannot send supplier reminders.")
    draft = supplier_repository.get_draft(rfq_id)
    if draft is None:
        raise MinaJobActionError(f"Supplier RFQ not found: {rfq_id}")
    workflow = supplier_repository.get_workflow(draft.workflow_id)
    if workflow is None:
        raise MinaJobActionError("Supplier RFQ workflow not found.")
    if workflow.mina_job_id != job.job_id:
        raise MinaJobActionError("Supplier RFQ does not belong to this MINA job.")
    return job, draft, workflow


def _current_reminder_context(
    *, supplier_repository: SupplierRFQRepository,
    draft: SupplierRFQDraft, workflow,
) -> dict[str, Any]:
    if draft.status != "awaiting_response" or draft.sent_at is None:
        raise MinaJobActionError("Supplier RFQ is not awaiting a response.")
    if not draft.recipient_email:
        raise MinaJobActionError("Supplier RFQ has no recipient email.")
    if latest_supplier_response_status(supplier_repository, draft.rfq_id) is not None:
        raise MinaJobActionError("Supplier already has a commercial response.")
    acknowledgements = supplier_repository.list_acknowledgements(draft.rfq_id)
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
    return {
        "action_type": action_type,
        "action_key": supplier_action_key(draft.rfq_id, action_type),
        "due_at": due_at,
    }


def preview_supplier_reminder_now(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    mina_code: str, rfq_id: str, now: datetime | None = None,
) -> dict[str, Any]:
    current = _now(now)
    job, draft, workflow = _load_job_draft_workflow(
        mina_job_repository=mina_job_repository,
        supplier_repository=supplier_repository,
        mina_code=mina_code,
        rfq_id=rfq_id,
    )
    try:
        context = _current_reminder_context(
            supplier_repository=supplier_repository, draft=draft, workflow=workflow
        )
        business_open = is_supplier_business_time(current)
        resume_at = None if business_open else next_supplier_business_open(current)
    except SupplierHolidayCalendarCoverageError as exc:
        raise MinaJobActionError(str(exc)) from exc
    existing = action_repository.get(context["action_key"])
    if existing is not None:
        raise MinaJobActionError(
            f"Reminder action already has durable state: {existing.status}."
        )
    request = build_supplier_reminder_request(
        draft=draft,
        action_type=context["action_type"],
        action_key=context["action_key"],
    )
    return {
        "mina_code": job.mina_code,
        "rfq_id": draft.rfq_id,
        "supplier_name": draft.supplier_name,
        "action_type": context["action_type"],
        "planned_due_at": context["due_at"],
        "send_now_allowed": business_open,
        "next_supplier_open_at": resume_at,
        "subject": request.subject,
        "body_text": request.body_text,
    }


def _complete_operator_action(
    *, action_repository: AutomationActionRepository,
    action: ScheduledAutomationAction, delivery: MailSendResult,
    completed_at: datetime,
) -> ScheduledAutomationAction:
    status = "sent" if delivery.status == "sent" else "failed"
    updated = action.model_copy(update={
        "status": status,
        "completed_at": aware_utc(delivery.sent_at or completed_at),
        "provider_name": delivery.provider_name if status == "sent" else None,
        "provider_message_id": delivery.provider_message_id if status == "sent" else None,
        "failure_code": None if status == "sent" else f"delivery_{delivery.status}",
    })
    return action_repository.save(updated)


def send_supplier_reminder_now(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    sender: OutboundMailSender | None,
    mina_code: str, rfq_id: str, actor: str,
    master_data_repository: MasterDataRepository | None = None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _now(now)
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("Operator identity is required.")
    job, draft, workflow = _load_job_draft_workflow(
        mina_job_repository=mina_job_repository,
        supplier_repository=supplier_repository,
        mina_code=mina_code,
        rfq_id=rfq_id,
    )
    effective_policy = resolve_effective_automation_policy(
        action="supplier_reminder",
        legacy_dispatch_enabled=workflow.dispatch_policy.automatic_supplier_reminders_enabled,
        mina_job_repository=mina_job_repository,
        job_id=job.job_id,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_policy_repository,
    )
    if effective_policy.effective_mode == "approval_required":
        raise MinaJobActionError(
            "Supplier reminder requires explicit approval and cannot use reminder-now."
        )
    try:
        if not is_supplier_business_time(current):
            resume_at = next_supplier_business_open(current)
            raise MinaJobActionError(
                "Supplier reminder cannot be sent outside supplier communication "
                f"hours; next opening is {resume_at.isoformat()}."
            )
        context = _current_reminder_context(
            supplier_repository=supplier_repository, draft=draft, workflow=workflow
        )
    except SupplierHolidayCalendarCoverageError as exc:
        raise MinaJobActionError(str(exc)) from exc
    with atomic_repository_transaction(
        supplier_repository, action_repository, mina_job_repository
    ):
        if action_repository.get(context["action_key"]) is not None:
            raise MinaJobActionError("Reminder action already has durable state.")
        action = ScheduledAutomationAction(
            action_key=context["action_key"],
            action_type=context["action_type"],
            workflow_id=workflow.workflow_id,
            resource_id=draft.rfq_id,
            due_at=context["due_at"],
            reserved_at=current,
            trigger_mode="operator_early",
            triggered_by_operator=normalized_actor,
            source="operator_early_outbound",
        )
        if not action_repository.reserve(action):
            raise MinaJobActionError("Reminder action was reserved concurrently.")

    # Recheck immediately before provider delivery just like the scheduler.
    try:
        current_job, current_draft, current_workflow = _load_job_draft_workflow(
            mina_job_repository=mina_job_repository,
            supplier_repository=supplier_repository,
            mina_code=mina_code,
            rfq_id=rfq_id,
        )
        current_context = _current_reminder_context(
            supplier_repository=supplier_repository,
            draft=current_draft,
            workflow=current_workflow,
        )
        current_policy = resolve_effective_automation_policy(
            action="supplier_reminder",
            legacy_dispatch_enabled=current_workflow.dispatch_policy.automatic_supplier_reminders_enabled,
            mina_job_repository=mina_job_repository,
            job_id=current_job.job_id,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
        )
        valid_to_send = (
            is_supplier_business_time(current)
            and current_context["action_key"] == action.action_key
            and current_policy.effective_mode != "approval_required"
        )
    except (MinaJobActionError, SupplierHolidayCalendarCoverageError):
        valid_to_send = False
    if not valid_to_send:
        with atomic_repository_transaction(action_repository):
            action_repository.save(action.model_copy(update={
                "status": "cancelled",
                "completed_at": current,
                "failure_code": "state_changed_before_operator_send",
            }))
        raise MinaJobActionError(
            "Supplier state changed before delivery; reminder was cancelled."
        )

    request = build_supplier_reminder_request(
        draft=current_draft,
        action_type=action.action_type,
        action_key=action.action_key,
    )
    delivery = dispatch_outbound_mail(request, sender)
    with atomic_repository_transaction(action_repository, mina_job_repository):
        completed = _complete_operator_action(
            action_repository=action_repository,
            action=action,
            delivery=delivery,
            completed_at=current,
        )
        refreshed_job = get_mina_job_or_raise(
            mina_job_repository, job_id=current_job.job_id
        )
        event_type = (
            "supplier_reminder_sent_early"
            if completed.status == "sent"
            else "supplier_reminder_early_delivery_failed"
        )
        mina_job_repository.append_event(MinaJobEvent(
            job_id=refreshed_job.job_id,
            mina_code=refreshed_job.mina_code,
            event_type=event_type,
            occurred_at=completed.completed_at or current,
            actor=normalized_actor,
            resource_type="supplier_rfq",
            resource_id=current_draft.rfq_id,
            metadata={
                "supplier_name": current_draft.supplier_name,
                "action_type": action.action_type,
                "planned_due_at": context["due_at"].isoformat(),
                "sent_before_planned_due": current < context["due_at"],
                "delivery_status": delivery.status,
            },
        ))
        mina_job_repository.save(refreshed_job.model_copy(update={
            "updated_at": completed.completed_at or current,
        }))
    return {
        "mina_code": current_job.mina_code,
        "rfq_id": current_draft.rfq_id,
        "action_type": action.action_type,
        "planned_due_at": context["due_at"],
        "sent_before_planned_due": current < context["due_at"],
        "delivery": delivery,
        "automation_action": completed,
    }
