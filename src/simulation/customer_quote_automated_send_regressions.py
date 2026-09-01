from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import src.api as controlled_api
from src.core.mail import MailSendResult
from src.core.models import CustomerQuote, QuoteDraft, Shipment, SupplierQuote
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_automated_sent import (
    CustomerQuoteAutomatedSentTransitionError,
    send_customer_quote_and_record,
)
from src.core.quote_case import QuoteCase
from src.core.quote_manual_sent import (
    CustomerQuoteManualSentTransitionError,
    record_customer_quote_manually_sent,
)
from src.core.sqlite_repositories import SQLiteQuoteApprovalRepository, SQLiteQuoteCaseRepository


class _Sender:
    def __init__(self, status: str = "sent"):
        self.status = status
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        if self.status == "sent":
            return MailSendResult(
                operation_id=request.operation_id,
                status="sent",
                reason="accepted",
                provider_name="synthetic_provider",
                provider_message_id="provider-ref-1",
                sent_at=datetime(2026, 9, 1, 12, 0, 0),
            )
        return MailSendResult(
            operation_id=request.operation_id,
            status="failed",
            reason="synthetic failure",
        )


def _setup(root: Path):
    store = SQLitePilotStore(root / "pilot.sqlite3", run_id="customer-auto-send")
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
        approval_status="approved",
        approved_by="Tan",
        approved_at=datetime(2026, 9, 1, 11, 0, 0),
        quote_snapshot=snapshot,
    )
    case = QuoteCase(
        shipment=Shipment(customer_name="Customer"),
        supplier_quote=supplier_quote,
        customer_quote=customer_quote,
        quote_draft=quote_draft,
        quote_approval=approval,
    )
    approvals.save(approval)
    cases.save(case)
    return approvals, cases, approval, case


def evaluate_customer_quote_automated_send_regressions() -> dict:
    failures = []
    if not route_allowed("POST", "/quote-cases/case-1/send"):
        failures.append("controlled pilot customer quote send route is not allowed")
    route_paths = {r.path for r in controlled_api.app.routes if hasattr(r, "path")}
    if "/quote-cases/{case_id}/send" not in route_paths:
        failures.append("customer quote automated send API route is not exposed")

    with TemporaryDirectory(prefix="minai-customer-auto-send-") as temp_dir:
        approvals, cases, approval, case = _setup(Path(temp_dir))
        sender = _Sender()
        result = send_customer_quote_and_record(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=case.case_id,
            expected_approval_id=approval.approval_id,
            recipient_email="customer@example.com",
            sender=sender,
        )
        durable = cases.get(case.case_id)
        if result.delivery.status != "sent" or result.automated_sent_evidence is None:
            failures.append("successful provider send did not create automated evidence")
        elif durable is None or len(durable.automated_sent_evidence) != 1:
            failures.append("automated send evidence was not durable")
        else:
            evidence = durable.automated_sent_evidence[0]
            if evidence.provider_message_id != "provider-ref-1" or evidence.recipient_email != "customer@example.com":
                failures.append("automated send evidence lost provider or recipient metadata")

        try:
            send_customer_quote_and_record(
                quote_case_repository=cases,
                approval_repository=approvals,
                case_id=case.case_id,
                expected_approval_id=approval.approval_id,
                recipient_email="customer@example.com",
                sender=sender,
            )
        except CustomerQuoteAutomatedSentTransitionError:
            pass
        else:
            failures.append("duplicate automated customer quote send was not blocked")
        if len(sender.calls) != 1:
            failures.append("duplicate automated send reached provider")

        try:
            record_customer_quote_manually_sent(
                quote_case_repository=cases,
                approval_repository=approvals,
                case_id=case.case_id,
                expected_approval_id=approval.approval_id,
                recipient_email="customer@example.com",
                sent_by="Tan",
            )
        except CustomerQuoteManualSentTransitionError:
            pass
        else:
            failures.append("manual sent evidence was allowed after automated send")

    with TemporaryDirectory(prefix="minai-customer-auto-fail-") as temp_dir:
        approvals, cases, approval, case = _setup(Path(temp_dir))
        failed = send_customer_quote_and_record(
            quote_case_repository=cases,
            approval_repository=approvals,
            case_id=case.case_id,
            expected_approval_id=approval.approval_id,
            recipient_email="customer@example.com",
            sender=_Sender("failed"),
        )
        durable = cases.get(case.case_id)
        if failed.delivery.status != "failed":
            failures.append("synthetic provider failure was not preserved")
        if durable is None or durable.automated_sent_evidence:
            failures.append("provider failure created automated send evidence")

    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_customer_quote_automated_send_regressions()
    for failure in result["failures"]:
        print("FAIL", failure)
    if result["passed"]:
        print("PASS Customer quote automated send evidence")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
