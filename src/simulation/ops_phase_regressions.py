from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.automation_planning import supplier_reminder_plan
from src.core.automation_policy_service import resolve_effective_automation_policy
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.master_data import SupplierRelationshipSettings
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.mail import MailSendResult
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import (
    create_manual_mina_job, link_mina_job_quote_case, link_mina_job_workflow,
    transition_mina_job_stage,
)
from src.core.models import Shipment, SupplierQuote
from src.core.operation_start_repository import InMemoryOperationStartMessageRepository
from src.core.operation_start_service import decide_operation_start_message, start_operation
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    assign_operational_work_to_me, assign_operational_work_to_operator,
)
from src.core.performance_settings import default_performance_settings
from src.core.pilot_access import route_allowed
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_quote_selection import (
    RejectedSupplierQuoteAlternative, SupplierQuoteSelectionDecision,
)
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_learning_service import derive_supplier_history_learning
from src.simulation.operational_work_assignment_regressions import _args
from src.simulation.operational_work_queue_regressions import NOW as WORK_NOW, _fixture

NOW = datetime(2026, 9, 7, 10, 0, tzinfo=timezone.utc)


class _Sender:
    def __init__(self):
        self.requests = []
    def send(self, request):
        self.requests.append(request)
        return MailSendResult(
            operation_id=request.operation_id, status="sent", reason="synthetic success",
            provider_name="synthetic", provider_message_id=f"msg-{len(self.requests)}", sent_at=NOW,
        )


def _shipment():
    return Shipment(
        customer_name="Small Agency Customer", pickup_city="Adana", pickup_country="Türkiye", pickup_address="Adana OSB 4. Cadde No:10",
        pickup_contact_name="Ayşe Yılmaz", pickup_contact_phone="+90 555 000 00 00",
        delivery_city="Munich", delivery_country="Almanya", transport_mode="road",
        equipment_type="Tenteli", commodity="Tekstil", gross_weight_kg=20000,
        cargo_ready_date="2026-09-08", required_delivery_date="2026-09-12",
        is_adr=False, is_temperature_controlled=False, is_high_value=False,
    )


