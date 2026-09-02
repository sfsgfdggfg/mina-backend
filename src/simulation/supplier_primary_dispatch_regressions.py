from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch
from tempfile import TemporaryDirectory
from pathlib import Path

from src.core.models import Package, Shipment
from src.core.supplier_dispatch_control import (
    SupplierSecondaryDispatchBlockedError,
    authorize_secondary_after_price_negotiation,
    build_supplier_dispatch_status,
    record_supplier_acknowledgement,
    secondary_dispatch_gate,
)
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_lifecycle import approve_supplier_rfq
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteSupplierRFQRepository
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.core.mail import InboundMailEnvelope
from src.workflow.supplier_response_ingestion import ingest_supplier_reply
from src.workflow.pipeline import process_shipment
from src.workflow.supplier_rfq_progression import resume_supplier_rfq_workflow


NOW = datetime(2026, 9, 2, 9, 0, 0)


def _repo() -> tuple[InMemorySupplierRFQRepository, SupplierRFQWorkflow, list[SupplierRFQDraft]]:
    repo = InMemorySupplierRFQRepository()
    workflow = SupplierRFQWorkflow(
        workflow_id="wf-primary-dispatch",
        shipment=Shipment(customer_name="Synthetic", transport_mode="road"),
        dispatch_policy=SupplierDispatchPolicy(mode="parallel", initial_supplier_count=2),
    )
    repo.save_workflow(workflow)
    drafts = [
        SupplierRFQDraft(
            rfq_id="primary-a",
            workflow_id=workflow.workflow_id,
            supplier_name="Primary A",
            priority=1,
            recipient_email="a@example.invalid",
            supplier_role="primary",
            dispatch_tier="primary",
            subject="A",
            body="A",
            status="awaiting_response",
            sent_at=NOW,
        ),
        SupplierRFQDraft(
            rfq_id="primary-b",
            workflow_id=workflow.workflow_id,
            supplier_name="Primary B",
            priority=2,
            recipient_email="b@example.invalid",
            supplier_role="specialist",
            dispatch_tier="primary",
            subject="B",
            body="B",
            status="awaiting_response",
            sent_at=NOW,
        ),
        SupplierRFQDraft(
            rfq_id="secondary-c",
            workflow_id=workflow.workflow_id,
            supplier_name="Secondary C",
            priority=3,
            recipient_email="c@example.invalid",
            supplier_role="backup",
            dispatch_tier="secondary",
            subject="C",
            body="C",
            status="draft",
        ),
    ]
    repo.save_drafts(drafts)
    return repo, workflow, drafts


def _response(draft: SupplierRFQDraft, status: str, *, cost=None, currency=None):
    return SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name=draft.supplier_name,
        rfq_priority=draft.priority,
        status=status,
        cost=cost,
        currency=currency,
        received_at=NOW + timedelta(minutes=10),
    )


