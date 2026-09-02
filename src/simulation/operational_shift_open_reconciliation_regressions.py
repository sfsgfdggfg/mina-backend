from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.operational_shift_close_attestation import attest_operational_shift_close
from src.core.operational_shift_close_receipt_repository import InMemoryOperationalShiftCloseReceiptRepository
from src.core.operational_shift_open_reconciliation import build_operational_shift_open_reconciliation
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    assign_operational_work_to_me,
    handoff_operational_work,
)
from src.core.operational_work_queue import build_operational_work_queue
from src.simulation.operational_shift_close_attestation_regressions import _sqlite_args
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


def _cover_critical(queue, *, args, operator="Coverage Operator"):
    for item in queue["items"]:
        if item["priority_band"] == "critical":
            assign_operational_work_to_me(
                work_id=item["work_id"],
                operator_name=operator,
                now=NOW,
                assignment_repository=args["assignment_repository"],
                attachment_repository=args["attachment_repository"],
                proposal_repository=args["proposal_repository"],
                supplier_repository=args["supplier_repository"],
                approval_repository=args["approval_repository"],
                quote_case_repository=args["quote_case_repository"],
            )


def evaluate_operational_shift_open_reconciliation_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachments, proposals, suppliers, approvals, cases = _fixture()
    assignments = InMemoryOperationalWorkAssignmentRepository()
    receipts = InMemoryOperationalShiftCloseReceiptRepository()
    args = _args(receipts, assignments, attachments, proposals, suppliers, approvals, cases)
    missing = build_operational_shift_open_reconciliation(
        operator_name="Incoming Operator", now=NOW, **args
    )
    check(
        missing["review_required"] is True
        and missing["prior_shift_close"]["status"] == "missing"
        and "no_prior_shift_close_receipt" in missing["attention_codes"]
        and "change_tracking_unavailable" in missing["attention_codes"],
        "missing prior close receipt fails safe into incoming-shift review",
    )

    queue = _queue(attachments, proposals, suppliers, approvals, cases)
    _cover_critical(queue, args=args)
    handoff_id = next(item["work_id"] for item in queue["items"] if item["priority_band"] != "critical")
    assign_operational_work_to_me(
        work_id=handoff_id,
        operator_name="Outgoing Operator",
        now=NOW,
        assignment_repository=assignments,
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
    )
    handoff_operational_work(
        work_id=handoff_id,
        operator_name="Outgoing Operator",
        now=NOW,
        assignment_repository=assignments,
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
    )
    incoming = build_operational_shift_open_reconciliation(
        operator_name="Incoming Operator", now=NOW, **args
    )
    check(
        incoming["incomplete_handoffs"]["count"] == 1
        and incoming["incomplete_handoffs"]["items"][0]["work_id"] == handoff_id
        and incoming["incomplete_handoffs"]["items"][0]["current_disposition"] == "available_unassigned"
        and "incomplete_handoffs_require_reconciliation" in incoming["attention_codes"],
        "incoming reconciliation sees incomplete handoff across operators without transfer",
    )

    rendered_handoff = repr(incoming).lower()
    check(
        "outgoing operator" not in rendered_handoff
        and "released_by" not in rendered_handoff
        and "assigned_to" not in rendered_handoff,
        "cross-operator reconciliation never exposes operator ownership identity",
    )

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "shift-open.sqlite3"
        store, sqlite_args = _sqlite_args(db_path, "shift-open-a")
        receipt = attest_operational_shift_close(
            operator_name="Closing Operator", now=NOW, **sqlite_args
        )
        immediate = build_operational_shift_open_reconciliation(
            operator_name="Incoming Operator", now=NOW, **sqlite_args
        )
        check(
            immediate["reconciliation_status"] == "clear"
            and immediate["review_required"] is False
            and immediate["prior_shift_close"]["status"] == "available"
            and immediate["prior_shift_close"]["receipt_id"] == receipt["receipt_id"]
            and immediate["prior_shift_close"]["current_status"] == "current"
            and immediate["changes_since_close"]["tracking_status"] == "available"
            and immediate["changes_since_close"]["event_count"] == 0,
            "latest cross-operator close receipt reconciles cleanly and ignores its own receipt event",
        )
        check(
            "attested_by" not in repr(immediate).lower(),
            "incoming operator can use latest global receipt without seeing closing operator identity",
        )

        before_state = len(store.list_all(namespace="operational_shift_close_receipts"))
        before_events = store.latest_event_id()
        second_read = build_operational_shift_open_reconciliation(
            operator_name="Incoming Operator", now=NOW, **sqlite_args
        )
        check(
            len(store.list_all(namespace="operational_shift_close_receipts")) == before_state
            and store.latest_event_id() == before_events
            and second_read == immediate,
            "shift-open reconciliation is deterministic and mutation-free",
        )

        store.record_event(
            event_type="synthetic_quote_case_changed",
            entity_type="quote_case",
            entity_id="sensitive-internal-id",
            payload={"subject": "SECRET SUBJECT", "currency": "EUR", "customer_name": "SECRET CUSTOMER"},
        )
        changed = build_operational_shift_open_reconciliation(
            operator_name="Incoming Operator", now=NOW, **sqlite_args
        )
        check(
            changed["review_required"] is True
            and changed["prior_shift_close"]["current_status"] == "stale"
            and changed["changes_since_close"]["event_count"] == 1
            and changed["changes_since_close"]["category_counts"] == {"customer_quote": 1}
            and "operational_changes_since_close" in changed["attention_codes"],
            "post-close operational event stales receipt and is summarized by safe category",
        )
        rendered_changed = repr(changed).lower()
        check(
            "secret subject" not in rendered_changed
            and "secret customer" not in rendered_changed
            and "sensitive-internal-id" not in rendered_changed
            and "quote_case" not in rendered_changed
            and "state_event_id" not in rendered_changed
            and "close_state_sha256" not in rendered_changed,
            "event reconciliation never reconstructs payload, entity IDs, raw entity types or fingerprints",
        )

        second_receipt = attest_operational_shift_close(
            operator_name="Another Closing Operator", now=NOW, **sqlite_args
        )
        latest = build_operational_shift_open_reconciliation(
            operator_name="Incoming Operator", now=NOW, **sqlite_args
        )
        check(
            latest["prior_shift_close"]["receipt_id"] == second_receipt["receipt_id"]
            and latest["changes_since_close"]["event_count"] == 0,
            "incoming reconciliation always anchors to the latest organization-wide close receipt",
        )

        request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Incoming Operator"))
        with (
            patch.object(api, "operational_shift_close_receipt_repository", sqlite_args["receipt_repository"]),
            patch.object(api, "operational_work_assignment_repository", sqlite_args["assignment_repository"]),
            patch.object(api, "attachment_review_repository", sqlite_args["attachment_repository"]),
            patch.object(api, "extraction_proposal_repository", sqlite_args["proposal_repository"]),
            patch.object(api, "supplier_rfq_repository", sqlite_args["supplier_repository"]),
            patch.object(api, "quote_approval_repository", sqlite_args["approval_repository"]),
            patch.object(api, "quote_case_repository", sqlite_args["quote_case_repository"]),
        ):
            api_result = api.get_operational_work_shift_open_reconciliation(request)
        check(
            api_result["scope"] == "authenticated_incoming_operator"
            and "attested_by" not in repr(api_result).lower(),
            "authenticated API scopes shift-open reconciliation without identity selector",
        )

    check(
        incoming["authority"]["reconciliation_is_read_only"] is True
        and incoming["authority"]["reconciliation_does_not_open_shift"] is True
        and incoming["authority"]["existing_workflow_guards_remain_authoritative"] is True,
        "shift-open reconciliation is descriptive coordination only and never opening authority",
    )

    rendered = repr(missing).lower() + repr(incoming).lower()
    check(
        "customer_name" not in rendered
        and "supplier_name" not in rendered
        and "subject" not in rendered
        and "currency" not in rendered
        and "work_state_sha256" not in rendered,
        "shift-open reconciliation remains privacy-minimal across missing and handoff states",
    )

    return {
        "name": "Operational shift open and incoming reconciliation",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_shift_open_reconciliation_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational shift-open reconciliation regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
