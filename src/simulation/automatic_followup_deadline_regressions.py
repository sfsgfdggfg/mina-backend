from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading

from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundMailEnvelope, MailSendResult
from src.core.models import Shipment
from src.core.operational_work_queue import build_operational_work_queue
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.relative_dates import infer_customer_quote_deadline
from src.core.sqlite_repositories import (
    SQLiteAutomationActionRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.supplier_dispatch_control import record_supplier_acknowledgement
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.automation_scheduler import run_automation_tick
from src.workflow.mail_ingestion import process_customer_inquiry_mail


NOW = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)


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
            provider_name="synthetic-provider",
            provider_message_id=f"message-{len(self.requests)}",
            sent_at=NOW,
        )


def _workflow(*, policy=None, deadline=None, version=1):
    return SupplierRFQWorkflow(
        workflow_id="wf-auto",
        shipment=Shipment(
            customer_name="Synthetic",
            transport_mode="road",
            equipment_type="Tenteli",
            cargo_ready_date="2026-09-03",
            customer_quote_deadline_at=deadline,
        ),
        sender_address="customer@example.invalid",
        customer_subject="Road quote request",
        automation_timing_version=version,
        dispatch_policy=policy
        or SupplierDispatchPolicy(mode="parallel", initial_supplier_count=2),
    )


def _draft(*, sent_at=None):
    return SupplierRFQDraft(
        rfq_id="rfq-auto",
        workflow_id="wf-auto",
        supplier_name="Synthetic Primary",
        priority=1,
        recipient_email="supplier@example.invalid",
        supplier_role="primary",
        dispatch_tier="primary",
        subject="Synthetic RFQ",
        body="Synthetic body",
        status="awaiting_response",
        sent_at=sent_at or NOW - timedelta(minutes=30),
    )


def _queue(repo, actions, now=NOW):
    return build_operational_work_queue(
        attachment_repository=InMemoryAttachmentInterpretationReviewRepository(),
        proposal_repository=InMemoryExtractionProposalRepository(),
        supplier_repository=repo,
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        automation_action_repository=actions,
        now=now,
    )


