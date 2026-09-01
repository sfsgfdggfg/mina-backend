from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.models import CustomerQuote, QuoteDraft, Shipment, SupplierQuote
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_approval_service import (
    approve_quote,
    invalidate_quote_approval,
    reject_quote,
)
from src.core.quote_case import QuoteCase
from src.core.quote_send_safety import evaluate_quote_send_safety
from src.core.sqlite_repositories import (
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
)


def _setup(root: Path):
    store = SQLitePilotStore(root / "pilot.sqlite3", run_id="approval-case-sync")
    approvals = SQLiteQuoteApprovalRepository(store)
    cases = SQLiteQuoteCaseRepository(store)
    supplier_quote = SupplierQuote(
        supplier_name="Carrier",
        cost=2400,
        currency="EUR",
        transit_time="5-7 days",
        equipment_type="Tenteli",
    )
    customer_quote = CustomerQuote(
        supplier_cost=2400,
        markup_type="percentage",
        markup_value=15,
        final_price=2760,
        currency="EUR",
    )
    quote_draft = QuoteDraft(subject="Offer", body="Offer 2760 EUR")
    snapshot = QuoteApprovalSnapshot.from_quote(
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )
    approval = QuoteApproval(
        approval_status="pending",
        quote_snapshot=snapshot,
    )
    initial_safety = evaluate_quote_send_safety(
        approval=approval,
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
    )
    case = QuoteCase(
        shipment=Shipment(customer_name="Customer"),
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        quote_approval=approval,
        quote_send_safety=initial_safety,
    )
    approvals.save(approval)
    cases.save(case)
    return approvals, cases, approval, case


def evaluate_quote_approval_case_sync_regressions() -> dict:
    failures = []

    with TemporaryDirectory(prefix="minai-approval-case-approve-") as temp_dir:
        approvals, cases, approval, case = _setup(Path(temp_dir))
        approve_quote(
            repository=approvals,
            approval_id=approval.approval_id,
            approved_by="Tan",
            approved_at=datetime(2026, 9, 1, 13, 0, 0),
            quote_case_repository=cases,
        )
        durable = cases.get(case.case_id)
        if durable is None or durable.quote_approval is None:
            failures.append("approved quote case was not durable")
        elif durable.quote_approval.approval_status != "approved":
            failures.append("approved quote case kept a stale approval snapshot")
        elif durable.quote_send_safety is None or not durable.quote_send_safety.can_send:
            failures.append("approved quote case did not persist send-ready safety")

        invalidate_quote_approval(
            repository=approvals,
            approval_id=approval.approval_id,
            invalidated_by="Tan",
            invalidated_at=datetime(2026, 9, 1, 13, 5, 0),
            quote_case_repository=cases,
        )
        durable = cases.get(case.case_id)
        if durable is None or durable.quote_approval is None:
            failures.append("invalidated quote case was not durable")
        elif durable.quote_approval.approval_status != "invalidated":
            failures.append("invalidated quote case kept a stale approval snapshot")
        elif (
            durable.quote_send_safety is None
            or durable.quote_send_safety.block_reason != "approval_invalidated"
        ):
            failures.append("invalidated quote case did not persist blocked send safety")

    with TemporaryDirectory(prefix="minai-approval-case-reject-") as temp_dir:
        approvals, cases, approval, case = _setup(Path(temp_dir))
        reject_quote(
            repository=approvals,
            approval_id=approval.approval_id,
            rejection_reason="Commercial review failed",
            rejected_by="Tan",
            rejected_at=datetime(2026, 9, 1, 14, 0, 0),
            quote_case_repository=cases,
        )
        durable = cases.get(case.case_id)
        if durable is None or durable.quote_approval is None:
            failures.append("rejected quote case was not durable")
        elif durable.quote_approval.approval_status != "rejected":
            failures.append("rejected quote case kept a stale approval snapshot")
        elif (
            durable.quote_send_safety is None
            or durable.quote_send_safety.block_reason != "approval_rejected"
        ):
            failures.append("rejected quote case did not persist blocked send safety")

    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_quote_approval_case_sync_regressions()
    for failure in result["failures"]:
        print("FAIL", failure)
    if result["passed"]:
        print("PASS Durable quote approval case sync")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
