from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.automation_planning import supplier_reminder_plan
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundMailEnvelope, MailSendResult
from src.core.mina_job import MinaJob
from src.core.mina_job_actions import MinaJobActionError, preview_supplier_reminder_now, send_supplier_reminder_now
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import (
    MinaJobTransitionError,
    allowed_next_stages,
    create_manual_mina_job,
    create_mina_job_for_confirmed_proposal,
    link_mina_job_quote_case,
    link_mina_job_workflow,
    record_mina_job_quote_revision,
    set_mina_job_automation_overrides,
    set_mina_job_owners,
    transition_mina_job_stage,
)
from src.core.mina_job_view import build_mina_job_detail
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.sqlite_repositories import SQLiteMinaJobRepository
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.automation_scheduler import run_automation_tick
from src.workflow.extraction_confirmation import create_extraction_proposal, confirm_extraction_proposal

NOW = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)


class _Sender:
    def __init__(self) -> None:
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return MailSendResult(
            operation_id=request.operation_id,
            status="sent",
            reason="synthetic success",
            provider_name="synthetic-provider",
            provider_message_id=f"message-{len(self.requests)}",
            sent_at=NOW,
        )


def _shipment(name: str = "Synthetic Customer") -> Shipment:
    return Shipment(
        customer_name=name,
        pickup_city="Adana",
        delivery_city="Munich",
        transport_mode="road",
        equipment_type="Tenteli",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
    )


