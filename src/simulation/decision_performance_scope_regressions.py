from datetime import datetime, timedelta, timezone

from src.core.models import Shipment
from src.core.operation_start import OperationStartMessage
from src.core.operation_start_repository import InMemoryOperationStartMessageRepository
from src.core.quote_approval import QuoteApproval, QuoteApprovalSnapshot
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.reporting_read_model import _decision_performance

NOW = datetime(2026, 9, 7, 9, 0, tzinfo=timezone.utc)


def _approval(label: str, operator: str) -> QuoteApproval:
    return QuoteApproval(
        approval_status="approved", approved_by=operator, approved_at=NOW + timedelta(minutes=2),
        created_at=NOW,
        quote_snapshot=QuoteApprovalSnapshot(
            supplier_name=label, supplier_cost=1000, final_price=1200, currency="EUR",
            quote_subject="Acceptance test", quote_body="Acceptance test",
        ),
    )


def evaluate_decision_performance_scope_regressions() -> dict:
    failures, passes = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    quotes = InMemoryQuoteCaseRepository()
    messages = InMemoryOperationStartMessageRepository()
    shipment = Shipment(customer_name="Acceptance")
    linked = QuoteCase(shipment=shipment, mina_job_id="job-live", mina_code="MINA2026/1", quote_approval=_approval("Linked", "Operator A"))
    orphan = QuoteCase(shipment=shipment, quote_approval=_approval("Legacy orphan", "Legacy Operator"))
    quotes.save(linked); quotes.save(orphan)

    messages.save(OperationStartMessage(
        message_id="linked-message", job_id="job-live", mina_code="MINA2026/1",
        supplier_name="Carrier A", recipient_email="a@example.invalid", kind="supplier_closure",
        outbound_mode="approval_required", subject="Closure", body_text="Test closure",
        status="rejected", created_at=NOW, created_by="Operator A",
        decided_at=NOW + timedelta(minutes=1), decided_by="Operator A", decision_reason="Acceptance test rejection",
    ))
    messages.save(OperationStartMessage(
        message_id="orphan-message", job_id="missing-job", mina_code="MINA2026/999",
        supplier_name="Carrier B", recipient_email="b@example.invalid", kind="supplier_closure",
        outbound_mode="approval_required", subject="Closure", body_text="Test closure",
        status="rejected", created_at=NOW, created_by="Legacy Operator",
        decided_at=NOW + timedelta(minutes=1), decided_by="Legacy Operator", decision_reason="Legacy test rejection",
    ))

    report = _decision_performance(
        quote_case_repository=quotes, operation_start_repository=messages,
        valid_job_ids={"job-live"}, start_date=None, end_date=None, decision_target_minutes=15,
    )
    check(
        report["period_basis"] == "decision_created_at_istanbul"
        and report["summary"]["decision_count"] == 2
        and {row["name"] for row in report["rows"]} == {"Operator A"},
        "decision timing includes only decisions linked to an existing MINA job",
    )
    check(
        report["excluded_unlinked_quote_decision_count"] == 1
        and report["excluded_unlinked_operation_start_decision_count"] == 1,
        "legacy unlinked decision evidence remains visible as excluded coverage",
    )
    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_decision_performance_scope_regressions()
    for label in result["passes"]: print(f"PASS {label}")
    for label in result["failures"]: print(f"FAIL {label}")
    print("\nDecision performance scope regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
