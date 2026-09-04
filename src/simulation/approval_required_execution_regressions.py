from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from starlette.requests import Request

from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.automation_approval_service import (
    AutomationApprovalError,
    decide_customer_deadline_update_approval,
    decide_supplier_reminder_approval,
    preview_customer_deadline_update_approval,
    preview_supplier_reminder_approval,
)
from src.core.automation_planning import customer_deadline_plan, supplier_reminder_plan
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import MailSendResult
from src.core.master_data_service import update_customer_master
from src.core.mina_job_actions import MinaJobActionError, send_supplier_reminder_now
from src.core.operational_work_queue import build_operational_work_queue
from src.core.pilot_access import route_allowed
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq import SupplierRFQResponse
from src.simulation.automation_policy_hierarchy_regressions import NOW, _case
from src.workflow.automation_scheduler import run_automation_tick


class _Sender:
    def __init__(self, status: str = "sent") -> None:
        self.status = status
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        if self.status != "sent":
            return MailSendResult(
                operation_id=request.operation_id,
                status=self.status,
                reason="synthetic controlled failure",
            )
        return MailSendResult(
            operation_id=request.operation_id,
            status="sent",
            reason="synthetic success",
            provider_name="synthetic",
            provider_message_id=f"approval-message-{len(self.requests)}",
            sent_at=NOW,
        )


def _approval_case(action_repo=None):
    (
        job_repo,
        supplier_repo,
        default_actions,
        master_repo,
        agency_repo,
        job,
        customer,
        workflow,
        draft,
    ) = _case()
    actions = action_repo or default_actions
    update_customer_master(
        repository=master_repo,
        customer_id=customer.customer_id,
        updated_by="Manager",
        occurred_at=NOW - timedelta(seconds=1),
        supplier_reminder_mode="approval_required",
        customer_deadline_update_mode="approval_required",
    )
    return (
        job_repo, supplier_repo, actions, master_repo, agency_repo,
        job, workflow, draft,
    )


def _queue(job_repo, supplier_repo, actions, master_repo, agency_repo):
    return build_operational_work_queue(
        attachment_repository=InMemoryAttachmentInterpretationReviewRepository(),
        proposal_repository=InMemoryExtractionProposalRepository(),
        supplier_repository=supplier_repo,
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        automation_action_repository=actions,
        mina_job_repository=job_repo,
        master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
        now=NOW,
    )


