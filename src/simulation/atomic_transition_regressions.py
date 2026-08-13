from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.core.mail import InboundMailEnvelope
from src.core.extraction_confirmation import (
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
)
from src.core.models import (
    CustomerQuote,
    Package,
    QuoteDraft,
    Shipment,
    SupplierQuote,
)
from src.core.pilot_store import SQLitePilotStore, SQLiteTransactionError
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_approval_service import (
    approve_quote,
    invalidate_quote_approval,
    reject_quote,
)
from src.core.quote_case import QuoteCase
from src.core.sqlite_repositories import (
    SQLiteExtractionProposalRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)
from src.core.supplier_rfq_lifecycle import attach_supplier_rfq_response
from src.core.supplier_rfq_repository import DuplicateSupplierRFQResponseError
from src.workflow.pipeline import process_shipment
from src.workflow.extraction_confirmation import (
    ExtractionConfirmationTransitionError,
    _require_unchanged_resume_state,
    confirm_extraction_proposal,
    resume_confirmed_extraction,
)
from src.workflow.supplier_response_ingestion import ingest_supplier_reply
from src.workflow.supplier_rfq_progression import (
    SupplierRFQWorkflowProgressionError,
    _require_unchanged_progression_state,
    resume_supplier_rfq_workflow,
)


class InjectedPersistenceError(RuntimeError):
    pass


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Atomic Transition Regression",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=12000,
        service_type="FTL",
        transport_mode="road",
        cargo_ready_date="2026-09-15",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[
            Package(
                package_type="pallet",
                quantity=12,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )


def _repositories(db_path: Path, run_id: str):
    store = SQLitePilotStore(db_path, run_id=run_id)
    return (
        store,
        SQLiteSupplierRFQRepository(store),
        SQLiteQuoteApprovalRepository(store),
        SQLiteQuoteCaseRepository(store),
    )


def _rfq_creation_atomicity(failures: list[str], root: Path) -> None:
    db_path = root / "rfq-creation.sqlite3"
    store, rfqs, approvals, cases = _repositories(db_path, "creation-fail")
    original_upsert = store.upsert
    write_count = 0

    def fail_after_first_write(**kwargs):
        nonlocal write_count
        original_upsert(**kwargs)
        write_count += 1
        if write_count == 1:
            raise InjectedPersistenceError("after first RFQ creation write")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        with patch.object(store, "upsert", side_effect=fail_after_first_write):
            try:
                process_shipment(
                    _shipment(),
                    rfq_repository=rfqs,
                    approval_repository=approvals,
                    quote_case_repository=cases,
                )
            except InjectedPersistenceError:
                pass
            else:
                failures.append("RFQ creation failure did not propagate")

    _, reopened_rfqs, _, _ = _repositories(db_path, "creation-reopen")
    if reopened_rfqs.list_drafts() or reopened_rfqs.get_workflow("unknown"):
        failures.append("RFQ creation rollback left partial durable records")
    if reopened_rfqs.store.list_all(
        namespace=reopened_rfqs.WORKFLOW_NAMESPACE
    ):
        failures.append("RFQ creation rollback left a workflow")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        recovered = process_shipment(
            _shipment(),
            rfq_repository=reopened_rfqs,
            approval_repository=SQLiteQuoteApprovalRepository(
                reopened_rfqs.store
            ),
            quote_case_repository=SQLiteQuoteCaseRepository(
                reopened_rfqs.store
            ),
        )
    workflow = recovered.get("supplier_rfq_workflow")
    drafts = recovered.get("supplier_rfq_drafts") or []
    if (
        workflow is None
        or not drafts
        or set(workflow.rfq_ids) != {draft.rfq_id for draft in drafts}
    ):
        failures.append("successful RFQ creation was not mutually consistent")


def _response_atomicity(failures: list[str], root: Path) -> None:
    db_path = root / "response.sqlite3"
    _, rfqs, _, _ = _repositories(db_path, "response-fail")
    workflow = SupplierRFQWorkflow(shipment=_shipment())
    draft = SupplierRFQDraft(
        workflow_id=workflow.workflow_id,
        supplier_name="Atomic Supplier",
        priority=1,
        recipient_email="pricing@supplier.test",
        subject="Atomic RFQ",
        body="Atomic RFQ body",
        status="awaiting_response",
        sent_at=datetime(2026, 8, 13, 10, 0, 0),
    )
    workflow.rfq_ids = [draft.rfq_id]
    rfqs.save_workflow(workflow)
    rfqs.save_drafts([draft])
    response = SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name=draft.supplier_name,
        rfq_priority=draft.priority,
        status="quoted",
        cost=1000,
        currency="EUR",
        received_at=datetime(2026, 8, 13, 10, 30, 0),
    )

    with patch.object(
        rfqs,
        "save_drafts",
        side_effect=InjectedPersistenceError("after response write"),
    ):
        try:
            attach_supplier_rfq_response(rfqs, response)
        except InjectedPersistenceError:
            pass
        else:
            failures.append("response persistence failure did not propagate")

    _, reopened, _, _ = _repositories(db_path, "response-reopen")
    durable_draft = reopened.get_draft(draft.rfq_id)
    if reopened.list_responses(draft.rfq_id):
        failures.append("response rollback left an accepted response")
    if durable_draft is None or durable_draft.status != "awaiting_response":
        failures.append("response rollback advanced RFQ status")

    attached = attach_supplier_rfq_response(reopened, response)
    if attached.status != "responded":
        failures.append("response retry did not advance RFQ exactly once")
    try:
        attach_supplier_rfq_response(reopened, response)
    except DuplicateSupplierRFQResponseError:
        pass
    else:
        failures.append("successful response retry allowed a duplicate")


