from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src import api
from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.attachment_interpretation_review_service import (
    create_attachment_interpretation_review,
)
from src.core.extraction_confirmation import (
    ShipmentExtractionProposal,
    ShipmentProposalSnapshot,
)
from src.core.extraction_confirmation_repository import (
    InMemoryExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.models import Shipment
from src.core.operational_work_queue import build_operational_work_queue
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case import CustomerQuoteManualSentEvidence, QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQFollowUpDraft,
    SupplierRFQFollowUpManualSentEvidence,
    SupplierRFQWorkflow,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.simulation.attachment_interpretation_review_regressions import (
    _customer_interpretation,
    _retrieval,
)
from src.simulation.outlook_inbound_router_regressions import CUSTOMER_EMAIL, _mail

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


def _proposal(
    *,
    proposal_id: str,
    received_at: datetime | None,
    required_delivery_date: str | None,
    cargo_ready_date: str | None = None,
) -> ShipmentExtractionProposal:
    mail = InboundMailEnvelope(
        external_message_id=f"msg-{proposal_id}",
        provider_name="microsoft_graph",
        mailbox_id="pilot@example.invalid",
        sender_address="private-customer@example.invalid",
        subject="PRIVATE CUSTOMER SUBJECT",
        body_text="Privacy-sensitive customer request.",
        received_at=received_at,
        source="email",
    )
    candidate = ShipmentProposalSnapshot(
        customer_name="PRIVATE CUSTOMER NAME",
        pickup_city="Adana",
        delivery_city="Hamburg",
        commodity="Textile",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date=cargo_ready_date,
        required_delivery_date=required_delivery_date,
        is_adr=None,
        is_temperature_controlled=None,
        is_high_value=None,
    )
    return ShipmentExtractionProposal(
        proposal_id=proposal_id,
        inbound_mail=mail,
        proposed_shipment=candidate,
    )


def _workflow(workflow_id: str, *, required_delivery_date: str | None) -> SupplierRFQWorkflow:
    return SupplierRFQWorkflow(
        workflow_id=workflow_id,
        shipment=Shipment(
            customer_name="PRIVATE WORKFLOW CUSTOMER",
            required_delivery_date=required_delivery_date,
            cargo_ready_date="2026-09-01",
        ),
    )


def _rfq(
    *,
    rfq_id: str,
    workflow_id: str,
    status: str = "clarification_required",
    created_at: datetime | None = None,
) -> SupplierRFQDraft:
    return SupplierRFQDraft(
        rfq_id=rfq_id,
        workflow_id=workflow_id,
        supplier_name="PRIVATE SUPPLIER NAME",
        priority=1,
        recipient_email="private-supplier@example.invalid",
        subject="PRIVATE SUPPLIER SUBJECT",
        body="PRIVATE SUPPLIER BODY",
        status=status,
        created_at=(created_at or NOW - timedelta(hours=6)).replace(tzinfo=None),
        responded_at=(NOW - timedelta(hours=5)).replace(tzinfo=None)
        if status == "clarification_required"
        else None,
    )


def _follow_up(
    *,
    follow_up_id: str,
    rfq_id: str,
    workflow_id: str,
    status: str,
) -> SupplierRFQFollowUpDraft:
    return SupplierRFQFollowUpDraft(
        follow_up_id=follow_up_id,
        rfq_id=rfq_id,
        workflow_id=workflow_id,
        sequence_number=1,
        recipient_email="private-supplier@example.invalid",
        subject="PRIVATE FOLLOW UP SUBJECT",
        body="PRIVATE FOLLOW UP BODY",
        rejection_reasons=["private-detail-that-must-not-leak"],
        status=status,
        created_at=(NOW - timedelta(hours=8)).replace(tzinfo=None),
    )


def _approval(
    *,
    approval_id: str,
    status: str = "pending",
    validity: str | None = "2026-09-01",
) -> QuoteApproval:
    kwargs = {}
    if status == "approved":
        kwargs = {
            "approved_by": "Regression Operator",
            "approved_at": (NOW - timedelta(hours=1)).replace(tzinfo=None),
        }
    return QuoteApproval(
        approval_id=approval_id,
        approval_status=status,
        created_at=(NOW - timedelta(hours=10)).replace(tzinfo=None),
        quote_snapshot=QuoteApprovalSnapshot(
            supplier_name="PRIVATE QUOTE SUPPLIER",
            supplier_cost=999999.0,
            final_price=1111111.0,
            currency="EUR",
            supplier_validity_date=validity,
            supplier_vehicle_available_date="next Friday",
            quote_subject="PRIVATE QUOTE SUBJECT",
            quote_body="PRIVATE QUOTE BODY",
        ),
        **kwargs,
    )


def _fixture():
    attachment_reviews = InMemoryAttachmentInterpretationReviewRepository()
    proposals = InMemoryExtractionProposalRepository()
    suppliers = InMemorySupplierRFQRepository()
    approvals = InMemoryQuoteApprovalRepository()
    quote_cases = InMemoryQuoteCaseRepository()

    attachment = create_attachment_interpretation_review(
        mail=_mail(
            sender=CUSTOMER_EMAIL,
            message_id="p1-61-attachment",
            has_attachments=True,
            attachment_manifest=[],
        ),
        retrieval=_retrieval("6"),
        interpretation=_customer_interpretation(),
        repository=attachment_reviews,
        supplier_repository=suppliers,
        trusted_customer_name="PRIVATE ATTACHMENT CUSTOMER",
    ).model_copy(update={"created_at": NOW - timedelta(hours=3)})
    attachment_reviews.save(attachment)

    proposals.save(
        _proposal(
            proposal_id="proposal-human",
            received_at=NOW - timedelta(hours=6),
            required_delivery_date="2026-09-01",
        )
    )
    confirmed = _proposal(
        proposal_id="proposal-confirmed",
        received_at=NOW - timedelta(hours=20),
        required_delivery_date="2026-09-01",
    ).model_copy(
        update={
            "extraction_status": "confirmed",
            "confirmed_shipment": Shipment(customer_name="PRIVATE CONFIRMED CUSTOMER"),
            "confirmed_by": "Regression Operator",
            "confirmed_at": NOW - timedelta(hours=19),
        }
    )
    proposals.save(ShipmentExtractionProposal.model_validate(confirmed.model_dump(exclude_computed_fields=True)))

    for suffix, status in (("draft", "draft"), ("approved", "approved"), ("waiting", "awaiting_response")):
        workflow_id = f"workflow-{suffix}"
        rfq_id = f"rfq-{suffix}"
        suppliers.save_workflow(_workflow(workflow_id, required_delivery_date="2026-09-02"))
        suppliers.save_drafts([_rfq(rfq_id=rfq_id, workflow_id=workflow_id)])
        suppliers.save_follow_up_drafts([
            _follow_up(
                follow_up_id=f"follow-{suffix}",
                rfq_id=rfq_id,
                workflow_id=workflow_id,
                status=status,
            )
        ])

    suppliers.save_workflow(_workflow("workflow-gap", required_delivery_date="2026-09-01"))
    suppliers.save_drafts([_rfq(rfq_id="rfq-gap", workflow_id="workflow-gap")])

    pending_approval = approvals.save(_approval(approval_id="approval-pending"))
    approved_approval = approvals.save(_approval(approval_id="approval-approved", status="approved"))
    freeform_approval = approvals.save(_approval(approval_id="approval-freeform", validity="tomorrow"))
    approvals.save(_approval(approval_id="approval-orphan", validity="2026-09-15"))
    for case_id, approval in (
        ("case-pending", pending_approval),
        ("case-approved", approved_approval),
        ("case-freeform", freeform_approval),
    ):
        quote_cases.save(QuoteCase(
            case_id=case_id,
            shipment=Shipment(customer_name="PRIVATE CASE CUSTOMER"),
            quote_approval=approval,
        ))
    return attachment_reviews, proposals, suppliers, approvals, quote_cases


def _state_snapshot(attachment_reviews, proposals, suppliers, approvals, quote_cases):
    return {
        "attachments": [item.model_dump(mode="json") for item in attachment_reviews.list_all()],
        "proposals": [item.model_dump(mode="json") for item in proposals.list_all()],
        "rfqs": [item.model_dump(mode="json") for item in suppliers.list_drafts()],
        "follow_ups": [item.model_dump(mode="json") for item in suppliers.list_follow_up_drafts()],
        "approvals": [item.model_dump(mode="json") for item in approvals.list_all()],
        "quote_cases": [item.model_dump(mode="json") for item in quote_cases.list_all()],
    }



def _follow_up_conflict_queue():
    suppliers = InMemorySupplierRFQRepository()
    workflow = _workflow("workflow-conflict", required_delivery_date="2026-09-02")
    suppliers.save_workflow(workflow)
    suppliers.save_drafts([_rfq(rfq_id="rfq-conflict", workflow_id=workflow.workflow_id)])
    first = _follow_up(
        follow_up_id="follow-conflict-one",
        rfq_id="rfq-conflict",
        workflow_id=workflow.workflow_id,
        status="approved",
    )
    second = _follow_up(
        follow_up_id="follow-conflict-two",
        rfq_id="rfq-conflict",
        workflow_id=workflow.workflow_id,
        status="draft",
    )
    suppliers.save_follow_up_drafts([first, second])
    suppliers.save_follow_up_manual_sent_evidence(
        SupplierRFQFollowUpManualSentEvidence(
            follow_up_id=first.follow_up_id,
            rfq_id=first.rfq_id,
            sequence_number=1,
            recorded_by="Regression Operator",
            recorded_at=NOW,
        )
    )
    return build_operational_work_queue(
        attachment_repository=InMemoryAttachmentInterpretationReviewRepository(),
        proposal_repository=InMemoryExtractionProposalRepository(),
        supplier_repository=suppliers,
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        now=NOW,
    )



def _sent_approval_conflict_queue():
    approval = _approval(
        approval_id="approval-sent-conflict",
        validity="2026-09-15",
    )
    approvals = InMemoryQuoteApprovalRepository()
    approvals.save(approval)
    cases = InMemoryQuoteCaseRepository()
    cases.save(
        QuoteCase(
            case_id="case-sent-conflict",
            shipment=Shipment(customer_name="PRIVATE SENT CUSTOMER"),
            quote_approval=approval,
            manual_sent_evidence=[
                CustomerQuoteManualSentEvidence(
                    case_id="case-sent-conflict",
                    approval_id=approval.approval_id,
                    revision_number=0,
                    recipient_email="private-customer@example.invalid",
                    sent_by="Regression Operator",
                    sent_at=NOW,
                )
            ],
        )
    )
    return build_operational_work_queue(
        attachment_repository=InMemoryAttachmentInterpretationReviewRepository(),
        proposal_repository=InMemoryExtractionProposalRepository(),
        supplier_repository=InMemorySupplierRFQRepository(),
        approval_repository=approvals,
        quote_case_repository=cases,
        now=NOW,
    )


def evaluate_operational_work_queue_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachment_reviews, proposals, suppliers, approvals, quote_cases = _fixture()
    before = _state_snapshot(attachment_reviews, proposals, suppliers, approvals, quote_cases)
    queue = build_operational_work_queue(
        attachment_repository=attachment_reviews,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=quote_cases,
        now=NOW,
    )
    after = _state_snapshot(attachment_reviews, proposals, suppliers, approvals, quote_cases)
    items = queue["items"]
    types = [item["work_type"] for item in items]

    check(
        queue["pending_count"] == 8
        and types.count("attachment_review") == 1
        and types.count("customer_extraction_confirmation") == 1
        and types.count("supplier_follow_up") == 2
        and types.count("supplier_clarification_gap") == 1
        and types.count("quote_approval") == 3
        and "proposal-confirmed" not in repr(queue)
        and "follow-waiting" not in repr(queue)
        and "approval-approved" not in repr(queue),
        "unified queue contains only active human work across all supported work types",
    )

    proposal_item = next(item for item in items if item["resource_id"] == "proposal-human")
    gap_item = next(item for item in items if item["resource_id"] == "rfq-gap")
    pending_approval = next(item for item in items if item["resource_id"] == "approval-pending")
    check(
        proposal_item["priority_band"] == "critical"
        and proposal_item["critical_attention_count"] == 3
        and "customer_safety_fields_unknown" in proposal_item["priority_reasons"]
        and gap_item["priority_band"] == "critical"
        and gap_item["blocker_count"] == 1
        and "clarification_required_without_active_follow_up" in gap_item["priority_reasons"]
        and pending_approval["priority_band"] in {"high", "critical"}
        and pending_approval["days_until_nearest_deadline"] == 0,
        "safety, clarification gaps and exact commercial deadlines drive cross-work priority",
    )

    draft_follow = next(item for item in items if item["resource_id"] == "follow-draft")
    approved_follow = next(item for item in items if item["resource_id"] == "follow-approved")
    check(
        draft_follow["next_action"] == "approve_supplier_follow_up"
        and approved_follow["next_action"] == "send_supplier_follow_up"
        and approved_follow["priority_score"] > draft_follow["priority_score"],
        "supplier follow-up state maps to the correct human next action",
    )

    freeform = next(item for item in items if item["resource_id"] == "approval-freeform")
    check(
        "days_until_nearest_deadline" not in freeform
        and "nearest_deadline_kind" not in freeform,
        "free-form commercial dates are never guessed into unified queue deadlines",
    )

    orphan = next(item for item in items if item["resource_id"] == "approval-orphan")
    check(
        orphan["priority_band"] == "critical"
        and orphan["blocker_count"] == 1
        and orphan["next_action"] == "inspect_quote_approval_state"
        and "quote_approval_case_missing" in orphan["priority_reasons"],
        "orphan pending quote approval is surfaced as blocked operational work",
    )

    conflict_items = {
        item["resource_id"]: item
        for item in _follow_up_conflict_queue()["items"]
    }
    check(
        conflict_items["follow-conflict-one"]["next_action"]
        == "inspect_supplier_follow_up"
        and conflict_items["follow-conflict-one"]["blocker_count"] >= 2
        and "supplier_follow_up_send_evidence_state_conflict"
        in conflict_items["follow-conflict-one"]["priority_reasons"]
        and conflict_items["follow-conflict-two"]["next_action"]
        == "inspect_supplier_follow_up"
        and "multiple_active_supplier_follow_ups"
        in conflict_items["follow-conflict-two"]["priority_reasons"],
        "supplier duplicate/send-evidence conflicts block action suggestions",
    )

    sent_item = _sent_approval_conflict_queue()["items"][0]
    check(
        sent_item["next_action"] == "inspect_quote_approval_state"
        and sent_item["blocker_count"] == 1
        and "quote_sent_while_approval_pending" in sent_item["priority_reasons"],
        "pending approval with prior send evidence is blocked instead of accelerated",
    )

    representation = repr(queue)
    check(
        "PRIVATE CUSTOMER NAME" not in representation
        and "PRIVATE CUSTOMER SUBJECT" not in representation
        and "private-customer@example.invalid" not in representation
        and "PRIVATE SUPPLIER NAME" not in representation
        and "PRIVATE FOLLOW UP BODY" not in representation
        and "private-detail-that-must-not-leak" not in representation
        and "PRIVATE QUOTE SUBJECT" not in representation
        and "999999" not in representation
        and "sha256" not in representation
        and "preview_token" not in representation,
        "unified operational queue remains privacy-minimal across work types",
    )
    check(before == after, "building unified operational queue is mutation-free")

    with (
        patch.object(api, "attachment_review_repository", attachment_reviews),
        patch.object(api, "extraction_proposal_repository", proposals),
        patch.object(api, "supplier_rfq_repository", suppliers),
        patch.object(api, "quote_approval_repository", approvals),
        patch.object(api, "quote_case_repository", quote_cases),
    ):
        api_queue = api.list_operational_work_queue()
    check(
        api_queue["pending_count"] == queue["pending_count"]
        and api_queue["work_type_counts"] == queue["work_type_counts"],
        "authenticated API exposes the same deterministic unified work queue",
    )

    return {
        "name": "Unified operational work queue",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_work_queue_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational work queue regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
