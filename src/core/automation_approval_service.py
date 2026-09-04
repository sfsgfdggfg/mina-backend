from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from src.core.automation_action import ScheduledAutomationAction
from src.core.automation_action_repository import AutomationActionRepository
from src.core.automation_planning import aware_utc, customer_deadline_plan, supplier_reminder_plan
from src.core.automation_policy_repository import AgencyAutomationPolicyRepository
from src.core.mail import MailSendResult, OutboundMailSender
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.workflow.automation_scheduler import (
    build_customer_deadline_update_request,
    build_supplier_reminder_request,
)
from src.workflow.mail_delivery import dispatch_outbound_mail


ApprovalDecision = Literal["approve", "reject"]


class AutomationApprovalError(ValueError):
    pass


class _IgnoringActionRepository:
    def __init__(self, repository: AutomationActionRepository, ignored_key: str) -> None:
        self.repository = repository
        self.ignored_key = ignored_key

    def get(self, action_key: str):
        return None if action_key == self.ignored_key else self.repository.get(action_key)

    def reserve(self, action):
        return self.repository.reserve(action)

    def save(self, action):
        return self.repository.save(action)

    def list_all(self):
        return self.repository.list_all()


def _now(value: datetime | None = None) -> datetime:
    return aware_utc(value or datetime.now(timezone.utc))