def _ingestion_marker_atomicity(failures: list[str], root: Path) -> None:
    db_path = root / "ingestion.sqlite3"
    _, rfqs, _, _ = _repositories(db_path, "ingestion-fail")
    workflow = SupplierRFQWorkflow(shipment=_shipment())
    draft = SupplierRFQDraft(
        workflow_id=workflow.workflow_id,
        supplier_name="Marker Supplier",
        priority=1,
        recipient_email="pricing@marker.test",
        subject="Marker RFQ",
        body="Marker body",
        status="awaiting_response",
        sent_at=datetime(2026, 8, 13, 11, 0, 0),
    )
    workflow.rfq_ids = [draft.rfq_id]
    rfqs.save_workflow(workflow)
    rfqs.save_drafts([draft])
    reply = InboundMailEnvelope(
        external_message_id="atomic-message-1",
        provider_name="regression",
        mailbox_id="pricing",
        sender_address="pricing@marker.test",
        subject=f"Re: {draft.reference_token}",
        body_text=f"{draft.reference_token} quoted 1000 EUR",
        source="email",
        received_at=datetime(2026, 8, 13, 11, 30, 0),
    )
    message_key = reply.message_deduplication_key
    original_record = rfqs.record_ingested_message

    def fail_after_marker(message_key_value: str):
        original_record(message_key_value)
        raise InjectedPersistenceError("after ingestion marker write")

    with patch.object(
        rfqs,
        "record_ingested_message",
        side_effect=fail_after_marker,
    ):
        try:
            ingest_supplier_reply(
                reply=reply,
                repository=rfqs,
                extracted_response={
                    "status": "quoted",
                    "cost": 1000,
                    "currency": "EUR",
                },
            )
        except InjectedPersistenceError:
            pass
        else:
            failures.append("ingestion marker failure did not propagate")

    _, reopened, _, _ = _repositories(db_path, "ingestion-reopen")
    if (
        reopened.list_responses(draft.rfq_id)
        or reopened.has_ingested_message(message_key)
        or reopened.get_draft(draft.rfq_id).status != "awaiting_response"
    ):
        failures.append("ingestion rollback left a partial accepted message")
    recovered = ingest_supplier_reply(
        reply=reply,
        repository=reopened,
        extracted_response={
            "status": "quoted",
            "cost": 1000,
            "currency": "EUR",
        },
    )
    if recovered.status != "response_attached":
        failures.append("rolled-back ingestion did not retry successfully")
    duplicate = ingest_supplier_reply(
        reply=reply,
        repository=reopened,
        extracted_response={
            "status": "quoted",
            "cost": 1000,
            "currency": "EUR",
        },
    )
    if duplicate.status != "duplicate_response":
        failures.append("successful ingestion retry was not idempotent")


