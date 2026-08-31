from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.extraction_confirmation import ShipmentExtractionProposal, ShipmentProposalSnapshot
from src.core.mail import InboundMailEnvelope
from src.core.models import Shipment
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_case import QuoteCase
from src.core.sqlite_repositories import SQLiteExtractionProposalRepository, SQLiteQuoteApprovalRepository, SQLiteQuoteCaseRepository, SQLiteSupplierRFQRepository
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQFollowUpDraft,
    SupplierRFQFollowUpManualSentEvidence,
    SupplierRFQResponse,
    SupplierRFQWorkflow,
)
from src.core.supplier_rfq_repository import DuplicateSupplierRFQResponseError
from src.workflow.extraction_confirmation import (
    confirm_extraction_proposal,
    resume_confirmed_extraction,
)

def evaluate_pilot_persistence_regressions() -> dict:
    failures = []
    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "pilot.sqlite3"
        store1 = SQLitePilotStore(db_path, run_id="run-a")
        extraction1 = SQLiteExtractionProposalRepository(store1)
        rfq1 = SQLiteSupplierRFQRepository(store1)
        approvals1 = SQLiteQuoteApprovalRepository(store1)
        cases1 = SQLiteQuoteCaseRepository(store1)

        proposal = ShipmentExtractionProposal(
            inbound_mail=InboundMailEnvelope(body_text="Synthetic pilot inquiry", sender_address="ops@example.test", source="manual"),
            proposed_shipment=ShipmentProposalSnapshot(customer_name="Synthetic Customer", is_adr=False, is_temperature_controlled=False, is_high_value=False),
        )
        extraction1.save(proposal)

        confirmed = confirm_extraction_proposal(
            repository=extraction1,
            proposal_id=proposal.proposal_id,
            operator_identity="synthetic-operator",
        )
        resume_result = resume_confirmed_extraction(
            repository=extraction1,
            proposal_id=confirmed.proposal_id,
            rfq_repository=rfq1,
            approval_repository=approvals1,
            quote_case_repository=cases1,
            evidence_recorder=store1,
        )
        if not resume_result.get("result_type"):
            failures.append("confirmed extraction resume produced no result type")

        resumed_proposal = extraction1.get(proposal.proposal_id)
        if resumed_proposal is None:
            failures.append("resumed extraction proposal was not persisted")
        else:
            if resumed_proposal.resume_started_at is None:
                failures.append(
                    "durable resume-start claim was not retained"
                )
            if resumed_proposal.resumed_at is None:
                failures.append(
                    "completed extraction resume timestamp was not retained"
                )

        workflow = SupplierRFQWorkflow(shipment=Shipment(customer_name="Synthetic Customer"))
        draft = SupplierRFQDraft(workflow_id=workflow.workflow_id, supplier_name="Synthetic Supplier", priority=1, recipient_email="pricing@supplier.test", subject="Synthetic RFQ", body="Synthetic body")
        workflow.rfq_ids = [draft.rfq_id]
        rfq1.save_workflow(workflow)
        rfq1.save_drafts([draft])

        response = SupplierRFQResponse(rfq_id=draft.rfq_id, supplier_name=draft.supplier_name, rfq_priority=1, status="quoted", cost=1000, currency="EUR", source="manual")
        rfq1.save_responses([response])
        rfq1.record_ingested_message("mailbox:test-message-1")
        follow_up = SupplierRFQFollowUpDraft(
            rfq_id=draft.rfq_id,
            workflow_id=workflow.workflow_id,
            sequence_number=1,
            recipient_email=draft.recipient_email,
            subject=f"Re: {draft.subject}",
            body="Please provide transit time.",
            rejection_reasons=["supplier_transit_missing_or_unparseable"],
            status="awaiting_response",
        )
        follow_up_evidence = SupplierRFQFollowUpManualSentEvidence(
            follow_up_id=follow_up.follow_up_id,
            rfq_id=draft.rfq_id,
            sequence_number=1,
            recorded_by="synthetic-operator",
            recorded_at=follow_up.created_at,
        )
        rfq1.save_follow_up_drafts([follow_up])
        rfq1.save_follow_up_manual_sent_evidence(follow_up_evidence)

        approval = QuoteApproval(quote_snapshot=QuoteApprovalSnapshot(supplier_name="Synthetic Supplier", supplier_cost=1000, final_price=1150, currency="EUR", quote_subject="Synthetic quote", quote_body="Synthetic quote body"))
        approvals1.save(approval)
        quote_case = QuoteCase(shipment=Shipment(customer_name="Synthetic Customer"), supplier_rfq_workflow_id=workflow.workflow_id, quote_approval=approval)
        cases1.save(quote_case)

        store2 = SQLitePilotStore(db_path, run_id="run-b")
        extraction2 = SQLiteExtractionProposalRepository(store2)
        rfq2 = SQLiteSupplierRFQRepository(store2)
        approvals2 = SQLiteQuoteApprovalRepository(store2)
        cases2 = SQLiteQuoteCaseRepository(store2)

        if extraction2.get(proposal.proposal_id) is None: failures.append("extraction proposal did not survive restart")
        if rfq2.get_workflow(workflow.workflow_id) is None: failures.append("RFQ workflow did not survive restart")
        if rfq2.get_draft(draft.rfq_id) is None: failures.append("RFQ draft did not survive restart")
        if len(rfq2.list_responses(draft.rfq_id)) != 1: failures.append("RFQ response did not survive restart")
        if rfq2.get_follow_up_draft(follow_up.follow_up_id) is None:
            failures.append("Supplier RFQ follow-up draft did not survive restart")
        if len(rfq2.list_follow_up_manual_sent_evidence(follow_up.follow_up_id)) != 1:
            failures.append("Supplier RFQ follow-up send evidence did not survive restart")
        if not rfq2.has_ingested_message("mailbox:test-message-1"): failures.append("ingested-message dedup key did not survive restart")
        if approvals2.get(approval.approval_id) is None: failures.append("quote approval did not survive restart")
        if cases2.get(quote_case.case_id) is None: failures.append("quote case did not survive restart")
        try:
            rfq2.save_responses([response])
        except DuplicateSupplierRFQResponseError:
            pass
        else:
            failures.append("duplicate RFQ response was accepted after restart")
        events = store2.list_events()
        if len(events) < 9: failures.append("append-only pilot evidence events were not retained")
        if not any(event["run_id"] == "run-a" for event in events):
            failures.append("original process run_id was not retained in evidence")

        resume_events = [
            event
            for event in events
            if event["event_type"] == "confirmed_extraction_resumed"
            and event["entity_id"] == proposal.proposal_id
        ]
        if len(resume_events) != 1:
            failures.append(
                "full downstream workflow result evidence was not retained"
            )
        else:
            payload = resume_events[0]["payload"]

            if payload.get("result_type") != resume_result.get("result_type"):
                failures.append(
                    "durable workflow result type does not match runtime result"
                )

            if not isinstance(payload.get("result"), dict):
                failures.append(
                    "durable workflow result snapshot is missing"
                )

    return {
        "name": "Durable pilot persistence",
        "passed": len(failures) == 0,
        "failures": failures,
    }
