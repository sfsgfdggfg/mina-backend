from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.requests import Request

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.automation_planning import customer_deadline_plan, supplier_reminder_plan
from src.core.automation_policy_repository import (
    InMemoryAgencyAutomationPolicyRepository,
    SQLiteAgencyAutomationPolicyRepository,
)
from src.core.automation_policy_service import (
    resolve_effective_automation_policy,
    save_agency_automation_policy,
)
from src.core.mail import MailSendResult
from src.core.master_data_repository import InMemoryMasterDataRepository, SQLiteMasterDataRepository
from src.core.master_data_service import create_customer_master, update_customer_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import (
    create_manual_mina_job,
    link_mina_job_workflow,
    set_mina_job_automation_overrides,
)
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.mina_job_view import build_mina_job_detail
from src.workflow.automation_scheduler import run_automation_tick

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


class _Sender:
    def __init__(self):
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        return MailSendResult(
            operation_id=request.operation_id,
            status="sent",
            reason="synthetic success",
            provider_name="synthetic",
            provider_message_id=f"message-{len(self.requests)}",
            sent_at=NOW,
        )


def _shipment(customer_name: str = "Beta Enerji") -> Shipment:
    return Shipment(
        customer_name=customer_name,
        pickup_city="Adana",
        pickup_country="Türkiye",
        delivery_city="Munich",
        delivery_country="Almanya",
        transport_mode="road",
        equipment_type="Tenteli / Curtainsider",
        customer_quote_deadline_at=NOW + timedelta(minutes=3),
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
    )


def _case():
    job_repo = InMemoryMinaJobRepository()
    supplier_repo = InMemorySupplierRFQRepository()
    action_repo = InMemoryAutomationActionRepository()
    master_repo = InMemoryMasterDataRepository()
    agency_repo = InMemoryAgencyAutomationPolicyRepository()
    job = create_manual_mina_job(
        repository=job_repo,
        manual_intake_id="policy-case-1",
        intake_channel="phone",
        job_kind="price_request",
        shipment=_shipment(),
        opened_by="Operator",
        opened_at=NOW - timedelta(hours=1),
    )
    customer = create_customer_master(
        repository=master_repo,
        entry_id="beta-master",
        customer_name="Beta Enerji",
        aliases=["Beta Energy"],
        updated_by="Operator",
        created_at=NOW - timedelta(hours=1),
    )
    policy = SupplierDispatchPolicy(
        automatic_supplier_reminders_enabled=True,
        automatic_customer_deadline_updates_enabled=True,
        no_response_reminder_minutes=30,
        customer_deadline_proactive_minutes=5,
    )
    workflow = SupplierRFQWorkflow(
        shipment=job.shipment,
        mina_job_id=job.job_id,
        mina_code=job.mina_code,
        sender_address="ops@beta.example",
        customer_subject="Road quote",
        automation_timing_version=1,
        dispatch_policy=policy,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW - timedelta(hours=1),
    )
    draft = SupplierRFQDraft(
        workflow_id=workflow.workflow_id,
        supplier_name="Anatolia Road",
        priority=1,
        recipient_email="pricing@anatolia.invalid",
        subject="RFQ",
        body="Please quote",
        status="awaiting_response",
        created_at=NOW - timedelta(minutes=45),
        sent_at=NOW - timedelta(minutes=40),
    )
    workflow = workflow.model_copy(update={"rfq_ids": [draft.rfq_id]})
    supplier_repo.save_workflow(workflow)
    supplier_repo.save_drafts([draft])
    job = link_mina_job_workflow(
        repository=job_repo,
        job_id=job.job_id,
        workflow_id=workflow.workflow_id,
        result_type="supplier_rfq_workflow",
        occurred_at=NOW - timedelta(minutes=44),
    )
    return job_repo, supplier_repo, action_repo, master_repo, agency_repo, job, customer, workflow, draft