def evaluate_automatic_followup_deadline_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    received = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    check(
        str(infer_customer_quote_deadline(
            "Fiyatınızı bugün 15:00 e kadar rica ederiz.", received
        )) == "2026-09-02 15:00:00+03:00"
        and str(infer_customer_quote_deadline(
            "Navlun teklifini 1 saat içinde iletebilir misiniz?", received
        )) == "2026-09-02 12:00:00+03:00"
        and str(infer_customer_quote_deadline(
            "Fiyatı öğlene kadar rica ederiz.", received
        )) == "2026-09-02 12:00:00+03:00",
        "explicit customer quote deadlines resolve from message receipt time",
    )
    proposal_repo = InMemoryExtractionProposalRepository()
    deadline_mail = InboundMailEnvelope(
        source="email",
        sender_address="customer@example.invalid",
        subject="Road quote",
        body_text="Fiyatınızı bugün 15:00 e kadar rica ederiz.",
        received_at=received,
        external_message_id="deadline-mail-1",
    )
    deadline_result = process_customer_inquiry_mail(
        mail=deadline_mail,
        shipment_parser=lambda _text: ShipmentProposalSnapshot(
            customer_name="Synthetic", transport_mode="road"
        ),
        proposal_repository=proposal_repo,
    )
    urgent_mail = InboundMailEnvelope(
        source="email",
        sender_address="customer@example.invalid",
        subject="Urgent quote",
        body_text="Acil fiyat rica ederiz.",
        received_at=received,
        external_message_id="deadline-mail-2",
    )
    urgent_result = process_customer_inquiry_mail(
        mail=urgent_mail,
        shipment_parser=lambda _text: ShipmentProposalSnapshot(
            customer_name="Synthetic", transport_mode="road"
        ),
        proposal_repository=proposal_repo,
    )
    check(
        str(
            deadline_result["extraction_proposal"]
            .proposed_shipment.customer_quote_deadline_at
        ) == "2026-09-02 15:00:00+03:00"
        and urgent_result["extraction_proposal"]
        .proposed_shipment.customer_quote_deadline_at is None,
        "safe customer mail ingestion persists only explicit quote-response deadline evidence",
    )

    check(
        infer_customer_quote_deadline("Acil fiyat rica ederiz.", received) is None
        and infer_customer_quote_deadline(
            "Teslimat bugün 15:00 e kadar olmalı.", received
        ) is None
        and infer_customer_quote_deadline(
            "Fiyat rica ederiz, transit 4 saat.", received
        ) is None,
        "urgency delivery timing and transit duration never invent quote deadlines",
    )

    defaults = SupplierDispatchPolicy()
    check(
        defaults.automatic_supplier_reminders_enabled is True
        and defaults.automatic_customer_deadline_updates_enabled is True,
        "both approved automation toggles default on",
    )

    legacy_repo = InMemorySupplierRFQRepository()
    legacy_actions = InMemoryAutomationActionRepository()
    legacy_repo.save_workflow(_workflow(version=0, deadline=NOW + timedelta(minutes=5)))
    legacy_repo.save_drafts([_draft()])
    legacy_sender = _Sender()
    run_automation_tick(
        supplier_repository=legacy_repo,
        action_repository=legacy_actions,
        sender=legacy_sender,
        now=NOW,
    )
    check(
        not legacy_sender.requests and not legacy_actions.list_all(),
        "pre-P1-73 workflows are never retroactively auto-activated",
    )

    repo = InMemorySupplierRFQRepository()
    actions = InMemoryAutomationActionRepository()
    repo.save_workflow(_workflow())
    repo.save_drafts([_draft()])
    sender = _Sender()
    run_automation_tick(
        supplier_repository=repo, action_repository=actions, sender=sender, now=NOW
    )
    run_automation_tick(
        supplier_repository=repo, action_repository=actions, sender=sender, now=NOW
    )
    check(
        len(sender.requests) == 1
        and sender.requests[0].purpose == "supplier_rfq"
        and len(actions.list_all()) == 1
        and actions.list_all()[0].status == "sent",
        "30-minute silent-supplier reminder sends once and is idempotent",
    )
    queue = _queue(repo, actions)
    check(
        any(
            item["work_type"] == "supplier_contact_escalation"
            and item["next_action"] == "contact_supplier_phone_or_whatsapp"
            for item in queue["items"]
        ),
        "silence after automatic reminder becomes phone or WhatsApp human work",
    )

    ack_repo = InMemorySupplierRFQRepository()
    ack_actions = InMemoryAutomationActionRepository()
    ack_repo.save_workflow(_workflow())
    ack_draft = _draft(sent_at=NOW - timedelta(minutes=130))
    ack_repo.save_drafts([ack_draft])
    record_supplier_acknowledgement(
        repository=ack_repo,
        rfq_id=ack_draft.rfq_id,
        channel="email",
        acknowledged_at=NOW - timedelta(minutes=120),
    )
    ack_sender = _Sender()
    run_automation_tick(
        supplier_repository=ack_repo,
        action_repository=ack_actions,
        sender=ack_sender,
        now=NOW,
    )
    check(
        len(ack_sender.requests) == 1
        and ack_actions.list_all()[0].action_type
        == "supplier_acknowledged_reminder",
        "acknowledgement suppresses 30-minute reminder and allows one two-hour reminder",
    )

    off_policy = SupplierDispatchPolicy(
        mode="parallel",
        initial_supplier_count=2,
        automatic_supplier_reminders_enabled=False,
        automatic_customer_deadline_updates_enabled=False,
    )
    off_repo = InMemorySupplierRFQRepository()
    off_actions = InMemoryAutomationActionRepository()
    off_repo.save_workflow(
        _workflow(policy=off_policy, deadline=NOW + timedelta(minutes=5))
    )
    off_repo.save_drafts([_draft()])
    off_sender = _Sender()
    run_automation_tick(
        supplier_repository=off_repo,
        action_repository=off_actions,
        sender=off_sender,
        now=NOW,
    )
    off_queue = _queue(off_repo, off_actions)
    check(
        not off_sender.requests
        and {item["work_type"] for item in off_queue["items"]}
        >= {"supplier_contact_escalation", "customer_deadline_update"},
        "disabled automations create human work and never send",
    )

    rendered_off_queue = repr(off_queue).lower()
    check(
        "customer@example.invalid" not in rendered_off_queue
        and "supplier@example.invalid" not in rendered_off_queue
        and "provider_message_id" not in rendered_off_queue,
        "automation work queue remains privacy-minimal",
    )

    deadline_repo = InMemorySupplierRFQRepository()
    deadline_actions = InMemoryAutomationActionRepository()
    deadline_repo.save_workflow(_workflow(deadline=NOW + timedelta(minutes=5)))
    deadline_sender = _Sender()
    run_automation_tick(
        supplier_repository=deadline_repo,
        action_repository=deadline_actions,
        sender=deadline_sender,
        now=NOW,
    )
    run_automation_tick(
        supplier_repository=deadline_repo,
        action_repository=deadline_actions,
        sender=deadline_sender,
        now=NOW,
    )
    check(
        len(deadline_sender.requests) == 1
        and deadline_sender.requests[0].purpose == "customer_status_update"
        and deadline_actions.list_all()[0].status == "sent",
        "customer receives one proactive status update five minutes before explicit deadline",
    )

    priced_repo = InMemorySupplierRFQRepository()
    priced_actions = InMemoryAutomationActionRepository()
    priced_repo.save_workflow(_workflow(deadline=NOW + timedelta(minutes=5)))
    priced_draft = _draft(sent_at=NOW - timedelta(minutes=10))
    priced_repo.save_drafts([priced_draft.model_copy(update={"status": "responded"})])
    priced_repo.save_responses([
        SupplierRFQResponse(
            rfq_id=priced_draft.rfq_id,
            supplier_name=priced_draft.supplier_name,
            rfq_priority=priced_draft.priority,
            status="quoted",
            cost=2200,
            currency="EUR",
            transit_time="4 days",
            received_at=NOW - timedelta(minutes=1),
        )
    ])
    priced_sender = _Sender()
    run_automation_tick(
        supplier_repository=priced_repo,
        action_repository=priced_actions,
        sender=priced_sender,
        now=NOW,
    )
    check(
        not priced_sender.requests and not priced_actions.list_all(),
        "usable supplier price suppresses proactive waiting-for-price customer update",
    )

    failed_repo = InMemorySupplierRFQRepository()
    failed_actions = InMemoryAutomationActionRepository()
    failed_repo.save_workflow(_workflow())
    failed_repo.save_drafts([_draft()])
    failed_sender = _Sender("failed")
    run_automation_tick(
        supplier_repository=failed_repo,
        action_repository=failed_actions,
        sender=failed_sender,
        now=NOW,
    )
    run_automation_tick(
        supplier_repository=failed_repo,
        action_repository=failed_actions,
        sender=failed_sender,
        now=NOW,
    )
    failed_queue = _queue(failed_repo, failed_actions)
    check(
        len(failed_sender.requests) == 1
        and failed_actions.list_all()[0].status == "failed"
        and any(
            item["next_action"] == "inspect_supplier_automation_delivery"
            for item in failed_queue["items"]
        ),
        "provider failure is not auto-retried and becomes human attention",
    )

    class _InjectResponseOnReserve(InMemoryAutomationActionRepository):
        def __init__(self, supplier_repo):
            super().__init__()
            self.supplier_repo = supplier_repo
            self.injected = False

        def reserve(self, action):
            reserved = super().reserve(action)
            if reserved and action.status == "reserved" and not self.injected:
                self.injected = True
                draft = self.supplier_repo.get_draft("rfq-auto")
                self.supplier_repo.save_responses([
                    SupplierRFQResponse(
                        rfq_id=draft.rfq_id,
                        supplier_name=draft.supplier_name,
                        rfq_priority=draft.priority,
                        status="no_capacity",
                        received_at=NOW,
                    )
                ])
                self.supplier_repo.save_drafts([
                    draft.model_copy(update={"status": "responded", "responded_at": NOW})
                ])
            return reserved

    race_repo = InMemorySupplierRFQRepository()
    race_repo.save_workflow(_workflow())
    race_repo.save_drafts([_draft()])
    race_actions = _InjectResponseOnReserve(race_repo)
    race_sender = _Sender()
    run_automation_tick(
        supplier_repository=race_repo,
        action_repository=race_actions,
        sender=race_sender,
        now=NOW,
    )
    check(
        not race_sender.requests
        and race_actions.list_all()[0].status == "cancelled",
        "supplier response arriving after reservation cancels stale reminder before provider send",
    )

    with tempfile.TemporaryDirectory(prefix="minai-p1-73-concurrency-") as directory:
        store = SQLitePilotStore(
            Path(directory) / "automation.sqlite3", run_id="p1-73-concurrency"
        )
        concurrent_supplier = SQLiteSupplierRFQRepository(store)
        concurrent_actions = SQLiteAutomationActionRepository(store)
        concurrent_supplier.save_workflow(_workflow())
        concurrent_supplier.save_drafts([_draft()])
        concurrent_sender = _Sender()
        errors = []

        def worker():
            try:
                run_automation_tick(
                    supplier_repository=concurrent_supplier,
                    action_repository=concurrent_actions,
                    sender=concurrent_sender,
                    now=NOW,
                )
            except Exception as exc:
                errors.append(type(exc).__name__)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        check(
            not errors
            and len(concurrent_sender.requests) == 1
            and len(concurrent_actions.list_all()) == 1
            and concurrent_actions.list_all()[0].status == "sent",
            "concurrent scheduler ticks reserve one durable send only",
        )

    with tempfile.TemporaryDirectory(prefix="minai-p1-73-") as directory:
        store = SQLitePilotStore(Path(directory) / "automation.sqlite3", run_id="p1-73")
        sqlite_supplier = SQLiteSupplierRFQRepository(store)
        sqlite_actions = SQLiteAutomationActionRepository(store)
        sqlite_supplier.save_workflow(_workflow())
        sqlite_supplier.save_drafts([_draft()])
        sqlite_sender = _Sender()
        run_automation_tick(
            supplier_repository=sqlite_supplier,
            action_repository=sqlite_actions,
            sender=sqlite_sender,
            now=NOW,
        )
        reopened = SQLitePilotStore(
            Path(directory) / "automation.sqlite3", run_id="p1-73-reopen"
        )
        persisted = SQLiteAutomationActionRepository(reopened).list_all()
        check(
            len(persisted) == 1 and persisted[0].status == "sent",
            "automation send evidence survives SQLite restart",
        )

    return {
        "name": "Automatic supplier follow-up and customer quote deadline",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main() -> int:
    result = evaluate_automatic_followup_deadline_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nP1-73 automatic follow-up/deadline regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
