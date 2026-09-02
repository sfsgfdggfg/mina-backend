from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.operational_shift_summary import (
    SHIFT_HANDOFF_WINDOW_HOURS,
    build_operational_shift_summary,
)
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    acknowledge_operational_work,
    assign_operational_work_to_me,
    handoff_operational_work,
)
from src.core.operational_work_queue import build_operational_work_queue
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import (
    SQLiteAttachmentInterpretationReviewRepository,
    SQLiteExtractionProposalRepository,
    SQLiteOperationalWorkAssignmentRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.simulation.operational_work_queue_regressions import NOW, _fixture, _proposal


def _args(assignments, attachments, proposals, suppliers, approvals, cases):
    return {
        "assignment_repository": assignments,
        "attachment_repository": attachments,
        "proposal_repository": proposals,
        "supplier_repository": suppliers,
        "approval_repository": approvals,
        "quote_case_repository": cases,
    }


def _work_id(queue, resource_id: str) -> str:
    return next(item["work_id"] for item in queue["items"] if item["resource_id"] == resource_id)


def evaluate_operational_shift_summary_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachments, proposals, suppliers, approvals, cases = _fixture()
    assignments = InMemoryOperationalWorkAssignmentRepository()
    args = _args(assignments, attachments, proposals, suppliers, approvals, cases)
    queue = build_operational_work_queue(
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
        now=NOW,
    )
    proposal_id = _work_id(queue, "proposal-human")
    handoff_id = _work_id(queue, "follow-draft")
    other_handoff_id = _work_id(queue, "approval-pending")
    old_handoff_id = _work_id(queue, "approval-freeform")

    assign_operational_work_to_me(work_id=proposal_id, operator_name="Summary Operator", now=NOW, **args)
    acknowledge_operational_work(work_id=proposal_id, operator_name="Summary Operator", now=NOW + timedelta(minutes=1), **args)
    active = assignments.get(proposal_id)
    assignments.save(active.model_copy(update={"lease_expires_at": NOW + timedelta(minutes=4)}))

    assign_operational_work_to_me(work_id=handoff_id, operator_name="Summary Operator", now=NOW, **args)
    handed = handoff_operational_work(
        work_id=handoff_id,
        operator_name="Summary Operator",
        now=NOW + timedelta(minutes=2),
        **args,
    )
    successor = assign_operational_work_to_me(
        work_id=handoff_id,
        operator_name="Incoming Operator",
        now=NOW + timedelta(minutes=3),
        **args,
    )

    assign_operational_work_to_me(work_id=other_handoff_id, operator_name="Other Operator", now=NOW, **args)
    handoff_operational_work(
        work_id=other_handoff_id,
        operator_name="Other Operator",
        now=NOW + timedelta(minutes=2),
        **args,
    )

    old_start = NOW - timedelta(hours=SHIFT_HANDOFF_WINDOW_HOURS + 1)
    assign_operational_work_to_me(work_id=old_handoff_id, operator_name="Summary Operator", now=old_start, **args)
    handoff_operational_work(
        work_id=old_handoff_id,
        operator_name="Summary Operator",
        now=old_start + timedelta(minutes=1),
        **args,
    )

    before_history = len(assignments.list_history())
    before_counts = (
        len(proposals.list_all()), len(suppliers.list_drafts()),
        len(approvals.list_all()), len(cases.list_all()),
    )
    summary = build_operational_shift_summary(
        operator_name="Summary Operator",
        now=NOW + timedelta(minutes=3),
        **args,
    )
    after_counts = (
        len(proposals.list_all()), len(suppliers.list_drafts()),
        len(approvals.list_all()), len(cases.list_all()),
    )

    check(
        summary["scope"] == "authenticated_operator"
        and summary["overview"]["my_active_count"] == 1
        and summary["overview"]["my_expiring_soon_count"] == 1
        and summary["my_work"]["items"][0]["work_id"] == proposal_id,
        "shift summary includes only the operator's active personal work and lease attention",
    )
    handoff_items = summary["recent_handoffs"]["items"]
    check(
        len(handoff_items) == 1
        and handoff_items[0]["work_id"] == handoff_id
        and handoff_items[0]["current_disposition"] == "claimed"
        and successor.generation == handed.generation + 1,
        "recent handoff history survives successor claim and reports current disposition",
    )
    check(
        other_handoff_id not in {item["work_id"] for item in handoff_items}
        and old_handoff_id not in {item["work_id"] for item in handoff_items},
        "shift summary scopes handoffs to the authenticated operator and bounded window",
    )
    critical = summary["critical_unassigned"]["items"]
    check(
        critical
        and all(item["priority_band"] == "critical" for item in critical)
        and all(item["work_id"] != proposal_id for item in critical)
        and all(item["work_id"] != handoff_id for item in critical),
        "shift summary surfaces only critical currently-unassigned work",
    )
    rendered = repr(summary).lower()
    check(
        "work_state_sha256" not in rendered
        and "subject" not in rendered
        and "currency" not in rendered
        and "customer_name" not in rendered
        and "supplier_name" not in rendered,
        "shift summary remains privacy-minimal and excludes raw assignment event payloads",
    )
    check(
        len(assignments.list_history()) == before_history
        and before_counts == after_counts,
        "building shift summary is mutation-free",
    )

    request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Summary Operator"))
    with (
        patch.object(api, "operational_work_assignment_repository", assignments),
        patch.object(api, "attachment_review_repository", attachments),
        patch.object(api, "extraction_proposal_repository", proposals),
        patch.object(api, "supplier_rfq_repository", suppliers),
        patch.object(api, "quote_approval_repository", approvals),
        patch.object(api, "quote_case_repository", cases),
        patch.object(
            api,
            "build_operational_shift_summary",
            side_effect=lambda **kwargs: build_operational_shift_summary(
                now=NOW + timedelta(minutes=3), **kwargs
            ),
        ),
    ):
        api_summary = api.get_operational_work_shift_summary(request)
    check(
        api_summary["scope"] == "authenticated_operator"
        and api_summary["recent_handoffs"]["count"] == 1
        and "work_state_sha256" not in repr(api_summary),
        "authenticated API scopes shift summary to the token owner",
    )

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "shift-summary.sqlite3"
        store1 = SQLitePilotStore(db_path, run_id="shift-a")
        sqlite_assignments = SQLiteOperationalWorkAssignmentRepository(store1)
        sqlite_attachments = SQLiteAttachmentInterpretationReviewRepository(store1)
        sqlite_proposals = SQLiteExtractionProposalRepository(store1)
        sqlite_suppliers = SQLiteSupplierRFQRepository(store1)
        sqlite_approvals = SQLiteQuoteApprovalRepository(store1)
        sqlite_cases = SQLiteQuoteCaseRepository(store1)
        sqlite_proposals.save(
            _proposal(
                proposal_id="proposal-shift-history",
                received_at=NOW,
                required_delivery_date="2026-09-03",
            )
        )
        sqlite_args = _args(
            sqlite_assignments, sqlite_attachments, sqlite_proposals,
            sqlite_suppliers, sqlite_approvals, sqlite_cases,
        )
        sqlite_work_id = "customer_extraction_confirmation:proposal-shift-history"
        sqlite_first = assign_operational_work_to_me(
            work_id=sqlite_work_id, operator_name="SQLite Outgoing", now=NOW, **sqlite_args
        )
        handoff_operational_work(
            work_id=sqlite_work_id,
            operator_name="SQLite Outgoing",
            now=NOW + timedelta(minutes=1),
            **sqlite_args,
        )
        assign_operational_work_to_me(
            work_id=sqlite_work_id,
            operator_name="SQLite Incoming",
            now=NOW + timedelta(minutes=2),
            **sqlite_args,
        )

        store2 = SQLitePilotStore(db_path, run_id="shift-b")
        sqlite_args2 = _args(
            SQLiteOperationalWorkAssignmentRepository(store2),
            SQLiteAttachmentInterpretationReviewRepository(store2),
            SQLiteExtractionProposalRepository(store2),
            SQLiteSupplierRFQRepository(store2),
            SQLiteQuoteApprovalRepository(store2),
            SQLiteQuoteCaseRepository(store2),
        )
        persisted = build_operational_shift_summary(
            operator_name="SQLite Outgoing",
            now=NOW + timedelta(minutes=3),
            **sqlite_args2,
        )
        persisted_item = persisted["recent_handoffs"]["items"][0]
        check(
            persisted["recent_handoffs"]["count"] == 1
            and persisted_item["work_id"] == sqlite_work_id
            and persisted_item["assignment_generation"] == sqlite_first.generation
            and persisted_item["current_disposition"] == "claimed",
            "SQLite append-only assignment history preserves handoff readout across restart",
        )

    return {
        "name": "Operational shift summary and handoff readout",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_shift_summary_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational shift summary regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