def _selection_fixture(draft: SupplierRFQDraft) -> dict:
    return {
        "selected_suppliers": [
            {
                "supplier_name": draft.supplier_name,
                "priority": draft.priority,
                "route_score": 1.0,
                "equipment_score": 1.0,
                "risk_score": 1.0,
                "price_score": 0.9,
                "speed_score": 0.9,
                "total_score": 0.95,
            }
        ],
        "rejected_suppliers": [],
        "source": "atomic_transition_regression",
    }


def _quote_progression_atomicity(failures: list[str], root: Path) -> None:
    db_path = root / "quote-progression.sqlite3"
    _, rfqs, approvals, cases = _repositories(db_path, "quote-fail")
    workflow = SupplierRFQWorkflow(shipment=_shipment())
    draft = SupplierRFQDraft(
        workflow_id=workflow.workflow_id,
        supplier_name="Quote Atomic Supplier",
        priority=1,
        subject="Quote RFQ",
        body="Quote body",
        status="responded",
        responded_at=datetime(2026, 8, 13, 12, 30, 0),
    )
    workflow.rfq_ids = [draft.rfq_id]
    rfqs.save_workflow(workflow)
    rfqs.save_drafts([draft])
    rfqs.save_responses(
        [
            SupplierRFQResponse(
                rfq_id=draft.rfq_id,
                supplier_name=draft.supplier_name,
                rfq_priority=draft.priority,
                status="quoted",
                cost=1000,
                currency="EUR",
                received_at=datetime(2026, 8, 13, 12, 30, 0),
            )
        ]
    )
    selection = _selection_fixture(draft)

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        with patch(
            "src.workflow.supplier_rfq_progression.select_suppliers_for_shipment",
            return_value=selection,
        ):
            with patch.object(
                cases,
                "save",
                side_effect=InjectedPersistenceError("after approval write"),
            ):
                try:
                    resume_supplier_rfq_workflow(
                        workflow_id=workflow.workflow_id,
                        rfq_repository=rfqs,
                        approval_repository=approvals,
                        quote_case_repository=cases,
                    )
                except InjectedPersistenceError:
                    pass
                else:
                    failures.append("quote progression failure did not propagate")

    _, reopened_rfqs, reopened_approvals, reopened_cases = _repositories(
        db_path,
        "quote-reopen",
    )
    reopened_workflow = reopened_rfqs.get_workflow(workflow.workflow_id)
    if reopened_approvals.list_all() or reopened_cases.list_all():
        failures.append("quote rollback left orphan approval or case")
    if (
        reopened_workflow is None
        or reopened_workflow.quote_progression_status != "ready"
        or reopened_workflow.quote_progression_attempt_count != 0
    ):
        failures.append("quote rollback left stale progression state")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        with patch(
            "src.workflow.supplier_rfq_progression.select_suppliers_for_shipment",
            return_value=selection,
        ):
            recovered = resume_supplier_rfq_workflow(
                workflow_id=workflow.workflow_id,
                rfq_repository=reopened_rfqs,
                approval_repository=reopened_approvals,
                quote_case_repository=reopened_cases,
            )
    if (
        recovered.get("quote_case") is None
        or len(reopened_approvals.list_all()) != 1
        or len(reopened_cases.list_all()) != 1
    ):
        failures.append("quote progression retry did not commit all artifacts")
    completed = reopened_rfqs.get_workflow(workflow.workflow_id)
    if completed is None or completed.quote_progression_status != "completed":
        failures.append("quote progression success did not complete workflow")
    try:
        resume_supplier_rfq_workflow(
            workflow_id=workflow.workflow_id,
            rfq_repository=reopened_rfqs,
            approval_repository=reopened_approvals,
            quote_case_repository=reopened_cases,
        )
    except SupplierRFQWorkflowProgressionError:
        pass
    else:
        failures.append("completed quote progression allowed duplicate retry")