def evaluate_approval_required_execution_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    (
        job_repo, supplier_repo, actions, master_repo, agency_repo,
        job, workflow, draft,
    ) = _approval_case()
    supplier_preview = preview_supplier_reminder_approval(
        mina_job_repository=job_repo,
        supplier_repository=supplier_repo,
        action_repository=actions,
        master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
        job_id=job.job_id,
        rfq_id=draft.rfq_id,
        now=NOW,
    )
    customer_preview = preview_customer_deadline_update_approval(
        mina_job_repository=job_repo,
        supplier_repository=supplier_repo,
        action_repository=actions,
        master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
        job_id=job.job_id,
        now=NOW,
    )
    check(
        supplier_preview["decision_required"] is True
        and customer_preview["decision_required"] is True
        and supplier_preview["body_text"]
        and customer_preview["body_text"]
        and not actions.list_all(),
        "approval previews are read-only and do not reserve or send actions",
    )

    scheduler_sender = _Sender()
    tick = run_automation_tick(
        supplier_repository=supplier_repo,
        action_repository=actions,
        sender=scheduler_sender,
        mina_job_repository=job_repo,
        master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
        now=NOW,
    )
    check(
        not scheduler_sender.requests and tick["counts"].get("sent", 0) == 0,
        "automatic scheduler never executes approval-required outbound work",
    )

    sender = _Sender()
    supplier_result = decide_supplier_reminder_approval(
        mina_job_repository=job_repo,
        supplier_repository=supplier_repo,
        action_repository=actions,
        master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
        sender=sender,
        job_id=job.job_id,
        rfq_id=draft.rfq_id,
        decision="approve",
        actor="Ops One",
        now=NOW,
    )
    supplier_action = supplier_result["automation_action"]
    check(
        len(sender.requests) == 1
        and supplier_action.status == "sent"
        and supplier_action.trigger_mode == "operator_approved"
        and supplier_action.triggered_by_operator == "Ops One"
        and any(
            event.event_type == "supplier_reminder_approved_sent"
            and event.actor == "Ops One"
            for event in job_repo.list_events(job.job_id)
        ),
        "supplier approval records authenticated evidence and sends exactly once",
    )
    duplicate_blocked = False
    try:
        decide_supplier_reminder_approval(
            mina_job_repository=job_repo,
            supplier_repository=supplier_repo,
            action_repository=actions,
            master_data_repository=master_repo,
            agency_policy_repository=agency_repo,
            sender=sender,
            job_id=job.job_id,
            rfq_id=draft.rfq_id,
            decision="approve",
            actor="Ops One",
            now=NOW,
        )
    except AutomationApprovalError:
        duplicate_blocked = True
    check(
        duplicate_blocked and len(sender.requests) == 1,
        "decided supplier approval cannot be executed twice",
    )

    customer_result = decide_customer_deadline_update_approval(
        mina_job_repository=job_repo,
        supplier_repository=supplier_repo,
        action_repository=actions,
        master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
        sender=sender,
        job_id=job.job_id,
        decision="approve",
        actor="Ops One",
        now=NOW,
    )
    check(
        len(sender.requests) == 2
        and customer_result["automation_action"].status == "sent"
        and sender.requests[-1].purpose == "customer_status_update"
        and any(
            event.event_type == "customer_deadline_update_approved_sent"
            for event in job_repo.list_events(job.job_id)
        ),
        "customer deadline approval uses the same explicit approve-and-send boundary",
    )

    (
        reject_jobs, reject_supplier, reject_actions, reject_master, reject_agency,
        reject_job, reject_workflow, reject_draft,
    ) = _approval_case()
    reject_sender = _Sender()
    rejected = decide_supplier_reminder_approval(
        mina_job_repository=reject_jobs,
        supplier_repository=reject_supplier,
        action_repository=reject_actions,
        master_data_repository=reject_master,
        agency_policy_repository=reject_agency,
        sender=reject_sender,
        job_id=reject_job.job_id,
        rfq_id=reject_draft.rfq_id,
        decision="reject",
        actor="Ops Reject",
        reason="Telefonla takip edeceğim.",
        now=NOW,
    )
    rejected_plan = supplier_reminder_plan(
        supplier_repository=reject_supplier,
        action_repository=reject_actions,
        draft=reject_draft,
        now=NOW,
        mina_job_repository=reject_jobs,
        master_data_repository=reject_master,
        agency_policy_repository=reject_agency,
    )
    rejected_queue = _queue(
        reject_jobs, reject_supplier, reject_actions, reject_master, reject_agency
    )
    check(
        not reject_sender.requests
        and rejected["automation_action"].status == "cancelled"
        and rejected["automation_action"].failure_code == "operator_rejected"
        and rejected_plan["state"] == "approval_rejected_no_send"
        and not any(
            item["next_action"] == "review_and_approve_supplier_reminder"
            for item in rejected_queue["items"]
        ),
        "rejected supplier action is durable no-send evidence and is not re-proposed",
    )

    reject_reason_required = False
    (
        rr_jobs, rr_supplier, rr_actions, rr_master, rr_agency,
        rr_job, rr_workflow, rr_draft,
    ) = _approval_case()
    try:
        decide_customer_deadline_update_approval(
            mina_job_repository=rr_jobs,
            supplier_repository=rr_supplier,
            action_repository=rr_actions,
            master_data_repository=rr_master,
            agency_policy_repository=rr_agency,
            sender=_Sender(),
            job_id=rr_job.job_id,
            decision="reject",
            actor="Ops Reject",
            now=NOW,
        )
    except ValueError:
        reject_reason_required = True
    check(
        reject_reason_required and not rr_actions.list_all(),
        "reject requires an explicit bounded reason before durable decision evidence",
    )
    customer_rejected = decide_customer_deadline_update_approval(
        mina_job_repository=rr_jobs,
        supplier_repository=rr_supplier,
        action_repository=rr_actions,
        master_data_repository=rr_master,
        agency_policy_repository=rr_agency,
        sender=_Sender(),
        job_id=rr_job.job_id,
        decision="reject",
        actor="Ops Reject",
        reason="Müşteriyi telefonla bilgilendireceğim.",
        now=NOW,
    )
    customer_rejected_plan = customer_deadline_plan(
        supplier_repository=rr_supplier,
        action_repository=rr_actions,
        workflow=rr_workflow,
        now=NOW,
        mina_job_repository=rr_jobs,
        master_data_repository=rr_master,
        agency_policy_repository=rr_agency,
    )
    check(
        customer_rejected["automation_action"].status == "cancelled"
        and customer_rejected["automation_action"].failure_code == "operator_rejected"
        and customer_rejected_plan["state"] == "approval_rejected_no_send"
        and any(
            event.event_type == "customer_deadline_update_rejected"
            for event in rr_jobs.list_events(rr_job.job_id)
        ),
        "rejected customer deadline update is durable no-send evidence and is not re-proposed",
    )

    (
        fail_jobs, fail_supplier, fail_actions, fail_master, fail_agency,
        fail_job, fail_workflow, fail_draft,
    ) = _approval_case()
    fail_sender = _Sender("failed")
    failed = decide_supplier_reminder_approval(
        mina_job_repository=fail_jobs,
        supplier_repository=fail_supplier,
        action_repository=fail_actions,
        master_data_repository=fail_master,
        agency_policy_repository=fail_agency,
        sender=fail_sender,
        job_id=fail_job.job_id,
        rfq_id=fail_draft.rfq_id,
        decision="approve",
        actor="Ops Failure",
        now=NOW,
    )
    run_automation_tick(
        supplier_repository=fail_supplier,
        action_repository=fail_actions,
        sender=fail_sender,
        mina_job_repository=fail_jobs,
        master_data_repository=fail_master,
        agency_policy_repository=fail_agency,
        now=NOW,
    )
    check(
        failed["automation_action"].status == "failed"
        and len(fail_sender.requests) == 1,
        "approved provider failure is durable attention and is never blindly retried",
    )

    class _InjectResponseOnReserve(InMemoryAutomationActionRepository):
        def __init__(self, supplier_repository, rfq_id):
            super().__init__()
            self.supplier_repository = supplier_repository
            self.rfq_id = rfq_id
            self.injected = False

        def reserve(self, action):
            reserved = super().reserve(action)
            if reserved and action.status == "reserved" and not self.injected:
                self.injected = True
                current_draft = self.supplier_repository.get_draft(self.rfq_id)
                self.supplier_repository.save_responses([
                    SupplierRFQResponse(
                        rfq_id=current_draft.rfq_id,
                        supplier_name=current_draft.supplier_name,
                        rfq_priority=current_draft.priority,
                        status="no_capacity",
                        received_at=NOW,
                    )
                ])
                self.supplier_repository.save_drafts([
                    current_draft.model_copy(update={"status": "responded", "responded_at": NOW})
                ])
            return reserved

    (
        race_jobs, race_supplier, _, race_master, race_agency,
        race_job, race_workflow, race_draft,
    ) = _approval_case()
    race_actions = _InjectResponseOnReserve(race_supplier, race_draft.rfq_id)
    race_sender = _Sender()
    stale_cancelled = False
    try:
        decide_supplier_reminder_approval(
            mina_job_repository=race_jobs,
            supplier_repository=race_supplier,
            action_repository=race_actions,
            master_data_repository=race_master,
            agency_policy_repository=race_agency,
            sender=race_sender,
            job_id=race_job.job_id,
            rfq_id=race_draft.rfq_id,
            decision="approve",
            actor="Ops Race",
            now=NOW,
        )
    except AutomationApprovalError:
        stale_cancelled = True
    race_action = race_actions.list_all()[0]
    check(
        stale_cancelled
        and not race_sender.requests
        and race_action.status == "cancelled"
        and race_action.failure_code == "state_changed_before_approved_send",
        "supplier response arriving after approval reservation cancels stale provider send",
    )

    import src.api as api
    original = (
        api.mina_job_repository,
        api.supplier_rfq_repository,
        api.automation_action_repository,
        api.master_data_repository,
        api.agency_automation_policy_repository,
        api.outbound_mail_sender,
    )
    (
        api_jobs, api_supplier, api_actions, api_master, api_agency,
        api_job, api_workflow, api_draft,
    ) = _approval_case()
    api_sender = _Sender()
    api.mina_job_repository = api_jobs
    api.supplier_rfq_repository = api_supplier
    api.automation_action_repository = api_actions
    api.master_data_repository = api_master
    api.agency_automation_policy_repository = api_agency
    api.outbound_mail_sender = api_sender
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Operator"
    bypass_blocked = False
    try:
        try:
            api.send_mina_job_supplier_reminder_now(
                api_job.job_id, api_draft.rfq_id, request
            )
        except HTTPException as exc:
            bypass_blocked = exc.status_code == 409
    finally:
        (
            api.mina_job_repository,
            api.supplier_rfq_repository,
            api.automation_action_repository,
            api.master_data_repository,
            api.agency_automation_policy_repository,
            api.outbound_mail_sender,
        ) = original
    check(
        bypass_blocked and not api_sender.requests and not api_actions.list_all(),
        "legacy reminder-now API cannot bypass approval-required policy",
    )

    (
        flip_jobs, flip_supplier, _, flip_master, flip_agency,
        flip_job, flip_customer, flip_workflow, flip_draft,
    ) = _case()

    class _FlipPolicyOnReserve(InMemoryAutomationActionRepository):
        def __init__(self):
            super().__init__()
            self.flipped = False

        def reserve(self, action):
            reserved = super().reserve(action)
            if reserved and not self.flipped:
                self.flipped = True
                update_customer_master(
                    repository=flip_master,
                    customer_id=flip_customer.customer_id,
                    updated_by="Manager",
                    occurred_at=NOW,
                    supplier_reminder_mode="approval_required",
                )
            return reserved

    flip_actions = _FlipPolicyOnReserve()
    flip_sender = _Sender()
    flip_blocked = False
    try:
        send_supplier_reminder_now(
            mina_job_repository=flip_jobs,
            supplier_repository=flip_supplier,
            action_repository=flip_actions,
            sender=flip_sender,
            mina_code=flip_job.mina_code,
            rfq_id=flip_draft.rfq_id,
            actor="Ops Flip",
            master_data_repository=flip_master,
            agency_policy_repository=flip_agency,
            now=NOW,
        )
    except MinaJobActionError:
        flip_blocked = True
    check(
        flip_blocked
        and not flip_sender.requests
        and flip_actions.list_all()[0].status == "cancelled"
        and flip_actions.list_all()[0].failure_code == "state_changed_before_operator_send",
        "reminder-now rechecks policy after reservation and cannot race into approval-required send",
    )

    check(
        route_allowed("GET", "/mina-jobs/job-1/supplier-rfqs/rfq-1/reminder-approval-preview")
        and route_allowed("POST", "/mina-jobs/job-1/supplier-rfqs/rfq-1/reminder-approval")
        and route_allowed("GET", "/mina-jobs/job-1/customer-deadline-update/approval-preview")
        and route_allowed("POST", "/mina-jobs/job-1/customer-deadline-update/approval"),
        "pilot access explicitly allows only the controlled P2-08 approval surfaces",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_approval_required_execution_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nApproval-required execution regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
