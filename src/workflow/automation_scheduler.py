from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from src.core.automation_action import ScheduledAutomationAction
from src.core.automation_action_repository import AutomationActionRepository
from src.core.automation_planning import (
    aware_utc,
    customer_deadline_plan,
    supplier_reminder_plan,
)
from src.core.mail import OutboundMailRequest, OutboundMailSender
from src.core.mina_job_repository import MinaJobRepository
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.workflow.mail_delivery import dispatch_outbound_mail


DEFAULT_AUTOMATION_POLL_SECONDS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _reply_subject(subject: str | None, fallback: str) -> str:
    normalized = str(subject or "").strip()
    if not normalized:
        return fallback
    if normalized.lower().startswith("re:"):
        return normalized
    return f"Re: {normalized}"


def build_supplier_reminder_request(
    *, draft: SupplierRFQDraft, action_type: str, action_key: str
) -> OutboundMailRequest:
    if action_type == "supplier_no_response_reminder":
        body = f"""
Merhaba,

Aşağıdaki navlun talebimizle ilgili dönüşünüzü rica ederiz.

RFQ Referansı: {draft.reference_token}

Araç uygunluğu ve fiyat çalışmanız hakkında bilgi verebilir misiniz?

Teşekkürler.

Saygılarımızla,
MINAI Freight OS
""".strip()
    else:
        body = f"""
Merhaba,

Aşağıdaki navlun talebimiz üzerinde çalıştığınızı teyit etmiştiniz.
Uygunluk ve fiyat çalışmanızla ilgili güncel dönüşünüzü rica ederiz.

RFQ Referansı: {draft.reference_token}

Teşekkürler.

Saygılarımızla,
MINAI Freight OS
""".strip()
    return OutboundMailRequest(
        operation_id=f"scheduled:{action_key}",
        recipients=[str(draft.recipient_email)],
        subject=_reply_subject(draft.subject, "Navlun talebi hatırlatma"),
        body_text=body,
        purpose="supplier_rfq",
        correlation_reference=draft.reference_token,
        reference_metadata={
            "rfq_id": draft.rfq_id,
            "workflow_id": draft.workflow_id,
            "automation_action": action_type,
        },
    )


def build_customer_deadline_update_request(
    *, workflow: SupplierRFQWorkflow, action_key: str
) -> OutboundMailRequest:
    body = """
Merhaba,

Talebinizle ilgili tedarikçilerimizden araç uygunluğu ve fiyat dönüşlerini bekliyoruz.
Konuyu takip ediyoruz ve mümkün olan en kısa sürede sizi bilgilendireceğiz.

Saygılarımızla,
MINAI Freight OS
""".strip()
    return OutboundMailRequest(
        operation_id=f"scheduled:{action_key}",
        recipients=[str(workflow.sender_address)],
        subject=_reply_subject(workflow.customer_subject, "Fiyat talebiniz hakkında"),
        body_text=body,
        purpose="customer_status_update",
        correlation_reference=workflow.workflow_id,
        reference_metadata={
            "workflow_id": workflow.workflow_id,
            "automation_action": "customer_deadline_update",
        },
    )


def _reserve_action(
    *,
    action_repository: AutomationActionRepository,
    action_key: str,
    action_type: str,
    workflow_id: str,
    resource_id: str,
    due_at: datetime,
    now: datetime,
) -> ScheduledAutomationAction | None:
    if action_repository.get(action_key) is not None:
        return None
    action = ScheduledAutomationAction(
        action_key=action_key,
        action_type=action_type,
        workflow_id=workflow_id,
        resource_id=resource_id,
        due_at=aware_utc(due_at),
        reserved_at=aware_utc(now),
    )
    return action if action_repository.reserve(action) else None


def _complete_action(
    *,
    action_repository: AutomationActionRepository,
    action: ScheduledAutomationAction,
    status: str,
    now: datetime,
    provider_name: str | None = None,
    provider_message_id: str | None = None,
    failure_code: str | None = None,
) -> ScheduledAutomationAction:
    with atomic_repository_transaction(action_repository):
        current = action_repository.get(action.action_key)
        if current is None or current.status != "reserved":
            return current or action
        updated = current.model_copy(
            update={
                "status": status,
                "completed_at": aware_utc(now),
                "provider_name": provider_name,
                "provider_message_id": provider_message_id,
                "failure_code": failure_code,
            }
        )
        return action_repository.save(updated)


