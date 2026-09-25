from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.inbound_sender_review_repository import (
    InMemoryInboundSenderReviewRepository,
    SQLiteInboundSenderReviewRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.operation_execution_repository import InMemoryOperationExecutionRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.operational_work_queue import build_operational_work_queue
from src.core.operations_dashboard import build_operations_dashboard
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.workflow.inbound_sender_review import (
    capture_inbound_sender_review,
    resolve_inbound_sender_review,
)
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail


UTC = timezone.utc
NOW = datetime(2026, 9, 25, 9, 30, tzinfo=UTC)
MAILBOX = "info@agency.test"
SENDER = "new.customer@example.test"


def _mail(message_id: str = "unknown-customer-001") -> InboundMailEnvelope:
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id=MAILBOX,
        sender_address=SENDER,
        sender_name="New Customer Contact",
        recipient_addresses=[MAILBOX],
        to_addresses=[MAILBOX],
        subject="Adana Münih 20 ton taşıma talebi",
        body_text="Adana yükleme, Münih teslim, 20 ton tekstil. Tenteli fiyat rica ederiz.",
        received_at=NOW,
        source="email",
    )


def _shipment() -> ShipmentProposalSnapshot:
    return ShipmentProposalSnapshot(
        customer_name="Unknown Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Münih",
        commodity="Tekstil",
        gross_weight_kg=20_000,
        equipment_type="tenteli",
        transport_mode="road",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
    )


