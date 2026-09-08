from __future__ import annotations

from datetime import datetime, timezone

from src.core.customer_recipient_authority import build_customer_quote_recipient_authority
from src.core.mail import MailSendResult
from src.core.master_data import MasterContact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job
from src.core.models import Shipment
from src.core.operation_start import OperationStartMessage
from src.core.operation_start_repository import InMemoryOperationStartMessageRepository
from src.core.operation_start_service import (
    OperationStartError,
    decide_operation_start_message,
    reconcile_operation_start_message_delivery,
    record_operation_start_message_manually_sent,
)
from src.core.outbound_runtime import OutboundRuntimePolicy, resolve_outbound_runtime_policy
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository


NOW = datetime(2026, 9, 8, 9, 0, tzinfo=timezone.utc)


class _Sender:
    def __init__(self):
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        raise AssertionError("shadow-mode regression must not reach provider")


class _UnknownSender:
    def __init__(self):
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        return MailSendResult(
            operation_id=request.operation_id,
            status="delivery_outcome_unknown",
            reason="synthetic uncertain provider outcome",
            provider_name="synthetic_provider",
        )


class _Scheduler:
    def __init__(self):
        self.starts = 0

    def start(self):
        self.starts += 1

    def stop(self):
        pass


def evaluate_outbound_shadow_safety_regressions() -> dict:
    failures: list[str] = []

    default_policy = resolve_outbound_runtime_policy({})
    enabled_policy = resolve_outbound_runtime_policy({"MINAI_OUTBOUND_MODE": "controlled_send"})
    if default_policy.mode != "shadow" or default_policy.delivery_enabled:
        failures.append("outbound runtime does not fail closed to shadow mode")
    if not enabled_policy.delivery_enabled:
        failures.append("explicit controlled_send mode does not enable delivery")
    try:
        resolve_outbound_runtime_policy({"MINAI_OUTBOUND_MODE": "unsafe"})
    except ValueError:
        pass
    else:
        failures.append("invalid outbound runtime mode did not fail closed")

    suppliers = InMemorySupplierRFQRepository()
    workflow = SupplierRFQWorkflow(
        shipment=Shipment(customer_name="Recipient Customer"),
        sender_address="requester@customer.example",
    )
    suppliers.save_workflow(workflow)
    cases = InMemoryQuoteCaseRepository()
    case = QuoteCase(
        shipment=Shipment(customer_name="Recipient Customer"),
        supplier_rfq_workflow_id=workflow.workflow_id,
    )
    cases.save(case)
    masters = InMemoryMasterDataRepository()
    create_customer_master(
        repository=masters,
        entry_id="recipient-customer",
        customer_name="Recipient Customer",
        trusted_sender_addresses=["trusted@customer.example"],
        trusted_sender_domains=["customer.example"],
        contacts=[MasterContact(
            contact_name="Pricing", email="pricing@customer.example",
            roles=["pricing"], is_primary=True,
        )],
        updated_by="Ops",
        created_at=NOW,
    )
    authority = build_customer_quote_recipient_authority(
        quote_case_repository=cases,
        supplier_repository=suppliers,
        master_repository=masters,
        case_id=case.case_id,
    )
    if authority.allowed_recipient_emails != [
        "requester@customer.example",
        "pricing@customer.example",
        "trusted@customer.example",
    ]:
        failures.append("customer quote recipient authority did not preserve bounded trusted evidence")
    if authority.allows("random@customer.example"):
        failures.append("trusted customer domain incorrectly authorized an arbitrary outbound recipient")

    if not __import__("src.core.pilot_access", fromlist=["route_allowed"]).route_allowed(
        "POST", "/operation-start-messages/message-1/send-reconciliation"
    ):
        failures.append("operation-start reconciliation route is not pilot-allowed")

    jobs = InMemoryMinaJobRepository()
    job = create_manual_mina_job(
        repository=jobs, manual_intake_id="shadow-reconcile-job",
        intake_channel="phone", job_kind="approved_job",
        shipment=Shipment(customer_name="Reconcile Customer"),
        opened_by="Ops", opened_at=NOW,
    )
    messages = InMemoryOperationStartMessageRepository()
    provider_unknown = OperationStartMessage(
        message_id="operation-provider-unknown", job_id=job.job_id, mina_code=job.mina_code,
        supplier_name="Carrier", recipient_email="carrier@example.test", kind="supplier_closure",
        outbound_mode="approval_required", subject="Closure", body_text="Body",
        status="approval_required", created_at=NOW, created_by="Ops",
    )
    messages.save(provider_unknown)
    unknown_sender = _UnknownSender()
    provider_result = decide_operation_start_message(
        repository=messages, mina_repository=jobs, sender=unknown_sender,
        message_id=provider_unknown.message_id, decision="approve", actor="Ops", now=NOW,
    )
    if provider_result.status != "delivery_outcome_unknown" or len(unknown_sender.calls) != 1:
        failures.append("operation-start uncertain provider outcome did not remain locked")
    try:
        record_operation_start_message_manually_sent(
            repository=messages, mina_repository=jobs, message_id=provider_unknown.message_id,
            actor="Ops", now=NOW,
        )
    except OperationStartError:
        pass
    else:
        failures.append("operation-start unknown provider outcome allowed manual evidence overwrite")

    unknown_not_sent = OperationStartMessage(
        message_id="operation-reconcile-not-sent", job_id=job.job_id, mina_code=job.mina_code,
        supplier_name="Carrier", recipient_email="carrier@example.test", kind="supplier_closure",
        outbound_mode="approval_required", subject="Closure", body_text="Body",
        status="delivery_outcome_unknown", created_at=NOW, created_by="Ops",
    )
    messages.save(unknown_not_sent)
    not_sent = reconcile_operation_start_message_delivery(
        repository=messages, mina_repository=jobs, message_id=unknown_not_sent.message_id,
        outcome="confirmed_not_sent", actor="Ops", reconciled_at=NOW,
    )
    if (not_sent.status != "failed"
            or not_sent.send_reconciliation_evidence[-1].outcome != "confirmed_not_sent"):
        failures.append("operation-start confirmed-not-sent reconciliation did not reopen delivery")

    unknown_sent = unknown_not_sent.model_copy(update={
        "message_id": "operation-reconcile-sent", "status": "delivery_outcome_unknown",
        "decision_reason": None, "attention_reason": None, "send_reconciliation_evidence": [],
    })
    messages.save(unknown_sent)
    sent = reconcile_operation_start_message_delivery(
        repository=messages, mina_repository=jobs, message_id=unknown_sent.message_id,
        outcome="confirmed_sent", actor="Ops", observed_sent_at=NOW, reconciled_at=NOW,
    )
    if (sent.status != "sent" or sent.sent_at != NOW or sent.sent_by != "Ops"
            or sent.send_reconciliation_evidence[-1].outcome != "confirmed_sent"):
        failures.append("operation-start confirmed-sent reconciliation lost operator evidence")

    import src.api as api
    original = (
        api.pilot_mode_enabled,
        api.outbound_runtime_policy,
        api.outbound_mail_sender,
        api.supplier_rfq_repository,
        api.automation_scheduler,
    )
    fake_sender = _Sender()
    shadow_suppliers = InMemorySupplierRFQRepository()
    draft = SupplierRFQDraft(
        workflow_id="shadow-workflow", supplier_name="Carrier", priority=1,
        recipient_email="carrier@example.test", subject="RFQ", body="Test",
        status="approved",
    )
    shadow_suppliers.save_drafts([draft])
    fake_scheduler = _Scheduler()
    try:
        api.pilot_mode_enabled = lambda: True
        api.outbound_runtime_policy = OutboundRuntimePolicy(mode="shadow")
        api.outbound_mail_sender = fake_sender
        api.supplier_rfq_repository = shadow_suppliers
        api.automation_scheduler = fake_scheduler
        api.start_controlled_automation_scheduler()
        if fake_scheduler.starts != 0:
            failures.append("shadow pilot started outbound automation scheduler")
        try:
            api.send_supplier_rfq_endpoint(draft.rfq_id)
        except api.HTTPException as exc:
            if exc.status_code != 409 or exc.detail != "outbound_delivery_disabled_by_shadow_mode":
                failures.append("shadow supplier send failed with the wrong control response")
        else:
            failures.append("shadow supplier send endpoint reached delivery path")
        if fake_sender.calls or shadow_suppliers.get_draft(draft.rfq_id).status != "approved":
            failures.append("shadow supplier send mutated state or reached provider")
    finally:
        (
            api.pilot_mode_enabled,
            api.outbound_runtime_policy,
            api.outbound_mail_sender,
            api.supplier_rfq_repository,
            api.automation_scheduler,
        ) = original

    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_outbound_shadow_safety_regressions()
    for failure in result["failures"]:
        print("FAIL", failure)
    if result["passed"]:
        print("PASS Shadow outbound safety and recipient authority")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