def _operation_case():
    jobs = InMemoryMinaJobRepository(); rfqs = InMemorySupplierRFQRepository(); cases = InMemoryQuoteCaseRepository()
    masters = InMemoryMasterDataRepository(); messages = InMemoryOperationStartMessageRepository()
    job = create_manual_mina_job(
        repository=jobs, manual_intake_id="ops-phase-1", intake_channel="phone",
        job_kind="price_request", shipment=_shipment(), opened_by="Ops One", opened_at=NOW-timedelta(hours=3),
    )
    workflow = SupplierRFQWorkflow(
        shipment=job.shipment, mina_job_id=job.job_id, mina_code=job.mina_code,
        automation_timing_version=1, created_at=NOW-timedelta(hours=2), updated_at=NOW-timedelta(hours=2),
    )
    selected = SupplierRFQDraft(
        workflow_id=workflow.workflow_id, supplier_name="Primary Road", priority=1,
        recipient_email="primary@example.invalid", subject="RFQ", body="quote", status="awaiting_response",
        created_at=NOW-timedelta(hours=2), sent_at=NOW-timedelta(hours=2),
    )
    alternative = SupplierRFQDraft(
        workflow_id=workflow.workflow_id, supplier_name="Alternative Road", priority=2,
        recipient_email="alternative@example.invalid", subject="RFQ", body="quote", status="awaiting_response",
        created_at=NOW-timedelta(hours=2), sent_at=NOW-timedelta(hours=2),
    )
    workflow = workflow.model_copy(update={"rfq_ids":[selected.rfq_id, alternative.rfq_id]})
    rfqs.save_workflow(workflow); rfqs.save_drafts([selected, alternative])
    rfqs.save_responses([
        SupplierRFQResponse(rfq_id=selected.rfq_id, supplier_name=selected.supplier_name, rfq_priority=1,
            status="quoted", cost=2200, currency="EUR", received_at=NOW-timedelta(minutes=80), source="email"),
        SupplierRFQResponse(rfq_id=alternative.rfq_id, supplier_name=alternative.supplier_name, rfq_priority=2,
            status="quoted", cost=2300, currency="EUR", received_at=NOW-timedelta(minutes=70), source="email"),
    ])
    for idx, draft in enumerate([selected, alternative], start=1):
        create_supplier_master(
            repository=masters, entry_id=f"supplier-{idx}", supplier_name=draft.supplier_name,
            contacts=[{"contact_name":"Ops", "email":draft.recipient_email, "roles":["operations"], "is_primary":True}],
            relationship=SupplierRelationshipSettings(
                supplier_reminder_mode="manual" if idx == 1 else None,
                first_reminder_minutes=90 if idx == 1 else None,
                operation_email_mode="approval_required", closure_email_mode="approval_required",
                preferred_contact_channels=["email","phone"],
            ),
            updated_by="Ops One", created_at=NOW-timedelta(days=1),
        )
    job = link_mina_job_workflow(repository=jobs, job_id=job.job_id, workflow_id=workflow.workflow_id,
        result_type="supplier_rfq_workflow", occurred_at=NOW-timedelta(hours=2))
    decision = SupplierQuoteSelectionDecision(
        selected_supplier=selected.supplier_name, selected_rfq_id=selected.rfq_id,
        selected_total_score=.91, selection_reason="Best controlled score",
        rejected_alternatives=[RejectedSupplierQuoteAlternative(
            rfq_id=alternative.rfq_id, supplier_name=alternative.supplier_name,
            cost=2300, currency="EUR", total_score=.84, score_difference=.07,
            rejection_reason="Lower score",
        )],
    )
    case = QuoteCase(
        shipment=job.shipment, mina_job_id=job.job_id, mina_code=job.mina_code,
        supplier_rfq_workflow_id=workflow.workflow_id,
        supplier_quote_selection_decision=decision,
        supplier_quote=SupplierQuote(supplier_name=selected.supplier_name, cost=2200, currency="EUR"),
    )
    cases.save(case); job = link_mina_job_quote_case(repository=jobs, job_id=job.job_id, quote_case_id=case.case_id, occurred_at=NOW-timedelta(hours=1))
    job = transition_mina_job_stage(repository=jobs, mina_code=job.mina_code, target_stage="quote_sent", actor="Ops One", occurred_at=NOW-timedelta(minutes=50))
    job = transition_mina_job_stage(repository=jobs, mina_code=job.mina_code, target_stage="accepted", actor="Ops One", occurred_at=NOW-timedelta(minutes=10))
    return jobs, rfqs, cases, masters, messages, job, selected, alternative