def _extraction_resume_atomicity(failures: list[str], root: Path) -> None:
    db_path = root / "extraction-resume.sqlite3"
    store, rfqs, approvals, cases = _repositories(db_path, "extraction-fail")
    proposals = SQLiteExtractionProposalRepository(store)
    proposed = proposals.save(
        ShipmentExtractionProposal(
            inbound_mail=InboundMailEnvelope(
                body_text="Privacy-safe atomic extraction inquiry.",
                privacy_transformed=True,
            ),
            proposed_shipment=ShipmentProposalSnapshot.model_validate(
                _shipment().model_dump()
            ),
        )
    )
    confirmed = confirm_extraction_proposal(
        repository=proposals,
        proposal_id=proposed.proposal_id,
        operator_identity="atomic-extraction-operator",
    )
    original_save = proposals.save

    def fail_on_completed(proposal):
        if proposal.resume_status == "completed":
            raise InjectedPersistenceError("after deferred RFQ writes")
        return original_save(proposal)

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        with patch.object(proposals, "save", side_effect=fail_on_completed):
            try:
                resume_confirmed_extraction(
                    repository=proposals,
                    proposal_id=confirmed.proposal_id,
                    rfq_repository=rfqs,
                    approval_repository=approvals,
                    quote_case_repository=cases,
                    evidence_recorder=store,
                )
            except InjectedPersistenceError:
                pass
            else:
                failures.append("extraction final-write failure did not propagate")

    retry_store, retry_rfqs, retry_approvals, retry_cases = _repositories(
        db_path,
        "extraction-reopen",
    )
    retry_proposals = SQLiteExtractionProposalRepository(retry_store)
    durable = retry_proposals.get(confirmed.proposal_id)
    if retry_rfqs.list_drafts() or retry_rfqs.store.list_all(
        namespace=retry_rfqs.WORKFLOW_NAMESPACE
    ):
        failures.append("extraction rollback left deferred RFQ records")
    if durable is None or durable.resume_status != "not_started":
        failures.append("extraction rollback left a stale resume claim")

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        recovered = resume_confirmed_extraction(
            repository=retry_proposals,
            proposal_id=confirmed.proposal_id,
            rfq_repository=retry_rfqs,
            approval_repository=retry_approvals,
            quote_case_repository=retry_cases,
            evidence_recorder=retry_store,
        )
    completed = retry_proposals.get(confirmed.proposal_id)
    if (
        completed is None
        or completed.resume_status != "completed"
        or not recovered.get("supplier_rfq_drafts")
    ):
        failures.append("extraction rollback retry did not commit complete state")