def evaluate_supplier_primary_dispatch_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    policy = SupplierDispatchPolicy()
    check(
        policy.no_response_reminder_minutes == 30
        and policy.acknowledged_grace_minutes == 120
        and policy.customer_deadline_proactive_minutes == 5
        and policy.silence_counts_as_capacity_failure is False
        and policy.urgent_customer_bypasses_primary_group is False,
        "road supplier timing and primary-protection defaults match operations",
    )

    repo, workflow, drafts = _repo()
    status_29 = build_supplier_dispatch_status(
        repository=repo, workflow_id=workflow.workflow_id, now=NOW + timedelta(minutes=29)
    )
    status_30 = build_supplier_dispatch_status(
        repository=repo, workflow_id=workflow.workflow_id, now=NOW + timedelta(minutes=30)
    )
    check(
        status_29["items"][0]["next_action"] == "wait_for_supplier_acknowledgement"
        and status_30["items"][0]["next_action"] == "send_no_response_reminder"
        and status_30["items"][0]["human_contact_required_if_still_silent_after_reminder"] is True,
        "silent primary supplier gets 30-minute reminder before human phone/WhatsApp escalation",
    )

    ack = record_supplier_acknowledgement(
        repository=repo,
        rfq_id=drafts[0].rfq_id,
        channel="whatsapp",
        recorded_by="Operator",
        acknowledged_at=NOW + timedelta(minutes=20),
    )
    ack_119 = build_supplier_dispatch_status(
        repository=repo, workflow_id=workflow.workflow_id, now=NOW + timedelta(minutes=139)
    )
    ack_120 = build_supplier_dispatch_status(
        repository=repo, workflow_id=workflow.workflow_id, now=NOW + timedelta(minutes=140)
    )
    check(
        ack["commercial_response_recorded"] is False
        and ack_119["items"][0]["next_action"] == "wait_acknowledged_supplier"
        and ack_120["items"][0]["next_action"] == "send_acknowledged_reminder",
        "confirmed seen/working acknowledgement starts a two-hour grace period without becoming a quote",
    )

    blocked = secondary_dispatch_gate(repo, workflow.workflow_id)
    check(
        blocked["allowed"] is False
        and blocked["reason"] == "primary_group_not_exhausted"
        and blocked["silence_never_counts_as_unavailable"] is True,
        "silent or still-working primary suppliers never release secondary suppliers",
    )

    try:
        approve_supplier_rfq(repo, drafts[2].rfq_id, "Operator")
    except Exception:
        secondary_approval_blocked = True
    else:
        secondary_approval_blocked = False
    check(
        secondary_approval_blocked,
        "secondary RFQ approval is fail-closed while any primary supplier remains unresolved",
    )

    unavailable_repo, unavailable_workflow, unavailable_drafts = _repo()
    unavailable_repo.save_responses([
        _response(unavailable_drafts[0], "no_capacity"),
        _response(unavailable_drafts[1], "declined"),
    ])
    capacity_gate = secondary_dispatch_gate(unavailable_repo, unavailable_workflow.workflow_id)
    approved_secondary = approve_supplier_rfq(
        unavailable_repo, unavailable_drafts[2].rfq_id, "Operator"
    )
    check(
        capacity_gate["allowed"] is True
        and capacity_gate["reason"] == "all_primary_explicitly_unavailable"
        and approved_secondary.status == "approved",
        "secondary suppliers release only after every primary explicitly reports unavailability",
    )

    deadline_repo = InMemorySupplierRFQRepository()
    deadline_workflow = SupplierRFQWorkflow(
        workflow_id="wf-deadline-dispatch",
        shipment=Shipment(
            customer_name="Deadline Customer",
            transport_mode="road",
            equipment_type="Tenteli",
            cargo_ready_date="2099-01-01",
            required_delivery_date="2099-01-02",
        ),
        dispatch_policy=SupplierDispatchPolicy(
            mode="parallel", initial_supplier_count=2
        ),
    )
    deadline_repo.save_workflow(deadline_workflow)
    deadline_drafts = [
        SupplierRFQDraft(
            rfq_id="deadline-primary-a",
            workflow_id=deadline_workflow.workflow_id,
            supplier_name="Deadline Primary A",
            priority=1,
            recipient_email="da@example.invalid",
            supplier_role="primary",
            dispatch_tier="primary",
            subject="DA", body="DA", status="responded",
            sent_at=NOW, responded_at=NOW + timedelta(minutes=10),
        ),
        SupplierRFQDraft(
            rfq_id="deadline-primary-b",
            workflow_id=deadline_workflow.workflow_id,
            supplier_name="Deadline Primary B",
            priority=2,
            recipient_email="db@example.invalid",
            supplier_role="specialist",
            dispatch_tier="primary",
            subject="DB", body="DB", status="responded",
            sent_at=NOW, responded_at=NOW + timedelta(minutes=10),
        ),
        SupplierRFQDraft(
            rfq_id="deadline-secondary",
            workflow_id=deadline_workflow.workflow_id,
            supplier_name="Deadline Secondary",
            priority=3,
            recipient_email="ds@example.invalid",
            supplier_role="backup",
            dispatch_tier="secondary",
            subject="DS", body="DS", status="draft",
        ),
    ]
    deadline_repo.save_drafts(deadline_drafts)
    deadline_repo.save_responses([
        SupplierRFQResponse(
            rfq_id=deadline_drafts[0].rfq_id,
            supplier_name=deadline_drafts[0].supplier_name,
            rfq_priority=1, status="quoted", cost=2400, currency="EUR",
            transit_time="4 days", vehicle_available_date="2099-01-01",
            received_at=NOW + timedelta(minutes=10),
        ),
        SupplierRFQResponse(
            rfq_id=deadline_drafts[1].rfq_id,
            supplier_name=deadline_drafts[1].supplier_name,
            rfq_priority=2, status="no_capacity",
            received_at=NOW + timedelta(minutes=10),
        ),
    ])
    deadline_gate = secondary_dispatch_gate(
        deadline_repo, deadline_workflow.workflow_id
    )
    deadline_secondary = approve_supplier_rfq(
        deadline_repo, deadline_drafts[2].rfq_id, "Operator"
    )
    check(
        deadline_gate["allowed"] is True
        and deadline_gate["reason"]
        == "all_primary_unavailable_or_delivery_incompatible"
        and deadline_secondary.status == "approved",
        "primary quote that cannot meet an explicit delivery deadline can release secondary only after every primary is resolved",
    )

    price_repo, price_workflow, price_drafts = _repo()
    price_repo.save_responses([
        _response(price_drafts[0], "quoted", cost=2500, currency="EUR"),
        _response(price_drafts[1], "no_capacity"),
    ])
    before_release = secondary_dispatch_gate(price_repo, price_workflow.workflow_id)
    release = authorize_secondary_after_price_negotiation(
        repository=price_repo,
        workflow_id=price_workflow.workflow_id,
        authorized_by="Operator",
        authorized_at=NOW + timedelta(minutes=30),
    )
    after_release = secondary_dispatch_gate(price_repo, price_workflow.workflow_id)
    check(
        before_release["allowed"] is False
        and release["reason"] == "primary_price_negotiation_exhausted"
        and release["customer_target_price_disclosed"] is False
        and after_release["allowed"] is True,
        "commercial fallback requires explicit exhausted-negotiation evidence and never discloses customer target price",
    )

    # Real orchestration does not prepare secondary RFQs at initial dispatch.
    # Once all primary results are terminal and the operator records exhausted
    # price negotiation, resume prepares the secondary RFQ instead of quoting
    # the expensive primary price.
    orchestration_selection = {
        "selected_suppliers": [
            {
                "supplier_name": "Primary Orchestration A",
                "recipient_email": "oa@example.invalid",
                "priority": 1,
                "supplier_role": "primary",
                "dispatch_tier": "primary",
                "total_score": 0.95,
            },
            {
                "supplier_name": "Primary Orchestration B",
                "recipient_email": "ob@example.invalid",
                "priority": 2,
                "supplier_role": "specialist",
                "dispatch_tier": "primary",
                "total_score": 0.90,
            },
            {
                "supplier_name": "Secondary Orchestration C",
                "recipient_email": "oc@example.invalid",
                "priority": 3,
                "supplier_role": "backup",
                "dispatch_tier": "secondary",
                "total_score": 0.80,
            },
        ],
        "rejected_suppliers": [],
        "source": "synthetic-tiered-selection",
    }
    orchestration_shipment = Shipment(
        customer_name="Synthetic Dispatch Orchestration",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        delivery_postcode="20095",
        commodity="Tekstil",
        gross_weight_kg=20_000,
        transport_mode="road",
        service_type="FTL",
        equipment_type="Tenteli",
        cargo_ready_date="2026-09-03",
        required_delivery_date="2026-09-09",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[Package(
            package_type="pallet", quantity=10,
            length_cm=120, width_cm=80, height_cm=150, weight_kg=2000,
        )],
    )
    orchestration_repo = InMemorySupplierRFQRepository()
    with patch.dict("os.environ", {"MINAI_PILOT_MODE": "0"}, clear=False), patch(
        "src.workflow.pipeline.select_suppliers_for_shipment",
        return_value=orchestration_selection,
    ):
        initial = process_shipment(
            orchestration_shipment,
            rfq_repository=orchestration_repo,
        )
    initial_orchestration_drafts = initial["supplier_rfq_drafts"]
    check(
        len(initial_orchestration_drafts) == 2
        and all(draft.dispatch_tier == "primary" for draft in initial_orchestration_drafts),
        "initial orchestration prepares every primary RFQ and no secondary RFQ",
    )
    terminal_primary_drafts = []
    for draft in initial_orchestration_drafts:
        terminal_primary_drafts.append(draft.model_copy(update={
            "status": "responded",
            "sent_at": NOW,
            "responded_at": NOW + timedelta(minutes=10),
        }))
    orchestration_repo.save_drafts(terminal_primary_drafts)
    orchestration_repo.save_responses([
        _response(terminal_primary_drafts[0], "quoted", cost=2900, currency="EUR"),
        _response(terminal_primary_drafts[1], "quoted", cost=2950, currency="EUR"),
    ])
    authorize_secondary_after_price_negotiation(
        repository=orchestration_repo,
        workflow_id=initial["supplier_rfq_workflow"].workflow_id,
        authorized_by="Operator",
        authorized_at=NOW + timedelta(minutes=20),
    )
    with patch.dict("os.environ", {"MINAI_PILOT_MODE": "0"}, clear=False), patch(
        "src.workflow.supplier_rfq_progression.select_suppliers_for_shipment",
        return_value=orchestration_selection,
    ):
        commercial_fallback = resume_supplier_rfq_workflow(
            workflow_id=initial["supplier_rfq_workflow"].workflow_id,
            rfq_repository=orchestration_repo,
            approval_repository=InMemoryQuoteApprovalRepository(),
            quote_case_repository=InMemoryQuoteCaseRepository(),
        )
    fallback_drafts = [
        draft for draft in orchestration_repo.list_drafts()
        if draft.workflow_id == initial["supplier_rfq_workflow"].workflow_id
    ]
    check(
        commercial_fallback.get("result_type") == "supplier_rfq_approval_required"
        and len(fallback_drafts) == 3
        and sum(draft.dispatch_tier == "secondary" for draft in fallback_drafts) == 1
        and next(
            draft for draft in fallback_drafts if draft.dispatch_tier == "secondary"
        ).status == "draft"
        and commercial_fallback.get("quote_case") is None,
        "exhausted primary price negotiation prepares secondary RFQ before customer quote",
    )

    incomplete_repo, incomplete_workflow, incomplete_drafts = _repo()
    incomplete_repo.save_responses([
        _response(incomplete_drafts[0], "quoted", cost=2500, currency="EUR"),
    ])
    try:
        authorize_secondary_after_price_negotiation(
            repository=incomplete_repo,
            workflow_id=incomplete_workflow.workflow_id,
            authorized_by="Operator",
        )
    except SupplierSecondaryDispatchBlockedError:
        incomplete_release_blocked = True
    else:
        incomplete_release_blocked = False
    check(
        incomplete_release_blocked,
        "one expensive primary quote cannot bypass another unresolved primary supplier",
    )

    with TemporaryDirectory(prefix="minai-primary-dispatch-") as directory:
        store = SQLitePilotStore(
            Path(directory) / "dispatch.sqlite3",
            run_id="primary-dispatch-regression",
        )
        sqlite_repo = SQLiteSupplierRFQRepository(store)
        _, durable_workflow, durable_drafts = _repo()
        sqlite_repo.save_workflow(durable_workflow)
        sqlite_repo.save_drafts(durable_drafts)
        durable_ack_time = NOW + timedelta(minutes=15)
        record_supplier_acknowledgement(
            repository=sqlite_repo,
            rfq_id=durable_drafts[0].rfq_id,
            channel="phone",
            recorded_by="Operator",
            acknowledged_at=durable_ack_time,
        )
        record_supplier_acknowledgement(
            repository=sqlite_repo,
            rfq_id=durable_drafts[0].rfq_id,
            channel="phone",
            recorded_by="Operator",
            acknowledged_at=durable_ack_time,
        )
        sqlite_repo.save_responses([
            _response(durable_drafts[0], "quoted", cost=2500, currency="EUR"),
            _response(durable_drafts[1], "no_capacity"),
        ])
        first_authorization = authorize_secondary_after_price_negotiation(
            repository=sqlite_repo,
            workflow_id=durable_workflow.workflow_id,
            authorized_by="Operator",
            authorized_at=NOW + timedelta(minutes=30),
        )
        second_authorization = authorize_secondary_after_price_negotiation(
            repository=sqlite_repo,
            workflow_id=durable_workflow.workflow_id,
            authorized_by="Operator",
            authorized_at=NOW + timedelta(minutes=31),
        )
        reopened = SQLiteSupplierRFQRepository(store)
        durable_acks = reopened.list_acknowledgements(
            durable_drafts[0].rfq_id
        )
        durable_authorization = reopened.get_secondary_dispatch_authorization(
            durable_workflow.workflow_id
        )
        check(
            len(durable_acks) == 1
            and durable_acks[0].acknowledged_at == durable_ack_time
            and durable_authorization is not None
            and first_authorization["authorized_at"]
            == second_authorization["authorized_at"]
            == durable_authorization.authorized_at,
            "acknowledgement and commercial release evidence are durable and idempotent in SQLite",
        )

    email_repo, email_workflow, email_drafts = _repo()
    reply = InboundMailEnvelope(
        source="email",
        sender_address=email_drafts[0].recipient_email,
        subject=f"Re: [{email_drafts[0].reference_token}] A",
        body_text="Mailinizi aldık, üzerinde çalışıyoruz. Dönüş yapacağız.",
        received_at=NOW + timedelta(minutes=5),
        external_message_id="synthetic-ack-1",
    )
    ingested = ingest_supplier_reply(reply=reply, repository=email_repo)
    check(
        ingested.status == "acknowledgement_recorded"
        and email_repo.list_responses(email_drafts[0].rfq_id) == []
        and len(email_repo.list_acknowledgements(email_drafts[0].rfq_id)) == 1
        and email_repo.get_draft(email_drafts[0].rfq_id).status == "awaiting_response",
        "natural supplier 'received and working' email is recorded as non-commercial acknowledgement",
    )

    no_currency_repo, _, no_currency_drafts = _repo()
    no_currency_reply = InboundMailEnvelope(
        source="email",
        sender_address=no_currency_drafts[0].recipient_email,
        subject=f"Re: [{no_currency_drafts[0].reference_token}] A",
        body_text="Mailinizi aldık, fiyatımız 2500.",
        received_at=NOW + timedelta(minutes=5),
        external_message_id="synthetic-no-currency-price",
    )
    no_currency = ingest_supplier_reply(
        reply=no_currency_reply, repository=no_currency_repo
    )
    check(
        no_currency.status != "acknowledgement_recorded"
        and no_currency_repo.list_acknowledgements(
            no_currency_drafts[0].rfq_id
        ) == [],
        "acknowledgement detector does not swallow a price without currency",
    )

    mixed_repo, mixed_workflow, mixed_drafts = _repo()
    mixed_reply = InboundMailEnvelope(
        source="email",
        sender_address=mixed_drafts[0].recipient_email,
        subject=f"Re: [{mixed_drafts[0].reference_token}] A",
        body_text="Mailinizi aldık, fiyatımız 2500 EUR.",
        received_at=NOW + timedelta(minutes=5),
        external_message_id="synthetic-mixed-1",
    )
    mixed = ingest_supplier_reply(reply=mixed_reply, repository=mixed_repo)
    check(
        mixed.status != "acknowledgement_recorded"
        and mixed_repo.list_acknowledgements(mixed_drafts[0].rfq_id) == [],
        "acknowledgement detector never swallows a message carrying commercial result signals",
    )

    rendered = repr(build_supplier_dispatch_status(
        repository=price_repo, workflow_id=price_workflow.workflow_id, now=NOW
    )).lower()
    check(
        "authorized_by" not in rendered
        and "recorded_by" not in rendered
        and "2500" not in rendered,
        "dispatch status does not expose operator evidence or customer target price",
    )

    return {
        "name": "Primary supplier dispatch and response timing",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main() -> int:
    result = evaluate_supplier_primary_dispatch_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nPrimary supplier dispatch regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