def evaluate_ops_phase_regressions() -> dict:
    failures, passes = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    jobs, rfqs, cases, masters, messages, job, selected, alternative = _operation_case()
    policy = resolve_effective_automation_policy(
        action="supplier_reminder", legacy_dispatch_enabled=True,
        mina_job_repository=jobs, job_id=job.job_id, master_data_repository=masters,
        supplier_name=selected.supplier_name,
    )
    check(policy.effective_mode == "manual" and policy.resolved_from == "supplier",
          "supplier-specific reminder policy overrides broader defaults")

    action_repo = InMemoryAutomationActionRepository()
    pre_accept_job = jobs.get(job.job_id).model_copy(update={"stage":"pricing"})
    jobs.save(pre_accept_job)
    no_response = SupplierRFQDraft(
        workflow_id=selected.workflow_id, supplier_name=selected.supplier_name, priority=3,
        recipient_email=selected.recipient_email, subject="RFQ 2", body="quote again",
        status="awaiting_response", created_at=NOW-timedelta(minutes=70), sent_at=NOW-timedelta(minutes=60),
    )
    rfqs.save_drafts([no_response])
    plan = supplier_reminder_plan(
        supplier_repository=rfqs, action_repository=action_repo, draft=no_response, now=NOW,
        mina_job_repository=jobs, master_data_repository=masters,
    )
    check(plan.get("due_at") == no_response.sent_at.replace(tzinfo=timezone.utc) + timedelta(minutes=90),
          "supplier profile can override first reminder timing")
    phone_only = InMemoryMasterDataRepository()
    create_supplier_master(
        repository=phone_only, entry_id="phone-only-supplier", supplier_name=selected.supplier_name,
        contacts=[{"contact_name":"Ops", "email":selected.recipient_email, "roles":["operations"], "is_primary":True}],
        relationship=SupplierRelationshipSettings(
            preferred_contact_channels=["phone"], max_email_reminders=1, first_reminder_minutes=5,
        ),
        updated_by="Ops One", created_at=NOW-timedelta(days=1),
    )
    phone_plan = supplier_reminder_plan(
        supplier_repository=rfqs, action_repository=InMemoryAutomationActionRepository(),
        draft=no_response, now=NOW, master_data_repository=phone_only,
    )
    check(
        phone_plan.get("state") == "human_contact_required"
        and phone_plan.get("reason") == "supplier_email_reminders_disabled",
        "supplier profile can bypass reminder email when email is not a preferred channel",
    )
    jobs.save(job)

    sender = _Sender()
    view = start_operation(
        mina_repository=jobs, quote_case_repository=cases, supplier_repository=rfqs,
        master_repository=masters, message_repository=messages, sender=sender,
        job_id=job.job_id, actor="Ops One", now=NOW,
    )
    selected_message = next(m for m in messages.list_for_job(job.job_id) if m.kind == "selected_supplier_confirmation")
    closure_message = next(m for m in messages.list_for_job(job.job_id) if m.kind == "supplier_closure")
    check(
        len(view["messages"]) == 2 and jobs.get(job.job_id).stage == "operation_opened"
        and "teklif kabul edilmiştir" in selected_message.body_text.casefold()
        and "plaka" in selected_message.body_text.casefold()
        and "adana osb 4. cadde no:10" in selected_message.body_text.casefold()
        and "ayşe yılmaz" in selected_message.body_text.casefold()
        and "teklifiniz için teşekkür" in closure_message.body_text.casefold(),
        "operation start prepares selected-supplier pickup confirmation and courteous quoted-supplier closure",
    )
    sent = decide_operation_start_message(
        repository=messages, mina_repository=jobs, sender=sender,
        message_id=selected_message.message_id, decision="approve", actor="Ops One", now=NOW,
    )
    post_plan = supplier_reminder_plan(
        supplier_repository=rfqs, action_repository=action_repo, draft=alternative, now=NOW,
        mina_job_repository=jobs, master_data_repository=masters,
    )
    check(sent.status == "sent" and jobs.get(job.job_id).stage == "supplier_confirmation_pending"
          and post_plan.get("state") == "procurement_closed",
          "selected supplier send advances operation and closes procurement reminder tracking")

    jobs_race, rfqs_race, cases_race, masters_race, messages_race, job_race, _, _ = _operation_case()
    start_operation(
        mina_repository=jobs_race, quote_case_repository=cases_race, supplier_repository=rfqs_race,
        master_repository=masters_race, message_repository=messages_race, sender=None,
        job_id=job_race.job_id, actor="Ops One", now=NOW,
    )
    race_message = next(m for m in messages_race.list_for_job(job_race.job_id) if m.kind == "selected_supplier_confirmation")
    race_sender = _Sender()
    def decide_once():
        try:
            return decide_operation_start_message(
                repository=messages_race, mina_repository=jobs_race, sender=race_sender,
                message_id=race_message.message_id, decision="approve", actor="Ops One", now=NOW,
            ).status
        except Exception as exc:
            return type(exc).__name__
    with ThreadPoolExecutor(max_workers=2) as pool:
        race_results = list(pool.map(lambda _: decide_once(), range(2)))
    check(
        len(race_sender.requests) == 1
        and messages_race.get(race_message.message_id).status == "sent"
        and any(result == "sent" for result in race_results),
        "concurrent operation-start approval reserves one provider send",
    )

    learning = InMemoryLearningFactRepository()
    derived = derive_supplier_history_learning(
        supplier_id=masters.find_supplier_by_name(selected.supplier_name).supplier_id,
        master_repository=masters, supplier_repository=rfqs, learning_repository=learning,
        created_by="Ops One", occurred_at=NOW,
    )
    check(derived["proposed_facts"] and all(f.status == "proposed" for f in learning.list_all()),
          "supplier history learning stays proposed until human confirmation")

    attachments, proposals, suppliers2, approvals, cases2 = _fixture()
    assignments = InMemoryOperationalWorkAssignmentRepository()
    queue_args = _args(assignments, attachments, proposals, suppliers2, approvals, cases2)
    from src.core.operational_work_queue import build_operational_work_queue
    q = build_operational_work_queue(
        attachment_repository=attachments, proposal_repository=proposals, supplier_repository=suppliers2,
        approval_repository=approvals, quote_case_repository=cases2, now=WORK_NOW,
    )
    work_id = next(item["work_id"] for item in q["items"] if item["resource_id"] == "proposal-human")
    first = assign_operational_work_to_me(work_id=work_id, operator_name="Ops A", now=WORK_NOW, **queue_args)
    directed = assign_operational_work_to_operator(
        work_id=work_id, target_operator_name="Ops B", assigned_by="Ops A",
        reason="load balance", now=WORK_NOW+timedelta(seconds=5), **queue_args,
    )
    check(directed.generation == first.generation + 1 and directed.assigned_to == "Ops B"
          and directed.assigned_by == "Ops A" and directed.reassigned_from == "Ops A",
          "directed operator reassignment preserves explicit audit generation")

    defaults = default_performance_settings()
    check(defaults.first_look_target_minutes == 15 and defaults.decision_target_minutes == 15,
          "small-agency performance defaults use simple configurable 15-minute targets")

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    css = (root / "ui" / "web_shell" / "app.css").read_text(encoding="utf-8")
    checks = [
        "/operation-start" in js and "Yük onayı + toplama" in js,
        "/operational-work-items/${encodeURIComponent(item.work_id)}/assign" in js and "/operators" in js,
        "Müşteri İstisnaları" in js and "/automation-policy" in js,
        "MINAI Geçmiş Gözlemleri" in js and "/derive-learning" in js,
        "Performans Hedeflerini Kaydet" in js and "P90" in js,
        ".supplier-relationship-form" in css and ".direct-assign" in css,
        "window.prompt" not in js and "localStorage" not in js and "sessionStorage" not in js,
    ]
    check(all(checks), "pilot browser exposes the agreed simple-agency workflows without unsafe browser state")
    controlled_routes = [
        ("GET", "/operators"),
        ("GET", "/settings/performance"), ("POST", "/settings/performance"),
        ("POST", "/master-data/customers/customer-1/automation-policy"),
        ("POST", "/master-data/suppliers/supplier-1/derive-learning"),
        ("GET", "/mina-jobs/job-1/operation-start"), ("POST", "/mina-jobs/job-1/operation-start"),
        ("POST", "/operation-start-messages/message-1/decision"),
        ("POST", "/operation-start-messages/message-1/record-manually-sent"),
        ("POST", "/operational-work-items/work-1/assign"),
    ]
    check(
        all(route_allowed(method, path) for method, path in controlled_routes)
        and not route_allowed("DELETE", "/settings/performance")
        and not route_allowed("POST", "/operators"),
        "new browser workflow routes stay bounded by the controlled pilot allowlist",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_ops_phase_regressions()
    for label in result["passes"]: print(f"PASS {label}")
    for label in result["failures"]: print(f"FAIL {label}")
    print("\nOps phase regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