def _extraction_stale_finalization(failures: list[str], root: Path) -> None:
    db_path = root / "extraction-stale.sqlite3"
    store, rfqs, approvals, cases = _repositories(db_path, "extract-stale-a")
    proposals = SQLiteExtractionProposalRepository(store)
    proposed = proposals.save(
        ShipmentExtractionProposal(
            inbound_mail=InboundMailEnvelope(
                body_text="Privacy-safe concurrent extraction inquiry.",
                privacy_transformed=True,
            ),
            proposed_shipment=ShipmentProposalSnapshot.model_validate(
                _shipment().model_dump()
            ),
        )
    )
    confirmed = confirm_extraction_proposal(
        repository=proposals,
        proposal_id=proposed.proposal_id,
        operator_identity="concurrent-extraction-operator",
    )
    first_snapshot = proposals.get(confirmed.proposal_id)
    second_snapshot = proposals.get(confirmed.proposal_id)

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        resume_confirmed_extraction(
            repository=proposals,
            proposal_id=confirmed.proposal_id,
            rfq_repository=rfqs,
            approval_repository=approvals,
            quote_case_repository=cases,
            evidence_recorder=store,
        )

    stale_workflow = SupplierRFQWorkflow(shipment=_shipment())
    stale_draft = SupplierRFQDraft(
        workflow_id=stale_workflow.workflow_id,
        supplier_name="Stale Extraction Supplier",
        priority=1,
        subject="Stale RFQ",
        body="Stale body",
    )
    stale_workflow.rfq_ids = [stale_draft.rfq_id]
    try:
        with store.transaction():
            _require_unchanged_resume_state(proposals, second_snapshot)
            rfqs.save_drafts([stale_draft])
            rfqs.save_workflow(stale_workflow)
            store.record_event(
                event_type="confirmed_extraction_resumed",
                entity_type="extraction_proposal",
                entity_id=confirmed.proposal_id,
                payload={"stale": True},
            )
    except ExtractionConfirmationTransitionError:
        pass
    else:
        failures.append("stale extraction completion was not rejected")

    stale_blocked = second_snapshot.model_copy(
        update={
            "resume_status": "provenance_blocked",
            "resume_started_at": datetime(2026, 8, 13, 13, 0, 0),
            "resume_attempt_count": second_snapshot.resume_attempt_count + 1,
            "last_resume_blocked_at": datetime(2026, 8, 13, 13, 1, 0),
            "last_resume_blocked_result_type": "data_provenance_blocked",
        }
    )
    try:
        with store.transaction():
            _require_unchanged_resume_state(proposals, second_snapshot)
            proposals.save(stale_blocked)
    except ExtractionConfirmationTransitionError:
        pass
    else:
        failures.append("stale extraction block downgraded completion")

    reopened_store, reopened_rfqs, _, _ = _repositories(
        db_path,
        "extract-stale-reopen",
    )
    reopened_proposals = SQLiteExtractionProposalRepository(reopened_store)
    durable = reopened_proposals.get(confirmed.proposal_id)
    completion_events = [
        event
        for event in reopened_store.list_events(
            entity_type="extraction_proposal",
            entity_id=confirmed.proposal_id,
        )
        if event["event_type"] == "confirmed_extraction_resumed"
    ]
    workflows = reopened_store.list_all(
        namespace=reopened_rfqs.WORKFLOW_NAMESPACE
    )
    drafts = reopened_rfqs.list_drafts()
    if durable is None or durable.resume_status != "completed":
        failures.append("stale extraction attempt changed completed state")
    if len(workflows) != 1 or not drafts:
        failures.append("concurrent extraction did not retain one RFQ set")
    if any(draft.workflow_id == stale_workflow.workflow_id for draft in drafts):
        failures.append("stale extraction created durable RFQ artifacts")
    if len(completion_events) != 1:
        failures.append("concurrent extraction created duplicate completion evidence")
    if first_snapshot != second_snapshot:
        failures.append("extraction attempts did not start from one snapshot")


