from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.operational_shift_close_attestation import (
    OperationalShiftCloseAttestationBlockedError,
    attest_operational_shift_close,
    list_operational_shift_close_receipts,
)
from src.core.operational_shift_close_receipt_repository import (
    InMemoryOperationalShiftCloseReceiptRepository,
)
from src.core.operational_work_assignment import OperationalWorkAssignment
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import assign_operational_work_to_me
from src.core.operational_work_queue import build_operational_work_queue
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import (
    SQLiteAttachmentInterpretationReviewRepository,
    SQLiteExtractionProposalRepository,
    SQLiteOperationalShiftCloseReceiptRepository,
    SQLiteOperationalWorkAssignmentRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.simulation.operational_work_queue_regressions import NOW, _fixture


def _args(receipts, assignments, attachments, proposals, suppliers, approvals, cases):
    return {
        "receipt_repository": receipts,
        "assignment_repository": assignments,
        "attachment_repository": attachments,
        "proposal_repository": proposals,
        "supplier_repository": suppliers,
        "approval_repository": approvals,
        "quote_case_repository": cases,
    }


def _queue(attachments, proposals, suppliers, approvals, cases):
    return build_operational_work_queue(
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
        now=NOW,
    )


def _cover_critical(queue, *, args):
    for item in queue["items"]:
        if item["priority_band"] == "critical":
            assign_operational_work_to_me(
                work_id=item["work_id"],
                operator_name="Coverage Operator",
                now=NOW,
                assignment_repository=args["assignment_repository"],
                attachment_repository=args["attachment_repository"],
                proposal_repository=args["proposal_repository"],
                supplier_repository=args["supplier_repository"],
                approval_repository=args["approval_repository"],
                quote_case_repository=args["quote_case_repository"],
            )


def _sqlite_args(db_path: Path, run_id: str):
    store = SQLitePilotStore(db_path, run_id=run_id)
    return store, {
        "receipt_repository": SQLiteOperationalShiftCloseReceiptRepository(store),
        "assignment_repository": SQLiteOperationalWorkAssignmentRepository(store),
        "attachment_repository": SQLiteAttachmentInterpretationReviewRepository(store),
        "proposal_repository": SQLiteExtractionProposalRepository(store),
        "supplier_repository": SQLiteSupplierRFQRepository(store),
        "approval_repository": SQLiteQuoteApprovalRepository(store),
        "quote_case_repository": SQLiteQuoteCaseRepository(store),
    }


def evaluate_operational_shift_close_attestation_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachments, proposals, suppliers, approvals, cases = _fixture()
    assignments = InMemoryOperationalWorkAssignmentRepository()
    receipts = InMemoryOperationalShiftCloseReceiptRepository()
    args = _args(receipts, assignments, attachments, proposals, suppliers, approvals, cases)
    queue = _queue(attachments, proposals, suppliers, approvals, cases)
    _cover_critical(queue, args=args)

    before_counts = (
        len(assignments.list_history()), len(proposals.list_all()),
        len(suppliers.list_drafts()), len(approvals.list_all()), len(cases.list_all()),
    )
    first = attest_operational_shift_close(operator_name="Closing Operator", now=NOW, **args)
    after_counts = (
        len(assignments.list_history()), len(proposals.list_all()),
        len(suppliers.list_drafts()), len(approvals.list_all()), len(cases.list_all()),
    )
    check(
        first["current_status"] == "current"
        and first["current_for_close_state"] is True
        and first["evidence_counts"]["active_assignment_count"] == 0
        and first["evidence_counts"]["expired_assignment_count"] == 0
        and first["evidence_counts"]["incomplete_handoff_count"] == 0
        and first["evidence_counts"]["critical_uncovered_count"] == 0
        and len(receipts.list_all()) == 1,
        "ready current state produces one durable privacy-safe shift-close receipt",
    )
    check(
        before_counts == after_counts,
        "attestation writes only receipt evidence and never mutates assignments or workflow repositories",
    )

    repeated = attest_operational_shift_close(operator_name="Closing Operator", now=NOW, **args)
    check(
        repeated["receipt_id"] == first["receipt_id"] and len(receipts.list_all()) == 1,
        "repeating attestation for the exact same close state is idempotent",
    )

    noncritical = next(item for item in queue["items"] if item["priority_band"] != "critical")
    assign_operational_work_to_me(
        work_id=noncritical["work_id"],
        operator_name="Other Operator",
        now=NOW,
        assignment_repository=assignments,
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
    )
    stale_list = list_operational_shift_close_receipts(
        operator_name="Closing Operator", now=NOW, **args
    )
    check(
        stale_list["count"] == 1
        and stale_list["current_count"] == 0
        and stale_list["items"][0]["current_status"] == "stale",
        "receipt becomes stale when the current close-state fingerprint changes even if readiness remains clean",
    )
    second = attest_operational_shift_close(operator_name="Closing Operator", now=NOW, **args)
    check(
        second["receipt_id"] != first["receipt_id"]
        and len(receipts.list_all()) == 2,
        "changed but ready close state requires a fresh receipt",
    )

    other_view = list_operational_shift_close_receipts(
        operator_name="Unrelated Operator", now=NOW, **args
    )
    check(
        other_view["count"] == 0,
        "receipt history is authenticated-operator scoped",
    )

    blocked_attachments, blocked_proposals, blocked_suppliers, blocked_approvals, blocked_cases = _fixture()
    blocked_assignments = InMemoryOperationalWorkAssignmentRepository()
    blocked_receipts = InMemoryOperationalShiftCloseReceiptRepository()
    blocked_args = _args(
        blocked_receipts, blocked_assignments, blocked_attachments, blocked_proposals,
        blocked_suppliers, blocked_approvals, blocked_cases,
    )
    blocked = False
    try:
        attest_operational_shift_close(operator_name="Blocked Operator", now=NOW, **blocked_args)
    except OperationalShiftCloseAttestationBlockedError:
        blocked = True
    check(
        blocked and len(blocked_receipts.list_all()) == 0,
        "blocked readiness fails closed and cannot create shift-close evidence",
    )

    rendered = repr(first).lower() + repr(stale_list).lower()
    check(
        "close_state_sha256" not in rendered
        and "state_event_id" not in rendered
        and "attested_by" not in rendered
        and "customer_name" not in rendered
        and "supplier_name" not in rendered
        and "subject" not in rendered
        and "currency" not in rendered,
        "public receipt surfaces exclude internal fingerprint, operator field and sensitive operational data",
    )

    request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Closing Operator"))
    with (
        patch.object(api, "operational_shift_close_receipt_repository", receipts),
        patch.object(api, "operational_work_assignment_repository", assignments),
        patch.object(api, "attachment_review_repository", attachments),
        patch.object(api, "extraction_proposal_repository", proposals),
        patch.object(api, "supplier_rfq_repository", suppliers),
        patch.object(api, "quote_approval_repository", approvals),
        patch.object(api, "quote_case_repository", cases),
    ):
        api_receipts = api.get_operational_work_shift_close_receipts(request)
    check(
        api_receipts["scope"] == "authenticated_operator"
        and api_receipts["count"] == 2
        and "close_state_sha256" not in repr(api_receipts),
        "authenticated API scopes receipt reads to the token owner",
    )

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "shift-close-attestation.sqlite3"
        _, sqlite_args = _sqlite_args(db_path, "attest-a")
        durable = attest_operational_shift_close(
            operator_name="SQLite Operator", now=NOW, **sqlite_args
        )
        _, sqlite_args2 = _sqlite_args(db_path, "attest-b")
        recovered = list_operational_shift_close_receipts(
            operator_name="SQLite Operator", now=NOW, **sqlite_args2
        )
        check(
            recovered["count"] == 1
            and recovered["current_count"] == 1
            and recovered["items"][0]["receipt_id"] == durable["receipt_id"],
            "SQLite shift-close receipt survives restart and is revalidated against current state",
        )
        sqlite_args2["assignment_repository"].save(
            OperationalWorkAssignment(
                work_id="synthetic-nonqueue:state-event",
                assigned_to="Synthetic State Operator",
                work_state_sha256="a" * 64,
            )
        )
        non_resurrecting = list_operational_shift_close_receipts(
            operator_name="SQLite Operator", now=NOW, **sqlite_args2
        )
        check(
            non_resurrecting["current_count"] == 0
            and non_resurrecting["items"][0]["current_status"] == "stale",
            "monotonic non-receipt event watermark prevents historical receipt resurrection",
        )

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "shift-close-concurrent.sqlite3"
        _, concurrent_args_a = _sqlite_args(db_path, "concurrent-a")
        _, concurrent_args_b = _sqlite_args(db_path, "concurrent-b")

        def worker(worker_args):
            return attest_operational_shift_close(
                operator_name="Concurrent Operator", now=NOW, **worker_args
            )["receipt_id"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(worker, (concurrent_args_a, concurrent_args_b)))
        _, final_args = _sqlite_args(db_path, "concurrent-final")
        final_receipts = final_args["receipt_repository"].list_all()
        check(
            len(set(ids)) == 1 and len(final_receipts) == 1,
            "concurrent same-state attestation serializes to exactly one durable receipt",
        )

    return {
        "name": "Operational shift close attestation and evidence receipt",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_shift_close_attestation_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational shift-close attestation regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