def _actor(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _decision_reason(decision: ApprovalDecision, value: str | None) -> str | None:
    normalized = None if value is None else value.strip()
    if decision == "reject" and not normalized:
        raise ValueError("Rejecting an approval-required action requires a reason.")
    if normalized and len(normalized) > 800:
        raise ValueError("Approval decision reason is too long.")
    return normalized


def _load_job_workflow(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    job_id: str,
):
    job = mina_job_repository.get(job_id)
    if job is None:
        raise AutomationApprovalError(f"MINA job not found: {job_id}")
    if job.is_closed:
        raise AutomationApprovalError("Closed MINA job cannot execute outbound approvals.")
    if not job.supplier_rfq_workflow_id:
        raise AutomationApprovalError("MINA job has no linked supplier RFQ workflow.")
    workflow = supplier_repository.get_workflow(job.supplier_rfq_workflow_id)
    if workflow is None:
        raise AutomationApprovalError("Linked supplier RFQ workflow was not found.")
    if workflow.mina_job_id != job.job_id:
        raise AutomationApprovalError("Supplier RFQ workflow is not linked to this MINA job.")
    return job, workflow


def _supplier_context(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    master_data_repository: MasterDataRepository | None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None,
    job_id: str,
    rfq_id: str,
    now: datetime,
):
    job, workflow = _load_job_workflow(
        mina_job_repository=mina_job_repository,
        supplier_repository=supplier_repository,
        job_id=job_id,
    )
    draft = supplier_repository.get_draft(rfq_id)
    if draft is None or draft.workflow_id != workflow.workflow_id:
        raise AutomationApprovalError("Supplier RFQ does not belong to this MINA job.")
    plan = supplier_reminder_plan(
        supplier_repository=supplier_repository,
        action_repository=action_repository,
        draft=draft,
        now=now,
        mina_job_repository=mina_job_repository,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_policy_repository,
    )
    if plan.get("state") != "approval_required_supplier_reminder_due":
        raise AutomationApprovalError(
            "Supplier reminder is not currently in approval-required due state."
        )
    return job, workflow, draft, plan


def _customer_context(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    master_data_repository: MasterDataRepository | None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None,
    job_id: str,
    now: datetime,
):
    job, workflow = _load_job_workflow(
        mina_job_repository=mina_job_repository,
        supplier_repository=supplier_repository,
        job_id=job_id,
    )
    plan = customer_deadline_plan(
        supplier_repository=supplier_repository,
        action_repository=action_repository,
        workflow=workflow,
        now=now,
        mina_job_repository=mina_job_repository,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_policy_repository,
    )
    if plan.get("state") != "approval_required_customer_update_due":
        raise AutomationApprovalError(
            "Customer deadline update is not currently in approval-required due state."
        )
    return job, workflow, plan


def preview_supplier_reminder_approval(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    master_data_repository: MasterDataRepository | None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None,
    job_id: str,
    rfq_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _now(now)
    job, workflow, draft, plan = _supplier_context(
        mina_job_repository=mina_job_repository,
        supplier_repository=supplier_repository,
        action_repository=action_repository,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_policy_repository,
        job_id=job_id,
        rfq_id=rfq_id,
        now=current,
    )
    request = build_supplier_reminder_request(
        draft=draft,
        action_type=plan["action_type"],
        action_key=plan["action_key"],
    )
    return {
        "mina_code": job.mina_code,
        "rfq_id": draft.rfq_id,
        "supplier_name": draft.supplier_name,
        "action_type": plan["action_type"],
        "action_key": plan["action_key"],
        "due_at": plan["due_at"],
        "subject": request.subject,
        "body_text": request.body_text,
        "decision_required": True,
    }


def preview_customer_deadline_update_approval(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    master_data_repository: MasterDataRepository | None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None,
    job_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _now(now)
    job, workflow, plan = _customer_context(
        mina_job_repository=mina_job_repository,
        supplier_repository=supplier_repository,
        action_repository=action_repository,
        master_data_repository=master_data_repository,
        agency_policy_repository=agency_policy_repository,
        job_id=job_id,
        now=current,
    )
    request = build_customer_deadline_update_request(
        workflow=workflow,
        action_key=plan["action_key"],
    )
    return {
        "mina_code": job.mina_code,
        "workflow_id": workflow.workflow_id,
        "action_type": "customer_deadline_update",
        "action_key": plan["action_key"],
        "due_at": plan["due_at"],
        "deadline_at": plan.get("deadline_at"),
        "subject": request.subject,
        "body_text": request.body_text,
        "decision_required": True,
    }


def _build_operator_action(
    *, action_key: str,
    action_type: str,
    workflow_id: str,
    resource_id: str,
    due_at: datetime,
    actor: str,
    now: datetime,
    rejected: bool,
) -> ScheduledAutomationAction:
    return ScheduledAutomationAction(
        action_key=action_key,
        action_type=action_type,
        workflow_id=workflow_id,
        resource_id=resource_id,
        due_at=aware_utc(due_at),
        status="cancelled" if rejected else "reserved",
        reserved_at=now,
        completed_at=now if rejected else None,
        failure_code="operator_rejected" if rejected else None,
        trigger_mode="operator_approved",
        triggered_by_operator=actor,
        source="operator_approval_outbound",
    )


def _complete_action(
    *, action_repository: AutomationActionRepository,
    action: ScheduledAutomationAction,
    delivery: MailSendResult,
    now: datetime,
) -> ScheduledAutomationAction:
    status = "sent" if delivery.status == "sent" else "failed"
    updated = action.model_copy(update={
        "status": status,
        "completed_at": aware_utc(delivery.sent_at or now),
        "provider_name": delivery.provider_name if status == "sent" else None,
        "provider_message_id": delivery.provider_message_id if status == "sent" else None,
        "failure_code": None if status == "sent" else f"delivery_{delivery.status}",
    })
    return action_repository.save(updated)


def _append_job_event(
    *, mina_job_repository: MinaJobRepository,
    job,
    actor: str,
    event_type: str,
    resource_type: str,
    resource_id: str,
    occurred_at: datetime,
    metadata: dict[str, Any],
) -> None:
    mina_job_repository.append_event(MinaJobEvent(
        job_id=job.job_id,
        mina_code=job.mina_code,
        event_type=event_type,
        occurred_at=occurred_at,
        actor=actor,
        resource_type=resource_type,
        resource_id=resource_id,
        metadata=metadata,
    ))
    mina_job_repository.save(job.model_copy(update={"updated_at": occurred_at}))


def _cancel_stale_action(
    *, action_repository: AutomationActionRepository,
    action: ScheduledAutomationAction,
    now: datetime,
) -> ScheduledAutomationAction:
    cancelled = action.model_copy(update={
        "status": "cancelled",
        "completed_at": now,
        "failure_code": "state_changed_before_approved_send",
    })
    return action_repository.save(cancelled)


def decide_supplier_reminder_approval(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    master_data_repository: MasterDataRepository | None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None,
    sender: OutboundMailSender | None,
    job_id: str,
    rfq_id: str,
    decision: ApprovalDecision,
    actor: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _now(now)
    operator = _actor(actor)
    decision_reason = _decision_reason(decision, reason)
    with atomic_repository_transaction(
        mina_job_repository, supplier_repository, action_repository
    ):
        job, workflow, draft, plan = _supplier_context(
            mina_job_repository=mina_job_repository,
            supplier_repository=supplier_repository,
            action_repository=action_repository,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
            job_id=job_id,
            rfq_id=rfq_id,
            now=current,
        )
        action = _build_operator_action(
            action_key=plan["action_key"],
            action_type=plan["action_type"],
            workflow_id=workflow.workflow_id,
            resource_id=draft.rfq_id,
            due_at=plan["due_at"],
            actor=operator,
            now=current,
            rejected=decision == "reject",
        )
        if not action_repository.reserve(action):
            raise AutomationApprovalError("Approval action was decided concurrently.")
        if decision == "reject":
            _append_job_event(
                mina_job_repository=mina_job_repository,
                job=job,
                actor=operator,
                event_type="supplier_reminder_rejected",
                resource_type="supplier_rfq",
                resource_id=draft.rfq_id,
                occurred_at=current,
                metadata={
                    "action_type": action.action_type,
                    "decision": "reject",
                    "reason": decision_reason,
                },
            )
            return {
                "decision": "reject",
                "mina_code": job.mina_code,
                "rfq_id": draft.rfq_id,
                "automation_action": action,
            }

    ignored = _IgnoringActionRepository(action_repository, action.action_key)
    try:
        _, _, current_draft, current_plan = _supplier_context(
            mina_job_repository=mina_job_repository,
            supplier_repository=supplier_repository,
            action_repository=ignored,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
            job_id=job_id,
            rfq_id=rfq_id,
            now=current,
        )
        still_valid = current_plan.get("action_key") == action.action_key
    except AutomationApprovalError:
        still_valid = False
    if not still_valid:
        with atomic_repository_transaction(action_repository, mina_job_repository):
            cancelled = _cancel_stale_action(
                action_repository=action_repository,
                action=action,
                now=current,
            )
            refreshed = mina_job_repository.get(job_id) or job
            _append_job_event(
                mina_job_repository=mina_job_repository,
                job=refreshed,
                actor=operator,
                event_type="supplier_reminder_approval_cancelled",
                resource_type="supplier_rfq",
                resource_id=rfq_id,
                occurred_at=current,
                metadata={"action_type": action.action_type, "reason": cancelled.failure_code},
            )
        raise AutomationApprovalError(
            "Supplier state or policy changed before provider delivery; approved send was cancelled."
        )
    request = build_supplier_reminder_request(
        draft=current_draft,
        action_type=action.action_type,
        action_key=action.action_key,
    )
    delivery = dispatch_outbound_mail(request, sender)
    with atomic_repository_transaction(action_repository, mina_job_repository):
        completed = _complete_action(
            action_repository=action_repository,
            action=action,
            delivery=delivery,
            now=current,
        )
        refreshed = mina_job_repository.get(job_id) or job
        event_type = (
            "supplier_reminder_approved_sent"
            if completed.status == "sent"
            else "supplier_reminder_approved_delivery_failed"
        )
        _append_job_event(
            mina_job_repository=mina_job_repository,
            job=refreshed,
            actor=operator,
            event_type=event_type,
            resource_type="supplier_rfq",
            resource_id=rfq_id,
            occurred_at=completed.completed_at or current,
            metadata={
                "action_type": action.action_type,
                "decision": "approve",
                "delivery_status": delivery.status,
            },
        )
    return {
        "decision": "approve",
        "mina_code": job.mina_code,
        "rfq_id": rfq_id,
        "delivery": delivery,
        "automation_action": completed,
    }


def decide_customer_deadline_update_approval(
    *, mina_job_repository: MinaJobRepository,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    master_data_repository: MasterDataRepository | None,
    agency_policy_repository: AgencyAutomationPolicyRepository | None,
    sender: OutboundMailSender | None,
    job_id: str,
    decision: ApprovalDecision,
    actor: str,
    reason: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = _now(now)
    operator = _actor(actor)
    decision_reason = _decision_reason(decision, reason)
    with atomic_repository_transaction(
        mina_job_repository, supplier_repository, action_repository
    ):
        job, workflow, plan = _customer_context(
            mina_job_repository=mina_job_repository,
            supplier_repository=supplier_repository,
            action_repository=action_repository,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
            job_id=job_id,
            now=current,
        )
        action = _build_operator_action(
            action_key=plan["action_key"],
            action_type="customer_deadline_update",
            workflow_id=workflow.workflow_id,
            resource_id=workflow.workflow_id,
            due_at=plan["due_at"],
            actor=operator,
            now=current,
            rejected=decision == "reject",
        )
        if not action_repository.reserve(action):
            raise AutomationApprovalError("Approval action was decided concurrently.")
        if decision == "reject":
            _append_job_event(
                mina_job_repository=mina_job_repository,
                job=job,
                actor=operator,
                event_type="customer_deadline_update_rejected",
                resource_type="supplier_rfq_workflow",
                resource_id=workflow.workflow_id,
                occurred_at=current,
                metadata={
                    "action_type": "customer_deadline_update",
                    "decision": "reject",
                    "reason": decision_reason,
                },
            )
            return {
                "decision": "reject",
                "mina_code": job.mina_code,
                "workflow_id": workflow.workflow_id,
                "automation_action": action,
            }

    ignored = _IgnoringActionRepository(action_repository, action.action_key)
    try:
        _, current_workflow, current_plan = _customer_context(
            mina_job_repository=mina_job_repository,
            supplier_repository=supplier_repository,
            action_repository=ignored,
            master_data_repository=master_data_repository,
            agency_policy_repository=agency_policy_repository,
            job_id=job_id,
            now=current,
        )
        still_valid = current_plan.get("action_key") == action.action_key
    except AutomationApprovalError:
        still_valid = False
    if not still_valid:
        with atomic_repository_transaction(action_repository, mina_job_repository):
            cancelled = _cancel_stale_action(
                action_repository=action_repository,
                action=action,
                now=current,
            )
            refreshed = mina_job_repository.get(job_id) or job
            _append_job_event(
                mina_job_repository=mina_job_repository,
                job=refreshed,
                actor=operator,
                event_type="customer_deadline_update_approval_cancelled",
                resource_type="supplier_rfq_workflow",
                resource_id=action.resource_id,
                occurred_at=current,
                metadata={"action_type": action.action_type, "reason": cancelled.failure_code},
            )
        raise AutomationApprovalError(
            "Customer state or policy changed before provider delivery; approved send was cancelled."
        )
    request = build_customer_deadline_update_request(
        workflow=current_workflow,
        action_key=action.action_key,
    )
    delivery = dispatch_outbound_mail(request, sender)
    with atomic_repository_transaction(action_repository, mina_job_repository):
        completed = _complete_action(
            action_repository=action_repository,
            action=action,
            delivery=delivery,
            now=current,
        )
        refreshed = mina_job_repository.get(job_id) or job
        event_type = (
            "customer_deadline_update_approved_sent"
            if completed.status == "sent"
            else "customer_deadline_update_approved_delivery_failed"
        )
        _append_job_event(
            mina_job_repository=mina_job_repository,
            job=refreshed,
            actor=operator,
            event_type=event_type,
            resource_type="supplier_rfq_workflow",
            resource_id=current_workflow.workflow_id,
            occurred_at=completed.completed_at or current,
            metadata={
                "action_type": "customer_deadline_update",
                "decision": "approve",
                "delivery_status": delivery.status,
            },
        )
    return {
        "decision": "approve",
        "mina_code": job.mina_code,
        "workflow_id": current_workflow.workflow_id,
        "delivery": delivery,
        "automation_action": completed,
    }