def evaluate_inbound_sender_review_regressions():
    failures = []
    passes = []

    def check(condition, message):
        (passes if condition else failures).append(message)

    reviews = InMemoryInboundSenderReviewRepository()
    mail = _mail()
    blocked = {
        "result_type": "inbound_sender_verification_required",
        "ingestion_status": "blocked",
        "reason_code": "sender_not_in_verified_inbound_scope",
        "inbound_route": "manual_review",
    }
    review = capture_inbound_sender_review(
        mail=mail,
        result=blocked,
        repository=reviews,
        now=NOW,
    )
    duplicate = capture_inbound_sender_review(
        mail=mail,
        result=blocked,
        repository=reviews,
        now=NOW,
    )
    dumped = review.model_dump(mode="json")
    check(
        review is not None
        and duplicate is not None
        and duplicate.review_id == review.review_id
        and review.status == "pending",
        "unknown verified-scope sender creates one durable idempotent operator review",
    )
    check(
        "body_text" not in dumped
        and "raw_body_sha256" not in dumped
        and review.subject == mail.subject
        and review.sender_address == SENDER,
        "sender review persists safe routing metadata without copying raw mail body",
    )

    queue = build_operational_work_queue(
        attachment_repository=InMemoryAttachmentInterpretationReviewRepository(),
        proposal_repository=InMemoryExtractionProposalRepository(),
        supplier_repository=InMemorySupplierRFQRepository(),
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        inbound_sender_review_repository=reviews,
        now=NOW,
    )
    queue_item = next(
        (item for item in queue["items"] if item["work_type"] == "inbound_sender_verification"),
        None,
    )
    check(
        queue_item is not None
        and queue_item["resource_id"] == review.review_id
        and queue_item["next_action"] == "verify_inbound_sender"
        and queue_item["priority_band"] in {"high", "critical"},
        "pending sender review becomes a first-class operational work item",
    )

    dashboard = build_operations_dashboard(
        mina_repository=InMemoryMinaJobRepository(),
        operation_repository=InMemoryOperationExecutionRepository(),
        inbound_sender_review_repository=reviews,
        now=NOW,
    )
    check(
        dashboard["summary"]["inbound_review_count"] == 1
        and dashboard["summary"]["attention_total"] == 1
        and dashboard["inbound_attention"][0]["review_id"] == review.review_id,
        "pending sender review is visible on the main operations dashboard attention surface",
    )

    masters = InMemoryMasterDataRepository()
    proposals = InMemoryExtractionProposalRepository()
    supplier_repo = InMemorySupplierRFQRepository()

    def _reprocess(_review):
        return process_controlled_outlook_inbound_mail(
            mail=mail,
            shipment_parser=lambda _safe_text: _shipment(),
            supplier_parser=None,
            proposal_repository=proposals,
            supplier_repository=supplier_repo,
            operational_data_sources=None,
            master_data_repository=masters,
        )

    import src.api as api

    request = api.InboundSenderResolveRequest(
        subject_type="customer",
        subject_name="New Customer Ltd.",
    )
    with patch.object(api, "master_data_repository", masters), patch.object(
        api, "inbound_sender_review_repository", reviews
    ), patch.object(
        api, "_authenticated_operator", return_value="Regression Operator"
    ), patch.object(
        api, "_reprocess_verified_review_mail", side_effect=_reprocess
    ):
        response = api.resolve_inbound_sender_review_endpoint(
            review.review_id,
            request,
            object(),
        )

    customers = masters.list_customers()
    proposal_list = proposals.list_all()
    resolved = reviews.get(review.review_id)
    check(
        len(customers) == 1
        and customers[0].customer_name == "New Customer Ltd."
        and SENDER in customers[0].trusted_sender_addresses
        and resolved is not None
        and resolved.status == "resolved"
        and resolved.resolution == "new_customer",
        "operator can create a customer master directly from the review and trust only the exact sender address",
    )
    check(
        len(proposal_list) == 1
        and proposal_list[0].trusted_customer_name == "New Customer Ltd."
        and response["reprocess_result"]["proposal_id"] == proposal_list[0].proposal_id,
        "customer verification immediately reprocesses the same mail into the normal extraction proposal path",
    )

    dashboard_after = build_operations_dashboard(
        mina_repository=InMemoryMinaJobRepository(),
        operation_repository=InMemoryOperationExecutionRepository(),
        inbound_sender_review_repository=reviews,
        now=NOW,
    )
    check(
        dashboard_after["summary"]["inbound_review_count"] == 0
        and not dashboard_after["inbound_attention"],
        "resolved sender review disappears from dashboard attention without deleting its audit record",
    )

    second_mail = _mail("irrelevant-001")
    second_review = capture_inbound_sender_review(
        mail=second_mail,
        result=blocked,
        repository=reviews,
        now=NOW,
    )
    dismissed = resolve_inbound_sender_review(
        review=second_review,
        repository=reviews,
        resolution="irrelevant",
        resolved_by="Regression Operator",
        resolution_note="Taşıma talebi değil",
        now=NOW,
    )
    queue_after = build_operational_work_queue(
        attachment_repository=InMemoryAttachmentInterpretationReviewRepository(),
        proposal_repository=proposals,
        supplier_repository=supplier_repo,
        approval_repository=InMemoryQuoteApprovalRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        inbound_sender_review_repository=reviews,
        now=NOW,
    )
    check(
        dismissed.status == "dismissed"
        and all(
            item["resource_id"] != second_review.review_id
            for item in queue_after["items"]
        ),
        "operator can dismiss non-work mail and it leaves the active work queue while remaining auditable",
    )


    with TemporaryDirectory() as tempdir:
        db_path = Path(tempdir) / "pilot.sqlite3"
        store = SQLitePilotStore(db_path, retention_days=90)
        sqlite_reviews = SQLiteInboundSenderReviewRepository(store)
        sqlite_review = capture_inbound_sender_review(
            mail=_mail("sqlite-review-001"),
            result=blocked,
            repository=sqlite_reviews,
            now=NOW,
        )
        reopened = SQLiteInboundSenderReviewRepository(
            SQLitePilotStore(db_path, retention_days=90)
        ).get(sqlite_review.review_id)
        check(
            reopened is not None
            and reopened.status == "pending"
            and reopened.sender_address == SENDER,
            "sender review survives SQLite repository reconstruction and remains pending until operator resolution",
        )

    check(
        route_allowed("GET", "/inbound-sender-reviews")
        and route_allowed("POST", f"/inbound-sender-reviews/{review.review_id}/resolve")
        and route_allowed("POST", f"/inbound-sender-reviews/{review.review_id}/dismiss")
        and not route_allowed("DELETE", f"/inbound-sender-reviews/{review.review_id}"),
        "controlled pilot explicitly allowlists only the bounded sender-review read and decision surfaces",
    )

    return {
        "name": "Inbound sender review and dashboard",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_inbound_sender_review_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print(
        "\nInbound sender review regressions:",
        "PASS" if result["passed"] else "FAIL",
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