def evaluate_mina_job_case_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    proposal_repo = InMemoryExtractionProposalRepository()
    job_repo = InMemoryMinaJobRepository()
    mail = InboundMailEnvelope(
        source="email",
        sender_address="customer@example.invalid",
        subject="Road quote",
        body_text="Adana Munich road quote",
        received_at=NOW - timedelta(minutes=5),
        external_message_id="mina-job-1",
    )
    proposed = create_extraction_proposal(
        mail=mail,
        proposed_shipment=ShipmentProposalSnapshot.model_validate(_shipment().model_dump()),
        repository=proposal_repo,
    )
    check(len(job_repo.list_all()) == 0, "unconfirmed mail does not consume a MINA job number")
    confirmed = confirm_extraction_proposal(
        repository=proposal_repo,
        proposal_id=proposed.proposal_id,
        operator_identity="Operator One",
        confirmed_at=NOW,
        mina_job_repository=job_repo,
    )
    first_job = job_repo.get(confirmed.mina_job_id)
    check(
        first_job is not None
        and first_job.mina_code == "MINA2026/1"
        and confirmed.mina_code == "MINA2026/1"
        and first_job.source_proposal_id == proposed.proposal_id,
        "confirmed genuine inquiry creates MINA2026/1 and links extraction",
    )
    same_job = create_mina_job_for_confirmed_proposal(
        repository=job_repo,
        proposal_id=proposed.proposal_id,
        shipment=confirmed.confirmed_shipment,
        opened_by="Operator One",
        opened_at=NOW,
    )
    second_job = create_mina_job_for_confirmed_proposal(
        repository=job_repo,
        proposal_id="proposal-2",
        shipment=_shipment("Second Customer"),
        opened_by="Operator One",
        opened_at=NOW + timedelta(minutes=1),
    )
    rollover_job = create_mina_job_for_confirmed_proposal(
        repository=job_repo,
        proposal_id="proposal-2027",
        shipment=_shipment("Next Year Customer"),
        opened_by="Operator One",
        opened_at=datetime(2027, 1, 2, 9, 0, tzinfo=timezone.utc),
    )
    check(
        same_job.job_id == first_job.job_id
        and second_job.mina_code == "MINA2026/2"
        and rollover_job.mina_code == "MINA2027/1",
        "MINA numbering is idempotent per inquiry and resets by Istanbul year",
    )

    manual_repo = InMemoryMinaJobRepository()
    manual_job = create_manual_mina_job(
        repository=manual_repo, manual_intake_id="phone-order-1",
        intake_channel="phone", job_kind="approved_job",
        shipment=_shipment("Approved Job Customer"), opened_by="Operator One",
        opened_at=NOW, sales_owner="Sales One", operations_owner="Ops One",
    )
    repeated_manual = create_manual_mina_job(
        repository=manual_repo, manual_intake_id="phone-order-1",
        intake_channel="phone", job_kind="approved_job",
        shipment=_shipment("Approved Job Customer"), opened_by="Operator One",
        opened_at=NOW, sales_owner="Sales One", operations_owner="Ops One",
    )
    manual_job = transition_mina_job_stage(
        repository=manual_repo, mina_code=manual_job.mina_code, target_stage="pricing",
        actor="Operator One", occurred_at=NOW + timedelta(minutes=1),
    )
    approved_allowed = allowed_next_stages(manual_job)
    try:
        transition_mina_job_stage(
            repository=manual_repo, mina_code=manual_job.mina_code, target_stage="quote_ready",
            actor="Operator One", occurred_at=NOW + timedelta(minutes=2),
        )
        approved_quote_blocked = False
    except MinaJobTransitionError:
        approved_quote_blocked = True
    manual_job = transition_mina_job_stage(
        repository=manual_repo, mina_code=manual_job.mina_code,
        target_stage="operation_opened", actor="Operator One",
        occurred_at=NOW + timedelta(minutes=2),
    )
    manual_job = set_mina_job_owners(
        repository=manual_repo, mina_code=manual_job.mina_code, actor="Manager One",
        sales_owner="Sales Two", operations_owner="Ops Two",
        occurred_at=NOW + timedelta(minutes=3),
    )
    manual_events = manual_repo.list_events(manual_job.job_id)
    check(
        repeated_manual.job_id == manual_job.job_id
        and manual_job.mina_code == "MINA2026/1"
        and manual_job.source_proposal_id is None
        and manual_job.manual_intake_id == "phone-order-1"
        and manual_job.job_kind == "approved_job"
        and manual_job.intake_channel == "phone"
        and "operation_opened" in approved_allowed
        and "quote_ready" not in approved_allowed
        and approved_quote_blocked
        and manual_job.stage == "operation_opened"
        and manual_job.sales_owner == "Sales Two"
        and manual_job.operations_owner == "Ops Two"
        and any(e.event_type == "job_sales_owner_changed" for e in manual_events)
        and any(e.event_type == "job_operations_owner_changed" for e in manual_events),
        "approved manual jobs are idempotent skip customer quote lifecycle and audit ownership",
    )

    legacy_payload = {
        "mina_code": "MINA2026/99", "sequence_year": 2026, "sequence_number": 99,
        "source_proposal_id": "legacy-proposal", "shipment": _shipment("Legacy Customer"),
        "stage": "delivered", "opened_by": "Legacy Operator",
        "opened_at": NOW, "updated_at": NOW, "closed_at": NOW,
    }
    legacy_job = MinaJob.model_validate(legacy_payload)
    check(
        legacy_job.lifecycle_version == 1 and legacy_job.is_closed
        and legacy_job.job_kind == "price_request" and legacy_job.intake_channel == "email",
        "persisted pre-P2-01 jobs deserialize as lifecycle v1 with delivered terminal",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "concurrent.sqlite3", retention_days=365)
        sqlite_jobs = SQLiteMinaJobRepository(store)
        barrier = threading.Barrier(2)
        codes: list[str] = []
        errors: list[str] = []

        def create_concurrent(index: int):
            try:
                barrier.wait()
                job = create_mina_job_for_confirmed_proposal(
                    repository=sqlite_jobs,
                    proposal_id=f"concurrent-{index}",
                    shipment=_shipment(f"Concurrent {index}"),
                    opened_by="Concurrent Operator",
                    opened_at=NOW,
                )
                codes.append(job.mina_code)
            except Exception as exc:
                errors.append(type(exc).__name__)
        threads = [threading.Thread(target=create_concurrent, args=(index,)) for index in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        check(
            not errors and sorted(codes) == ["MINA2026/1", "MINA2026/2"],
            "concurrent job creation reserves unique durable MINA numbers",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "mixed-concurrent.sqlite3", retention_days=365)
        mixed_jobs = SQLiteMinaJobRepository(store)
        barrier = threading.Barrier(2)
        mixed_codes: list[str] = []
        mixed_errors: list[str] = []

        def create_email_job():
            try:
                barrier.wait()
                job = create_mina_job_for_confirmed_proposal(
                    repository=mixed_jobs, proposal_id="mixed-email",
                    shipment=_shipment("Mixed Email"), opened_by="Operator One", opened_at=NOW,
                )
                mixed_codes.append(job.mina_code)
            except Exception as exc:
                mixed_errors.append(type(exc).__name__)

        def create_manual_job():
            try:
                barrier.wait()
                job = create_manual_mina_job(
                    repository=mixed_jobs, manual_intake_id="mixed-phone",
                    intake_channel="phone", job_kind="approved_job",
                    shipment=_shipment("Mixed Manual"), opened_by="Operator Two", opened_at=NOW,
                )
                mixed_codes.append(job.mina_code)
            except Exception as exc:
                mixed_errors.append(type(exc).__name__)

        threads = [threading.Thread(target=create_email_job), threading.Thread(target=create_manual_job)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        check(
            not mixed_errors and sorted(mixed_codes) == ["MINA2026/1", "MINA2026/2"],
            "email and manual intake share one concurrency-safe MINA sequence",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "ownership.sqlite3", retention_days=365)
        durable_jobs = SQLiteMinaJobRepository(store)
        durable_job = create_manual_mina_job(
            repository=durable_jobs, manual_intake_id="durable-owner",
            intake_channel="whatsapp", job_kind="approved_job",
            shipment=_shipment("Durable Owner"), opened_by="Operator One", opened_at=NOW,
            sales_owner="Sales One", operations_owner="Ops One",
        )
        durable_job = set_mina_job_owners(
            repository=durable_jobs, mina_code=durable_job.mina_code, actor="Manager One",
            sales_owner="Sales Durable", operations_owner="Ops Durable",
            occurred_at=NOW + timedelta(minutes=1),
        )
        reopened_jobs = SQLiteMinaJobRepository(store)
        reopened = reopened_jobs.get(durable_job.job_id)
        check(
            reopened is not None
            and reopened.sales_owner == "Sales Durable"
            and reopened.operations_owner == "Ops Durable"
            and len(reopened_jobs.list_events(durable_job.job_id)) >= 3,
            "job ownership and its audit trail survive SQLite repository reopen",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "retention.sqlite3", retention_days=1)
        persistent_jobs = SQLiteMinaJobRepository(store)
        persistent_job = create_mina_job_for_confirmed_proposal(
            repository=persistent_jobs,
            proposal_id="retention-proposal",
            shipment=_shipment("Persistent Customer"),
            opened_by="Operator One",
            opened_at=NOW,
        )
        store.upsert(
            namespace="temporary_test_state",
            record_key="old",
            payload={"value": 1},
            event_type="temporary_saved",
            entity_type="temporary",
        )
        store.purge_expired(now=NOW + timedelta(days=400))
        check(
            persistent_jobs.get(persistent_job.job_id) is not None
            and persistent_jobs.list_events(persistent_job.job_id)
            and store.get(namespace="temporary_test_state", record_key="old") is None,
            "MINA job and timeline survive pilot retention purge while ordinary state expires",
        )
    supplier_repo = InMemorySupplierRFQRepository()
    actions = InMemoryAutomationActionRepository()
    workflow = SupplierRFQWorkflow(
        workflow_id="wf-mina-1",
        shipment=first_job.shipment,
        mina_job_id=first_job.job_id,
        mina_code=first_job.mina_code,
        automation_timing_version=1,
        dispatch_policy=SupplierDispatchPolicy(),
    )
    draft = SupplierRFQDraft(
        rfq_id="rfq-mina-1",
        workflow_id=workflow.workflow_id,
        supplier_name="Synthetic Primary",
        priority=1,
        recipient_email="supplier@example.invalid",
        dispatch_tier="primary",
        subject="Synthetic RFQ",
        body="Synthetic RFQ body",
        status="awaiting_response",
        sent_at=NOW - timedelta(minutes=15),
    )
    supplier_repo.save_workflow(workflow)
    supplier_repo.save_drafts([draft])
    first_job = link_mina_job_workflow(
        repository=job_repo,
        job_id=first_job.job_id,
        workflow_id=workflow.workflow_id,
        result_type="supplier_rfq_approval_required",
        occurred_at=NOW,
    )
    first_job = set_mina_job_automation_overrides(
        repository=job_repo,
        mina_code=first_job.mina_code,
        actor="Operator One",
        disable_supplier_reminders=True,
        disable_customer_deadline_updates=False,
        occurred_at=NOW,
    )
    due_time = NOW + timedelta(minutes=15)
    disabled_plan = supplier_reminder_plan(
        supplier_repository=supplier_repo,
        action_repository=actions,
        draft=draft,
        now=due_time,
        mina_job_repository=job_repo,
    )
    check(
        disabled_plan.get("state") == "manual_reminder_due",
        "job-level supplier reminder override converts due automation into human work",
    )
    workflow_global_off = workflow.model_copy(update={
        "dispatch_policy": workflow.dispatch_policy.model_copy(update={
            "automatic_supplier_reminders_enabled": False,
        })
    })
    supplier_repo.save_workflow(workflow_global_off)
    set_mina_job_automation_overrides(
        repository=job_repo,
        mina_code=first_job.mina_code,
        actor="Operator One",
        disable_supplier_reminders=False,
        disable_customer_deadline_updates=False,
        occurred_at=NOW,
    )
    global_off_plan = supplier_reminder_plan(
        supplier_repository=supplier_repo,
        action_repository=actions,
        draft=draft,
        now=due_time,
        mina_job_repository=job_repo,
    )
    check(
        global_off_plan.get("state") == "manual_reminder_due",
        "job override cannot re-enable a globally disabled supplier reminder automation",
    )
    supplier_repo.save_workflow(workflow)

    preview = preview_supplier_reminder_now(
        mina_job_repository=job_repo,
        supplier_repository=supplier_repo,
        action_repository=actions,
        mina_code=first_job.mina_code,
        rfq_id=draft.rfq_id,
        now=NOW,
    )
    sender = _Sender()
    sent = send_supplier_reminder_now(
        mina_job_repository=job_repo,
        supplier_repository=supplier_repo,
        action_repository=actions,
        sender=sender,
        mina_code=first_job.mina_code,
        rfq_id=draft.rfq_id,
        actor="Operator One",
        now=NOW,
    )
    run_automation_tick(
        supplier_repository=supplier_repo,
        action_repository=actions,
        sender=sender,
        mina_job_repository=job_repo,
        now=due_time + timedelta(minutes=1),
    )
    action = actions.get(sent["automation_action"].action_key)
    check(
        preview["send_now_allowed"] is True
        and preview["planned_due_at"] == due_time
        and sent["sent_before_planned_due"] is True
        and action is not None
        and action.status == "sent"
        and action.trigger_mode == "operator_early"
        and action.triggered_by_operator == "Operator One"
        and len(sender.requests) == 1,
        "operator early reminder sends once and consumes the later scheduled reminder",
    )

    late_draft = draft.model_copy(update={"rfq_id": "rfq-mina-late"})
    supplier_repo.save_drafts([late_draft])
    try:
        send_supplier_reminder_now(
            mina_job_repository=job_repo,
            supplier_repository=supplier_repo,
            action_repository=actions,
            sender=sender,
            mina_code=first_job.mina_code,
            rfq_id=late_draft.rfq_id,
            actor="Operator One",
            now=datetime(2026, 9, 2, 19, 0, tzinfo=timezone.utc),
        )
        outside_hours_blocked = False
    except MinaJobActionError:
        outside_hours_blocked = True
    check(
        outside_hours_blocked and len(sender.requests) == 1,
        "operator early reminder still respects supplier communication hours",
    )

    quote_cases = InMemoryQuoteCaseRepository()
    quote_case = quote_cases.save(QuoteCase(
        shipment=first_job.shipment,
        mina_job_id=first_job.job_id,
        mina_code=first_job.mina_code,
        supplier_rfq_workflow_id=workflow.workflow_id,
    ))
    first_job = link_mina_job_quote_case(
        repository=job_repo,
        job_id=first_job.job_id,
        quote_case_id=quote_case.case_id,
        occurred_at=NOW + timedelta(minutes=20),
    )
    first_job = record_mina_job_quote_revision(
        repository=job_repo,
        job_id=first_job.job_id,
        actor="Operator One",
        revision_number=1,
        changed_fields=["final_price"],
        occurred_at=NOW + timedelta(minutes=25),
    )
    check(
        first_job.mina_code == "MINA2026/1"
        and first_job.quote_case_id == quote_case.case_id
        and any(event.event_type == "quote_revised" for event in job_repo.list_events(first_job.job_id)),
        "quote revisions remain inside the same MINA job and timeline",
    )
    detail = build_mina_job_detail(
        repository=job_repo,
        supplier_repository=supplier_repo,
        quote_case_repository=quote_cases,
        action_repository=actions,
        job_id=first_job.job_id,
        now=NOW + timedelta(minutes=26),
    )
    check(
        detail["summary"]["mina_code"] == "MINA2026/1"
        and detail["suppliers"][0]["rfq_id"] == "rfq-mina-1"
        and detail["quote"]["case_id"] == quote_case.case_id
        and any(item["event_type"] == "supplier_reminder_sent_early" for item in detail["timeline"]),
        "MINA job detail exposes stage supplier quote automation and durable timeline context",
    )

    current = first_job
    for target in (
        "quote_sent", "accepted", "operation_opened",
        "supplier_confirmation_pending", "vehicle_details_pending",
        "vehicle_assigned", "pre_loading_check", "ready_for_loading",
        "loaded", "in_transit", "delivery", "delivered",
    ):
        current = transition_mina_job_stage(
            repository=job_repo,
            mina_code=current.mina_code,
            target_stage=target,
            actor="Operator One",
            occurred_at=current.updated_at + timedelta(minutes=1),
        )
    check(
        current.stage == "delivered"
        and not current.is_closed
        and current.closed_at is None,
        "lifecycle v2 delivery remains open until POD CMR and closing review complete",
    )
    for target in ("pod_cmr_pending", "closing_review", "completed"):
        current = transition_mina_job_stage(
            repository=job_repo,
            mina_code=current.mina_code,
            target_stage=target,
            actor="Operator One",
            occurred_at=current.updated_at + timedelta(minutes=1),
        )
    try:
        set_mina_job_automation_overrides(
            repository=job_repo,
            mina_code=current.mina_code,
            actor="Operator One",
            disable_supplier_reminders=True,
            disable_customer_deadline_updates=True,
        )
        closed_override_blocked = False
    except MinaJobTransitionError:
        closed_override_blocked = True
    check(
        current.stage == "completed"
        and current.is_closed
        and current.closed_at is not None
        and closed_override_blocked,
        "lifecycle v2 completes only after POD CMR and closing review and then freezes overrides",
    )

    try:
        transition_mina_job_stage(
            repository=job_repo,
            mina_code=second_job.mina_code,
            target_stage="lost",
            actor="Operator One",
        )
        lost_reason_required = False
    except ValueError:
        lost_reason_required = True
    lost_job = transition_mina_job_stage(
        repository=job_repo,
        mina_code=second_job.mina_code,
        target_stage="lost",
        actor="Operator One",
        reason="Customer did not proceed with the shipment.",
        occurred_at=NOW + timedelta(hours=1),
    )
    check(
        lost_reason_required and lost_job.is_closed and lost_job.stage == "lost",
        "lost or cancelled work closes only with explicit human reason evidence",
    )

    from starlette.requests import Request
    from src import api
    api_jobs = InMemoryMinaJobRepository()
    api_suppliers = InMemorySupplierRFQRepository()
    api_quotes = InMemoryQuoteCaseRepository()
    api_actions = InMemoryAutomationActionRepository()
    api_job = create_mina_job_for_confirmed_proposal(
        repository=api_jobs, proposal_id="api-job-proposal",
        shipment=_shipment("API Customer"), opened_by="API Operator", opened_at=NOW,
    )
    original_api_repositories = (
        api.mina_job_repository, api.supplier_rfq_repository,
        api.quote_case_repository, api.automation_action_repository,
    )
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Operator"
    try:
        api.mina_job_repository = api_jobs
        api.supplier_rfq_repository = api_suppliers
        api.quote_case_repository = api_quotes
        api.automation_action_repository = api_actions
        api_list = api.list_mina_jobs()
        api_detail = api.get_mina_job(api_job.job_id)
        api_override = api.update_mina_job_automation_overrides(
            api_job.job_id,
            api.MinaJobAutomationOverrideRequest(
                disable_supplier_reminders=True,
                disable_customer_deadline_updates=False,
            ),
            request,
        )
        api_stage = api.update_mina_job_stage(
            api_job.job_id, api.MinaJobStageTransitionRequest(target_stage="pricing"), request
        )
        api_manual = api.create_manual_job(
            api.MinaJobManualCreateRequest(
                manual_intake_id="api-phone-1", job_kind="approved_job",
                intake_channel="phone", shipment=_shipment("API Manual Customer"),
                sales_owner="API Sales", operations_owner="API Ops",
            ),
            request,
        )
        api_owned = api.update_mina_job_owners(
            api_manual["job_id"],
            api.MinaJobOwnersRequest(
                sales_owner="API Sales Two", operations_owner="API Ops Two"
            ),
            request,
        )
    finally:
        (api.mina_job_repository, api.supplier_rfq_repository,
         api.quote_case_repository, api.automation_action_repository) = original_api_repositories
    check(
        api_list["jobs"][0]["mina_code"] == api_job.mina_code
        and api_detail["job"]["job_id"] == api_job.job_id
        and api_override["automation_overrides"]["disable_supplier_reminders"] is True
        and api_stage["stage"] == "pricing"
        and api_manual["job_kind"] == "approved_job"
        and api_manual["intake_channel"] == "phone"
        and api_owned["sales_owner"] == "API Sales Two"
        and api_owned["operations_owner"] == "API Ops Two",
        "MINA API list detail manual intake ownership and lifecycle use the durable job model",
    )

    check(
        route_allowed("GET", "/mina-jobs")
        and route_allowed("POST", "/mina-jobs/manual")
        and route_allowed("GET", "/mina-jobs/job-1")
        and route_allowed("POST", "/mina-jobs/job-1/automation-overrides")
        and route_allowed("POST", "/mina-jobs/job-1/owners")
        and route_allowed("POST", "/mina-jobs/job-1/stage")
        and route_allowed("GET", "/mina-jobs/job-1/supplier-rfqs/rfq-1/reminder-preview")
        and route_allowed("POST", "/mina-jobs/job-1/supplier-rfqs/rfq-1/reminder-now"),
        "pilot access explicitly allows the controlled MINA job API surface",
    )
    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_mina_job_case_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nMINA job/case regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