def _run_supplier_action(
    *,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    draft: SupplierRFQDraft,
    sender: OutboundMailSender | None,
    now: datetime,
    mina_job_repository: MinaJobRepository | None = None,
) -> str:
    with atomic_repository_transaction(supplier_repository, action_repository):
        current_draft = supplier_repository.get_draft(draft.rfq_id)
        if current_draft is None:
            return "skipped"
        plan = supplier_reminder_plan(
            supplier_repository=supplier_repository,
            action_repository=action_repository,
            draft=current_draft,
            now=now,
            mina_job_repository=mina_job_repository,
        )
        if plan.get("state") != "automatic_reminder_due":
            return "skipped"
        action = _reserve_action(
            action_repository=action_repository,
            action_key=plan["action_key"],
            action_type=plan["action_type"],
            workflow_id=current_draft.workflow_id,
            resource_id=current_draft.rfq_id,
            due_at=plan["due_at"],
            now=now,
        )
    if action is None:
        return "skipped"

    # Recheck immediately before provider delivery. A response/acknowledgement
    # arriving after reservation cancels this action instead of sending stale mail.
    current_draft = supplier_repository.get_draft(draft.rfq_id)
    if current_draft is None:
        _complete_action(
            action_repository=action_repository,
            action=action,
            status="cancelled",
            now=now,
            failure_code="resource_missing_before_send",
        )
        return "cancelled"
    pre_send_plan = supplier_reminder_plan(
        supplier_repository=supplier_repository,
        action_repository=_IgnoringReservedActionRepository(action_repository, action.action_key),
        draft=current_draft,
        now=now,
        mina_job_repository=mina_job_repository,
    )
    if pre_send_plan.get("state") != "automatic_reminder_due":
        _complete_action(
            action_repository=action_repository,
            action=action,
            status="cancelled",
            now=now,
            failure_code="state_changed_before_send",
        )
        return "cancelled"

    request = build_supplier_reminder_request(
        draft=current_draft,
        action_type=action.action_type,
        action_key=action.action_key,
    )
    delivery = dispatch_outbound_mail(request, sender)
    if delivery.status != "sent":
        _complete_action(
            action_repository=action_repository,
            action=action,
            status="failed",
            now=now,
            failure_code=f"delivery_{delivery.status}",
        )
        return "failed"
    _complete_action(
        action_repository=action_repository,
        action=action,
        status="sent",
        now=delivery.sent_at or _now(),
        provider_name=delivery.provider_name,
        provider_message_id=delivery.provider_message_id,
    )
    return "sent"


class _IgnoringReservedActionRepository:
    """View used for the immediate pre-send recheck of one reserved action."""

    def __init__(self, repository: AutomationActionRepository, ignored_key: str) -> None:
        self.repository = repository
        self.ignored_key = ignored_key

    def get(self, action_key: str):
        if action_key == self.ignored_key:
            return None
        return self.repository.get(action_key)

    def reserve(self, action):
        return self.repository.reserve(action)

    def save(self, action):
        return self.repository.save(action)

    def list_all(self):
        return self.repository.list_all()


