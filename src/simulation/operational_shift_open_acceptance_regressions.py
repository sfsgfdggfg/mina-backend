from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.operational_shift_close_attestation import attest_operational_shift_close
from src.core.operational_shift_close_receipt_repository import InMemoryOperationalShiftCloseReceiptRepository
from src.core.operational_shift_open_acceptance import (
    OperationalShiftOpenAcceptanceBlockedError,
    attest_operational_shift_open_acceptance,
    list_operational_shift_open_acceptances,
)
from src.core.operational_shift_open_acceptance_receipt_repository import (
    InMemoryOperationalShiftOpenAcceptanceReceiptRepository,
)
from src.core.operational_shift_open_reconciliation import build_operational_shift_open_reconciliation
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import (
    SQLiteAttachmentInterpretationReviewRepository,
    SQLiteExtractionProposalRepository,
    SQLiteOperationalShiftCloseReceiptRepository,
    SQLiteOperationalShiftOpenAcceptanceReceiptRepository,
    SQLiteOperationalWorkAssignmentRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.simulation.operational_work_queue_regressions import NOW, _fixture


def _memory_args():
    attachments, proposals, suppliers, approvals, cases = _fixture()
    return {
        "acceptance_repository": InMemoryOperationalShiftOpenAcceptanceReceiptRepository(),
        "receipt_repository": InMemoryOperationalShiftCloseReceiptRepository(),
        "assignment_repository": InMemoryOperationalWorkAssignmentRepository(),
        "attachment_repository": attachments,
        "proposal_repository": proposals,
        "supplier_repository": suppliers,
        "approval_repository": approvals,
        "quote_case_repository": cases,
    }


def _sqlite_args(db_path: Path, run_id: str):
    store = SQLitePilotStore(db_path, run_id=run_id)
    return store, {
        "acceptance_repository": SQLiteOperationalShiftOpenAcceptanceReceiptRepository(store),
        "receipt_repository": SQLiteOperationalShiftCloseReceiptRepository(store),
        "assignment_repository": SQLiteOperationalWorkAssignmentRepository(store),
        "attachment_repository": SQLiteAttachmentInterpretationReviewRepository(store),
        "proposal_repository": SQLiteExtractionProposalRepository(store),
        "supplier_repository": SQLiteSupplierRFQRepository(store),
        "approval_repository": SQLiteQuoteApprovalRepository(store),
        "quote_case_repository": SQLiteQuoteCaseRepository(store),
    }


def _close_args(args):
    return {key: value for key, value in args.items() if key != "acceptance_repository"}


def _workflow_counts(args):
    return (
        len(args["assignment_repository"].list_history()),
        len(args["attachment_repository"].list_all()),
        len(args["proposal_repository"].list_all()),
        len(args["supplier_repository"].list_drafts()),
        len(args["approval_repository"].list_all()),
        len(args["quote_case_repository"].list_all()),
    )


def evaluate_operational_shift_open_acceptance_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    blocked_args = _memory_args()
    blocked = False
    try:
        attest_operational_shift_open_acceptance(
            operator_name="Incoming Operator", now=NOW, **blocked_args
        )
    except OperationalShiftOpenAcceptanceBlockedError:
        blocked = True
    check(
        blocked and blocked_args["acceptance_repository"].list_all() == [],
        "missing or review-required reconciliation fails closed without acceptance evidence",
    )

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "shift-open-acceptance.sqlite3"
        store, args = _sqlite_args(db_path, "accept-a")
        close = attest_operational_shift_close(
            operator_name="Closing Operator", now=NOW, **_close_args(args)
        )
        before = _workflow_counts(args)
        accepted = attest_operational_shift_open_acceptance(
            operator_name="Incoming Operator", now=NOW, **args
        )
        after = _workflow_counts(args)
        check(
            accepted["current_status"] == "current"
            and accepted["current_for_open_state"] is True
            and accepted["source_close_receipt_id"] == close["receipt_id"]
            and accepted["evidence_counts"]["incomplete_handoff_count"] == 0
            and accepted["evidence_counts"]["critical_uncovered_count"] == 0
            and len(args["acceptance_repository"].list_all()) == 1,
            "clear reconciliation produces one durable privacy-safe incoming acceptance receipt",
        )
        check(
            before == after,
            "incoming acceptance writes only evidence and never mutates assignments or workflow repositories",
        )

        reconciliation_after_receipt = build_operational_shift_open_reconciliation(
            operator_name="Incoming Operator", now=NOW, **_close_args(args)
        )
        check(
            reconciliation_after_receipt["reconciliation_status"] == "clear"
            and reconciliation_after_receipt["changes_since_close"]["event_count"] == 0,
            "acceptance evidence event is excluded from post-close operational change tracking",
        )

        repeated = attest_operational_shift_open_acceptance(
            operator_name="Incoming Operator", now=NOW, **args
        )
        check(
            repeated["receipt_id"] == accepted["receipt_id"]
            and len(args["acceptance_repository"].list_all()) == 1,
            "same operator and exact same reconciliation state is idempotent",
        )

        other = attest_operational_shift_open_acceptance(
            operator_name="Second Incoming Operator", now=NOW, **args
        )
        incoming_list = list_operational_shift_open_acceptances(
            operator_name="Incoming Operator", now=NOW, **args
        )
        other_list = list_operational_shift_open_acceptances(
            operator_name="Second Incoming Operator", now=NOW, **args
        )
        check(
            other["receipt_id"] != accepted["receipt_id"]
            and incoming_list["count"] == 1
            and other_list["count"] == 1
            and incoming_list["items"][0]["receipt_id"] == accepted["receipt_id"],
            "acceptance history is authenticated-operator scoped without cross-operator leakage",
        )

        rendered = (repr(accepted) + repr(incoming_list)).lower()
        check(
            "accepted_by" not in rendered
            and "acceptance_state_sha256" not in rendered
            and "closing operator" not in rendered
            and "second incoming operator" not in rendered
            and "customer_name" not in rendered
            and "supplier_name" not in rendered
            and "subject" not in rendered
            and "currency" not in rendered,
            "public acceptance surfaces exclude operator identity, internal fingerprint and sensitive data",
        )

        request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Incoming Operator"))
        with (
            patch.object(api, "operational_shift_open_acceptance_repository", args["acceptance_repository"]),
            patch.object(api, "operational_shift_close_receipt_repository", args["receipt_repository"]),
            patch.object(api, "operational_work_assignment_repository", args["assignment_repository"]),
            patch.object(api, "attachment_review_repository", args["attachment_repository"]),
            patch.object(api, "extraction_proposal_repository", args["proposal_repository"]),
            patch.object(api, "supplier_rfq_repository", args["supplier_repository"]),
            patch.object(api, "quote_approval_repository", args["approval_repository"]),
            patch.object(api, "quote_case_repository", args["quote_case_repository"]),
        ):
            api_accept = api.accept_operational_work_shift_open(request)
            api_list = api.get_operational_work_shift_open_acceptances(request)
        check(
            api_accept["receipt_id"] == accepted["receipt_id"]
            and api_list["scope"] == "authenticated_incoming_operator"
            and api_list["count"] == 1,
            "authenticated API derives incoming acceptance identity from the token owner",
        )

        store.record_event(
            event_type="synthetic_supplier_state_changed",
            entity_type="supplier_rfq_workflow",
            entity_id="sensitive-internal-id",
            payload={"supplier_name": "SECRET SUPPLIER", "currency": "EUR"},
        )
        stale = list_operational_shift_open_acceptances(
            operator_name="Incoming Operator", now=NOW, **args
        )
        changed_reconciliation = build_operational_shift_open_reconciliation(
            operator_name="Incoming Operator", now=NOW, **_close_args(args)
        )
        check(
            stale["current_count"] == 0
            and stale["items"][0]["current_status"] == "stale"
            and changed_reconciliation["review_required"] is True
            and changed_reconciliation["changes_since_close"]["category_counts"] == {"supplier_operations": 1},
            "later operational event stales acceptance while remaining payload-private",
        )
        check(
            "secret supplier" not in repr(stale).lower()
            and "sensitive-internal-id" not in repr(changed_reconciliation).lower(),
            "stale acceptance and reconciliation never expose operational event payload or entity id",
        )

        new_close = attest_operational_shift_close(
            operator_name="Next Closing Operator", now=NOW, **_close_args(args)
        )
        refreshed = build_operational_shift_open_reconciliation(
            operator_name="Incoming Operator", now=NOW, **_close_args(args)
        )
        fresh_acceptance = attest_operational_shift_open_acceptance(
            operator_name="Incoming Operator", now=NOW, **args
        )
        check(
            refreshed["reconciliation_status"] == "clear"
            and fresh_acceptance["receipt_id"] != accepted["receipt_id"]
            and fresh_acceptance["source_close_receipt_id"] == new_close["receipt_id"],
            "fresh global close evidence creates a new acceptance state instead of resurrecting old evidence",
        )

        _, restarted_args = _sqlite_args(db_path, "accept-restart")
        restarted = list_operational_shift_open_acceptances(
            operator_name="Incoming Operator", now=NOW, **restarted_args
        )
        check(
            restarted["count"] == 2
            and restarted["current_count"] == 1
            and restarted["items"][0]["receipt_id"] == fresh_acceptance["receipt_id"],
            "SQLite incoming acceptance evidence survives restart and is revalidated against current reconciliation",
        )

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "shift-open-acceptance-concurrent.sqlite3"
        _, setup_args = _sqlite_args(db_path, "concurrent-setup")
        attest_operational_shift_close(
            operator_name="Concurrent Closing Operator", now=NOW, **_close_args(setup_args)
        )
        _, args_a = _sqlite_args(db_path, "concurrent-a")
        _, args_b = _sqlite_args(db_path, "concurrent-b")

        def worker(worker_args):
            return attest_operational_shift_open_acceptance(
                operator_name="Concurrent Incoming Operator", now=NOW, **worker_args
            )["receipt_id"]

        with ThreadPoolExecutor(max_workers=2) as executor:
            ids = list(executor.map(worker, (args_a, args_b)))
        _, final_args = _sqlite_args(db_path, "concurrent-final")
        final_receipts = [
            item for item in final_args["acceptance_repository"].list_all()
            if item.accepted_by == "Concurrent Incoming Operator"
        ]
        check(
            len(set(ids)) == 1 and len(final_receipts) == 1,
            "concurrent same-state incoming acceptance serializes to exactly one durable receipt",
        )

    check(
        accepted["authority"]["receipt_is_audit_evidence_only"] is True
        and accepted["authority"]["receipt_does_not_open_or_authorize_shift"] is True
        and accepted["authority"]["receipt_does_not_authorize_workflow_actions"] is True,
        "incoming acceptance receipt remains evidence only and never becomes shift or workflow authority",
    )

    return {
        "name": "Operational shift open acceptance evidence",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_shift_open_acceptance_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational shift-open acceptance regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