def _rfq_stale_finalization(failures: list[str], root: Path) -> None:
    db_path = root / "rfq-stale.sqlite3"
    store, rfqs, approvals, cases = _repositories(db_path, "rfq-stale-a")
    workflow = SupplierRFQWorkflow(shipment=_shipment())
    draft = SupplierRFQDraft(
        workflow_id=workflow.workflow_id,
        supplier_name="Concurrent Quote Supplier",
        priority=1,
        subject="Concurrent RFQ",
        body="Concurrent body",
        status="responded",
        responded_at=datetime(2026, 8, 13, 14, 0, 0),
    )
    workflow.rfq_ids = [draft.rfq_id]
    rfqs.save_workflow(workflow)
    rfqs.save_drafts([draft])
    rfqs.save_responses(
        [
            SupplierRFQResponse(
                rfq_id=draft.rfq_id,
                supplier_name=draft.supplier_name,
                rfq_priority=1,
                status="quoted",
                cost=1000,
                currency="EUR",
                received_at=datetime(2026, 8, 13, 14, 0, 0),
            )
        ]
    )
    first_snapshot = rfqs.get_workflow(workflow.workflow_id)
    second_snapshot = rfqs.get_workflow(workflow.workflow_id)
    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        with patch(
            "src.workflow.supplier_rfq_progression.select_suppliers_for_shipment",
            return_value=_selection_fixture(draft),
        ):
            resume_supplier_rfq_workflow(
                workflow_id=workflow.workflow_id,
                rfq_repository=rfqs,
                approval_repository=approvals,
                quote_case_repository=cases,
            )

    stale_approval = QuoteApproval(quote_snapshot=_approval_snapshot())
    stale_case = QuoteCase(
        shipment=_shipment(),
        supplier_rfq_workflow_id=workflow.workflow_id,
        quote_approval=stale_approval,
    )
    try:
        with store.transaction():
            _require_unchanged_progression_state(rfqs, second_snapshot)
            approvals.save(stale_approval)
            cases.save(stale_case)
    except SupplierRFQWorkflowProgressionError:
        pass
    else:
        failures.append("stale quote completion was not rejected")

    stale_ready = second_snapshot.model_copy(
        update={
            "quote_progression_status": "ready",
            "quote_progression_attempt_count": 1,
        }
    )
    try:
        with store.transaction():
            _require_unchanged_progression_state(rfqs, second_snapshot)
            rfqs.save_workflow(stale_ready)
    except SupplierRFQWorkflowProgressionError:
        pass
    else:
        failures.append("stale ready result downgraded quote completion")

    reopened_store, reopened_rfqs, reopened_approvals, reopened_cases = (
        _repositories(db_path, "rfq-stale-reopen")
    )
    durable = reopened_rfqs.get_workflow(workflow.workflow_id)
    if durable is None or durable.quote_progression_status != "completed":
        failures.append("stale quote attempt changed completed workflow")
    if len(reopened_approvals.list_all()) != 1:
        failures.append("concurrent quote completion created duplicate approval")
    if len(reopened_cases.list_all()) != 1:
        failures.append("concurrent quote completion created duplicate case")
    if reopened_approvals.get(stale_approval.approval_id) is not None:
        failures.append("stale quote attempt persisted its approval")
    if reopened_cases.get(stale_case.case_id) is not None:
        failures.append("stale quote attempt persisted its case")
    if first_snapshot != second_snapshot:
        failures.append("quote attempts did not start from one snapshot")


def _approval_snapshot() -> QuoteApprovalSnapshot:
    return QuoteApprovalSnapshot.from_quote(
        supplier_quote=SupplierQuote(
            supplier_name="Approval Atomic Supplier",
            cost=1000,
            currency="EUR",
        ),
        customer_quote=CustomerQuote(
            supplier_cost=1000,
            margin_type="percentage",
            margin_value=15,
            final_price=1150,
            currency="EUR",
        ),
        quote_draft=QuoteDraft(
            subject="Atomic customer quote",
            body="Atomic customer quote body",
        ),
    )


def _set_approval_event_failure(db_path: Path, enabled: bool) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "DROP TRIGGER IF EXISTS fail_quote_approval_event"
        )
        if enabled:
            connection.execute(
                """CREATE TRIGGER fail_quote_approval_event
                BEFORE INSERT ON pilot_events
                WHEN NEW.event_type = 'quote_approval_saved'
                BEGIN
                    SELECT RAISE(ABORT, 'injected approval event failure');
                END"""
            )