def _run_customer_action(
    *,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    workflow: SupplierRFQWorkflow,
    sender: OutboundMailSender | None,
    now: datetime,
    mina_job_repository: MinaJobRepository | None = None,
) -> str:
    with atomic_repository_transaction(supplier_repository, action_repository):
        current_workflow = supplier_repository.get_workflow(workflow.workflow_id)
        if current_workflow is None:
            return "skipped"
        plan = customer_deadline_plan(
            supplier_repository=supplier_repository,
            action_repository=action_repository,
            workflow=current_workflow,
            now=now,
            mina_job_repository=mina_job_repository,
        )
        if plan.get("state") != "automatic_customer_update_due":
            return "skipped"
        action = _reserve_action(
            action_repository=action_repository,
            action_key=plan["action_key"],
            action_type="customer_deadline_update",
            workflow_id=current_workflow.workflow_id,
            resource_id=current_workflow.workflow_id,
            due_at=plan["due_at"],
            now=now,
        )
    if action is None:
        return "skipped"

    current_workflow = supplier_repository.get_workflow(workflow.workflow_id)
    if current_workflow is None:
        _complete_action(
            action_repository=action_repository,
            action=action,
            status="cancelled",
            now=now,
            failure_code="resource_missing_before_send",
        )
        return "cancelled"
    pre_send_plan = customer_deadline_plan(
        supplier_repository=supplier_repository,
        action_repository=_IgnoringReservedActionRepository(action_repository, action.action_key),
        workflow=current_workflow,
        now=now,
        mina_job_repository=mina_job_repository,
    )
    if pre_send_plan.get("state") != "automatic_customer_update_due":
        _complete_action(
            action_repository=action_repository,
            action=action,
            status="cancelled",
            now=now,
            failure_code="state_changed_before_send",
        )
        return "cancelled"

    request = build_customer_deadline_update_request(
        workflow=current_workflow,
        action_key=action.action_key,
    )
    delivery = dispatch_outbound_mail(request, sender)
    if delivery.status != "sent":
        _complete_action(
            action_repository=action_repository,
            action=action,
            status="failed",
            now=now,
            failure_code=f"delivery_{delivery.status}",
        )
        return "failed"
    _complete_action(
        action_repository=action_repository,
        action=action,
        status="sent",
        now=delivery.sent_at or _now(),
        provider_name=delivery.provider_name,
        provider_message_id=delivery.provider_message_id,
    )
    return "sent"


def run_automation_tick(
    *,
    supplier_repository: SupplierRFQRepository,
    action_repository: AutomationActionRepository,
    sender: OutboundMailSender | None,
    mina_job_repository: MinaJobRepository | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = aware_utc(now or _now())
    counts = {"sent": 0, "failed": 0, "cancelled": 0, "skipped": 0}
    for draft in supplier_repository.list_drafts():
        outcome = _run_supplier_action(
            supplier_repository=supplier_repository,
            action_repository=action_repository,
            draft=draft,
            sender=sender,
            now=current,
            mina_job_repository=mina_job_repository,
        )
        counts[outcome] = counts.get(outcome, 0) + 1
    for workflow in supplier_repository.list_workflows():
        outcome = _run_customer_action(
            supplier_repository=supplier_repository,
            action_repository=action_repository,
            workflow=workflow,
            sender=sender,
            now=current,
            mina_job_repository=mina_job_repository,
        )
        counts[outcome] = counts.get(outcome, 0) + 1
    return {"generated_at": current, "counts": counts}


class AutomationScheduler:
    def __init__(
        self,
        *,
        supplier_repository: SupplierRFQRepository,
        action_repository: AutomationActionRepository,
        sender: OutboundMailSender | None,
        mina_job_repository: MinaJobRepository | None = None,
        poll_seconds: int = DEFAULT_AUTOMATION_POLL_SECONDS,
    ) -> None:
        self.supplier_repository = supplier_repository
        self.action_repository = action_repository
        self.sender = sender
        self.mina_job_repository = mina_job_repository
        self.poll_seconds = max(5, int(poll_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_tick_at: datetime | None = None
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="minai-automation-scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=min(5, self.poll_seconds))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                run_automation_tick(
                    supplier_repository=self.supplier_repository,
                    action_repository=self.action_repository,
                    sender=self.sender,
                    mina_job_repository=self.mina_job_repository,
                )
                self._last_tick_at = _now()
                self._last_error = None
            except Exception:
                self._last_tick_at = _now()
                self._last_error = "automation_tick_failed_safely"
            self._stop.wait(self.poll_seconds)

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self._thread is not None and self._thread.is_alive()),
            "poll_seconds": self.poll_seconds,
            "last_tick_at": self._last_tick_at,
            "last_error": self._last_error,
        }