def evaluate_automation_policy_hierarchy_regressions() -> dict:
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    job_repo, supplier_repo, action_repo, master_repo, agency_repo, job, customer, workflow, draft = _case()

    legacy = resolve_effective_automation_policy(
        action="supplier_reminder", legacy_dispatch_enabled=True,
        mina_job_repository=job_repo, job_id=job.job_id,
        master_data_repository=master_repo, agency_policy_repository=agency_repo,
    )
    check(
        legacy.effective_mode == "automatic" and legacy.resolved_from == "legacy_dispatch",
        "legacy dispatch behavior remains the fallback when no durable policy exists",
    )

    save_agency_automation_policy(
        repository=agency_repo, updated_by="Manager",
        supplier_reminder_mode="manual", customer_deadline_update_mode="automatic",
        occurred_at=NOW,
    )
    agency = resolve_effective_automation_policy(
        action="supplier_reminder", legacy_dispatch_enabled=True,
        mina_job_repository=job_repo, job_id=job.job_id,
        master_data_repository=master_repo, agency_policy_repository=agency_repo,
    )
    check(
        agency.effective_mode == "manual" and agency.resolved_from == "agency",
        "durable agency policy overrides legacy dispatch booleans",
    )

    customer = update_customer_master(
        repository=master_repo, customer_id=customer.customer_id, updated_by="Manager",
        occurred_at=NOW + timedelta(seconds=1), supplier_reminder_mode="approval_required",
        customer_deadline_update_mode="approval_required",
    )
    customer_resolved = resolve_effective_automation_policy(
        action="supplier_reminder", legacy_dispatch_enabled=True,
        mina_job_repository=job_repo, job_id=job.job_id,
        master_data_repository=master_repo, agency_policy_repository=agency_repo,
    )
    check(
        customer_resolved.effective_mode == "approval_required"
        and customer_resolved.resolved_from == "customer"
        and customer_resolved.customer_id == customer.customer_id,
        "customer policy overrides agency policy and records its source",
    )

    approval_supplier_plan = supplier_reminder_plan(
        supplier_repository=supplier_repo, action_repository=action_repo, draft=draft, now=NOW,
        mina_job_repository=job_repo, master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
    )
    approval_customer_plan = customer_deadline_plan(
        supplier_repository=supplier_repo, action_repository=action_repo, workflow=workflow, now=NOW,
        mina_job_repository=job_repo, master_data_repository=master_repo,
        agency_policy_repository=agency_repo,
    )
    check(
        approval_supplier_plan["state"] == "approval_required_supplier_reminder_due"
        and approval_customer_plan["state"] == "approval_required_customer_update_due",
        "approval-required policies create explicit human-review planner states",
    )

    sender = _Sender()
    approval_tick = run_automation_tick(
        supplier_repository=supplier_repo, action_repository=action_repo, sender=sender,
        mina_job_repository=job_repo, master_data_repository=master_repo,
        agency_policy_repository=agency_repo, now=NOW,
    )
    check(
        not sender.requests and approval_tick["counts"].get("sent", 0) == 0,
        "approval-required actions are never sent by the automatic scheduler",
    )

    job = set_mina_job_automation_overrides(
        repository=job_repo, mina_code=job.mina_code, actor="Operator",
        disable_supplier_reminders=False, disable_customer_deadline_updates=False,
        supplier_reminder_mode="automatic", customer_deadline_update_mode="manual",
        occurred_at=NOW + timedelta(seconds=2),
    )
    supplier_job = resolve_effective_automation_policy(
        action="supplier_reminder", legacy_dispatch_enabled=True,
        mina_job_repository=job_repo, job_id=job.job_id,
        master_data_repository=master_repo, agency_policy_repository=agency_repo,
    )
    customer_job = resolve_effective_automation_policy(
        action="customer_deadline_update", legacy_dispatch_enabled=True,
        mina_job_repository=job_repo, job_id=job.job_id,
        master_data_repository=master_repo, agency_policy_repository=agency_repo,
    )
    check(
        supplier_job.effective_mode == "automatic" and supplier_job.resolved_from == "job"
        and customer_job.effective_mode == "manual" and customer_job.resolved_from == "job",
        "job policy is the most specific policy layer",
    )

    automatic_tick = run_automation_tick(
        supplier_repository=supplier_repo, action_repository=action_repo, sender=sender,
        mina_job_repository=job_repo, master_data_repository=master_repo,
        agency_policy_repository=agency_repo, now=NOW,
    )
    check(
        len(sender.requests) == 1
        and sender.requests[0].purpose == "supplier_rfq"
        and automatic_tick["counts"].get("sent", 0) == 1,
        "scheduler sends only actions whose effective policy is automatic",
    )

    # Explicit legacy disable flags remain a job-level compatibility override when no modern job mode is set.
    job = set_mina_job_automation_overrides(
        repository=job_repo, mina_code=job.mina_code, actor="Operator",
        disable_supplier_reminders=True, disable_customer_deadline_updates=False,
        supplier_reminder_mode=None, customer_deadline_update_mode=None,
        occurred_at=NOW + timedelta(seconds=3),
    )
    legacy_disabled = resolve_effective_automation_policy(
        action="supplier_reminder", legacy_dispatch_enabled=True,
        mina_job_repository=job_repo, job_id=job.job_id,
        master_data_repository=master_repo, agency_policy_repository=agency_repo,
    )
    check(
        legacy_disabled.effective_mode == "manual"
        and legacy_disabled.resolved_from == "job_legacy_disable",
        "legacy job disable remains a fail-safe job-level override",
    )

    detail = build_mina_job_detail(
        repository=job_repo, supplier_repository=supplier_repo,
        quote_case_repository=InMemoryQuoteCaseRepository(), action_repository=action_repo,
        master_data_repository=master_repo, agency_policy_repository=agency_repo,
        job_id=job.job_id, now=NOW,
    )
    check(
        detail["automation"]["supplier_reminder_policy"]["resolved_from"] == "job_legacy_disable"
        and detail["automation"]["customer_deadline_update_policy"]["resolved_from"] == "customer",
        "MINA job detail exposes effective policy source and mode",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "policy.sqlite3", retention_days=30)
        sqlite_agency = SQLiteAgencyAutomationPolicyRepository(store)
        sqlite_master = SQLiteMasterDataRepository(store)
        save_agency_automation_policy(
            repository=sqlite_agency, updated_by="Manager",
            supplier_reminder_mode="approval_required",
            customer_deadline_update_mode="manual", occurred_at=NOW,
        )
        durable_customer = create_customer_master(
            repository=sqlite_master, entry_id="durable-customer", customer_name="Durable Customer",
            supplier_reminder_mode="automatic", updated_by="Manager", created_at=NOW,
        )
        store.purge_expired(now=NOW + timedelta(days=60))
        check(
            SQLiteAgencyAutomationPolicyRepository(store).get().supplier_reminder_mode == "approval_required"
            and SQLiteMasterDataRepository(store).get_customer(durable_customer.customer_id).supplier_reminder_mode == "automatic",
            "agency and customer automation policies survive ordinary retention purge",
        )

    import src.api as api
    original_agency = api.agency_automation_policy_repository
    original_master = api.master_data_repository
    original_jobs = api.mina_job_repository
    original_supplier = api.supplier_rfq_repository
    api.agency_automation_policy_repository = InMemoryAgencyAutomationPolicyRepository()
    api.master_data_repository = InMemoryMasterDataRepository()
    api.mina_job_repository = InMemoryMinaJobRepository()
    api.supplier_rfq_repository = InMemorySupplierRFQRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Operator"
    try:
        first = api.update_agency_automation_policy(
            api.AgencyAutomationPolicyRequest(
                supplier_reminder_mode="approval_required",
                customer_deadline_update_mode="automatic",
            ), request,
        )
        second = api.update_agency_automation_policy(
            api.AgencyAutomationPolicyRequest(supplier_reminder_mode="manual"), request,
        )
        api_customer = create_customer_master(
            repository=api.master_data_repository, entry_id="api-customer",
            customer_name="API Customer", supplier_reminder_mode="automatic",
            customer_deadline_update_mode="approval_required",
            updated_by="API Operator", created_at=NOW,
        )
        customer_partial = api.update_customer_automation_policy(
            api_customer.customer_id,
            api.CustomerAutomationPolicyRequest(supplier_reminder_mode="manual"), request,
        )
        api_job = create_manual_mina_job(
            repository=api.mina_job_repository, manual_intake_id="api-policy-job",
            intake_channel="phone", job_kind="price_request", shipment=_shipment("API Customer"),
            opened_by="API Operator", opened_at=NOW,
        )
        api.update_mina_job_automation_overrides(
            api_job.job_id,
            api.MinaJobAutomationOverrideRequest(customer_deadline_update_mode="manual"), request,
        )
        policy_view = api.get_mina_job_automation_policy(api_job.job_id)
    finally:
        api.agency_automation_policy_repository = original_agency
        api.master_data_repository = original_master
        api.mina_job_repository = original_jobs
        api.supplier_rfq_repository = original_supplier
    check(
        first["customer_deadline_update_mode"] == "automatic"
        and second["supplier_reminder_mode"] == "manual"
        and second["customer_deadline_update_mode"] == "automatic"
        and customer_partial["supplier_reminder_mode"] == "manual"
        and customer_partial["customer_deadline_update_mode"] == "approval_required"
        and policy_view["supplier_reminder"]["effective_mode"] == "manual"
        and policy_view["customer_deadline_update"]["effective_mode"] == "manual",
        "policy APIs preserve omitted fields and expose effective hierarchy",
    )

    check(
        route_allowed("GET", "/automation-policy/agency")
        and route_allowed("POST", "/automation-policy/agency")
        and route_allowed("POST", "/master-data/customers/customer-1/automation-policy")
        and route_allowed("GET", "/mina-jobs/job-1/automation-policy"),
        "pilot access explicitly allows controlled policy hierarchy surfaces",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_automation_policy_hierarchy_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAutomation policy hierarchy regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