def _approval_decision_atomicity(failures: list[str], root: Path) -> None:
    db_path = root / "approval.sqlite3"
    _, _, approvals, cases = _repositories(db_path, "approval-setup")
    actions = (
        (
            "approved",
            lambda repository, approval_id: approve_quote(
                repository,
                approval_id,
                approved_by="atomic-approver",
            ),
        ),
        (
            "rejected",
            lambda repository, approval_id: reject_quote(
                repository,
                approval_id,
                rejection_reason="Atomic rejection",
                rejected_by="atomic-rejector",
            ),
        ),
        (
            "invalidated",
            lambda repository, approval_id: invalidate_quote_approval(
                repository,
                approval_id,
                invalidated_by="atomic-invalidator",
            ),
        ),
    )
    for expected_status, action in actions:
        pending = approvals.save(QuoteApproval(quote_snapshot=_approval_snapshot()))
        quote_case = cases.save(
            QuoteCase(
                shipment=_shipment(),
                quote_approval=pending,
            )
        )
        _set_approval_event_failure(db_path, True)
        try:
            action(approvals, pending.approval_id)
        except sqlite3.IntegrityError:
            pass
        else:
            failures.append(
                f"{expected_status} approval event failure did not propagate"
            )
        finally:
            _set_approval_event_failure(db_path, False)

        _, _, reopened_approvals, reopened_cases = _repositories(
            db_path,
            f"approval-{expected_status}-reopen",
        )
        durable = reopened_approvals.get(pending.approval_id)
        durable_case = reopened_cases.get(quote_case.case_id)
        if durable is None or durable.approval_status != "pending":
            failures.append(
                f"{expected_status} rollback left a partial approval decision"
            )
        if (
            durable_case is None
            or durable_case.quote_approval is None
            or durable_case.quote_approval.approval_status != "pending"
        ):
            failures.append("approval rollback changed quote-case snapshot")
        completed = action(reopened_approvals, pending.approval_id)
        if completed.approval_status != expected_status:
            failures.append(
                f"{expected_status} approval retry did not complete"
            )
        approvals = reopened_approvals
        cases = reopened_cases


def _store_transaction_contract(failures: list[str], root: Path) -> None:
    db_path = root / "store-transaction.sqlite3"
    store = SQLitePilotStore(db_path, run_id="store-fail")
    try:
        with store.transaction():
            store.upsert(
                namespace="atomic_test",
                record_key="rolled-back",
                payload={"state": "partial"},
                event_type="atomic_test_saved",
                entity_type="atomic_test",
            )
            raise InjectedPersistenceError("rollback contract")
    except InjectedPersistenceError:
        pass
    else:
        failures.append("transaction exception was suppressed")
    reopened = SQLitePilotStore(db_path, run_id="store-reopen")
    if reopened.get(namespace="atomic_test", record_key="rolled-back"):
        failures.append("explicit transaction rollback retained state")
    if any(
        event["entity_id"] == "rolled-back"
        for event in reopened.list_events(entity_type="atomic_test")
    ):
        failures.append("explicit transaction rollback retained evidence")

    repository = SQLiteQuoteApprovalRepository(reopened)
    joined_approval = QuoteApproval(quote_snapshot=_approval_snapshot())
    try:
        with reopened.transaction():
            repository.save(joined_approval)
            raise InjectedPersistenceError("repository joined outer transaction")
    except InjectedPersistenceError:
        pass
    joined_reopen = SQLitePilotStore(db_path, run_id="joined-reopen")
    joined_repository = SQLiteQuoteApprovalRepository(joined_reopen)
    if joined_repository.get(joined_approval.approval_id) is not None:
        failures.append("repository save committed its outer transaction")
    if any(
        event["entity_id"] == joined_approval.approval_id
        for event in joined_reopen.list_events(entity_type="quote_approval")
    ):
        failures.append("repository evidence committed its outer transaction")

    try:
        with reopened.transaction():
            with reopened.transaction():
                pass
    except SQLiteTransactionError:
        pass
    else:
        failures.append("nested transaction was not rejected explicitly")


def evaluate_atomic_transition_regressions() -> dict:
    failures: list[str] = []
    with TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _rfq_creation_atomicity(failures, root)
        _response_atomicity(failures, root)
        _ingestion_marker_atomicity(failures, root)
        _quote_progression_atomicity(failures, root)
        _extraction_resume_atomicity(failures, root)
        _extraction_stale_finalization(failures, root)
        _rfq_stale_finalization(failures, root)
        _approval_decision_atomicity(failures, root)
        _store_transaction_contract(failures, root)
    return {
        "name": "Atomic multi-record workflow transitions",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_atomic_transition_regressions()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
