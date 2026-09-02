from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.operational_shift_close_attestation import attest_operational_shift_close
from src.core.operational_shift_continuity_ledger import build_operational_shift_continuity_ledger
from src.core.operational_shift_open_acceptance import attest_operational_shift_open_acceptance
from src.core.operational_shift_open_acceptance_receipt import OperationalShiftOpenAcceptanceReceipt
from src.simulation.operational_shift_open_acceptance_regressions import _close_args, _sqlite_args
from src.simulation.operational_work_queue_regressions import NOW


def evaluate_operational_shift_continuity_ledger_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    with TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "continuity.sqlite3"
        store, args = _sqlite_args(db_path, "continuity-a")

        empty = build_operational_shift_continuity_ledger(now=NOW, **args)
        check(
            empty["ledger_status"] == "attention"
            and empty["counts"]["retained_cycle_count"] == 0
            and "no_shift_close_evidence" in empty["audit_attention_codes"],
            "ledger fails safe when no retained shift-close evidence exists",
        )

        before_state = store.latest_event_id()
        close_one = attest_operational_shift_close(
            operator_name="Closing Operator One", now=NOW, **_close_args(args)
        )
        close_duplicate = attest_operational_shift_close(
            operator_name="Closing Operator Two", now=NOW, **_close_args(args)
        )
        duplicate_open = build_operational_shift_continuity_ledger(now=NOW, **args)
        check(
            duplicate_open["counts"]["retained_close_receipt_count"] == 2
            and duplicate_open["counts"]["retained_cycle_count"] == 1
            and duplicate_open["items"][0]["close_attestation_count"] == 2
            and duplicate_open["items"][0]["completion_status"] == "open",
            "same operational state duplicate close attestations collapse into one continuity cycle",
        )

        accepted = attest_operational_shift_open_acceptance(
            operator_name="Incoming Operator", now=NOW + timedelta(seconds=1), **args
        )
        complete = build_operational_shift_continuity_ledger(
            now=NOW + timedelta(seconds=1), **args
        )
        check(
            accepted["source_close_receipt_id"] in {close_one["receipt_id"], close_duplicate["receipt_id"]}
            and complete["ledger_status"] == "clear"
            and complete["items"][0]["completion_status"] == "complete"
            and complete["items"][0]["evidence_freshness"] == "current"
            and complete["items"][0]["acceptance_count"] == 1,
            "accepted duplicate-close cycle is complete and current without exposing operator ownership",
        )

        store.record_event(
            event_type="synthetic_quote_changed",
            entity_type="quote_case",
            entity_id="internal-sensitive-id",
            payload={"subject": "SECRET SUBJECT", "customer_name": "SECRET CUSTOMER"},
        )
        stale_complete = build_operational_shift_continuity_ledger(
            now=NOW + timedelta(seconds=2), **args
        )
        check(
            stale_complete["ledger_status"] == "clear"
            and stale_complete["items"][0]["completion_status"] == "complete"
            and stale_complete["items"][0]["evidence_freshness"] == "stale"
            and stale_complete["counts"]["listed_stale_cycle_count"] == 1,
            "later operational activity stales evidence without turning completed continuity into a gap",
        )

        close_two = attest_operational_shift_close(
            operator_name="Next Closing Operator", now=NOW + timedelta(seconds=3), **_close_args(args)
        )
        second_open = build_operational_shift_continuity_ledger(
            now=NOW + timedelta(seconds=3), **args
        )
        check(
            second_open["counts"]["retained_cycle_count"] == 2
            and second_open["items"][0]["anchor_close_receipt_id"] == close_two["receipt_id"]
            and second_open["items"][0]["completion_status"] == "open"
            and second_open["items"][1]["completion_status"] == "complete"
            and second_open["items"][1]["evidence_freshness"] == "historical",
            "new operational high-water close starts a new cycle while prior completion becomes historical",
        )

        attest_operational_shift_open_acceptance(
            operator_name="Second Incoming Operator", now=NOW + timedelta(seconds=4), **args
        )
        two_complete = build_operational_shift_continuity_ledger(
            now=NOW + timedelta(seconds=4), **args
        )
        check(
            two_complete["ledger_status"] == "clear"
            and two_complete["counts"]["listed_complete_cycle_count"] == 2
            and all(item["completion_status"] == "complete" for item in two_complete["items"]),
            "fresh acceptance completes the newest continuity cycle",
        )

        store.record_event(
            event_type="synthetic_supplier_changed",
            entity_type="supplier_rfq_workflow",
            entity_id="another-internal-id",
            payload={"supplier_name": "SECRET SUPPLIER", "currency": "EUR"},
        )
        gap_close = attest_operational_shift_close(
            operator_name="Gap Closing Operator", now=NOW + timedelta(seconds=5), **_close_args(args)
        )
        store.record_event(
            event_type="synthetic_next_state",
            entity_type="quote_case",
            entity_id="next-internal-id",
            payload={"subject": "MORE SECRET"},
        )
        attest_operational_shift_close(
            operator_name="Later Closing Operator", now=NOW + timedelta(seconds=6), **_close_args(args)
        )
        gap_ledger = build_operational_shift_continuity_ledger(
            now=NOW + timedelta(seconds=6), **args
        )
        gap_rows = [item for item in gap_ledger["items"] if item["anchor_close_receipt_id"] == gap_close["receipt_id"]]
        check(
            len(gap_rows) == 1
            and gap_rows[0]["completion_status"] == "gap"
            and "historical_continuity_gap_present" in gap_ledger["audit_attention_codes"],
            "a superseded close without acceptance is retained as an explicit historical continuity gap",
        )

        latest_close_id = gap_ledger["items"][0]["anchor_close_receipt_id"]
        bad = OperationalShiftOpenAcceptanceReceipt(
            receipt_id="shift-open-" + "a" * 32,
            accepted_by="Corrupt Test Operator",
            accepted_at=NOW - timedelta(seconds=10),
            reconciliation_generated_at=NOW,
            source_close_receipt_id=latest_close_id,
            pending_work_count=0,
            critical_pending_count=0,
            incomplete_handoff_count=0,
            critical_uncovered_count=0,
            acceptance_state_sha256="b" * 64,
        )
        args["acceptance_repository"].save_if_absent(bad)
        integrity = build_operational_shift_continuity_ledger(
            now=NOW + timedelta(seconds=6), **args
        )
        check(
            integrity["counts"]["listed_temporal_integrity_error_count"] >= 1
            and "acceptance_temporal_integrity_error" in integrity["audit_attention_codes"],
            "acceptance predating its close cycle fails safe as temporal evidence-integrity attention",
        )

        rendered = repr(integrity).lower()
        check(
            "attested_by" not in rendered
            and "accepted_by" not in rendered
            and "closing operator" not in rendered
            and "incoming operator" not in rendered
            and "secret subject" not in rendered
            and "secret supplier" not in rendered
            and "internal-sensitive-id" not in rendered
            and "state_event_id" not in rendered
            and "close_state_sha256" not in rendered
            and "acceptance_state_sha256" not in rendered,
            "organization continuity ledger remains privacy-minimal and never returns internal fingerprints or identities",
        )

        before_read_event = store.latest_event_id()
        before_close_count = len(args["receipt_repository"].list_all())
        before_acceptance_count = len(args["acceptance_repository"].list_all())
        second_read = build_operational_shift_continuity_ledger(
            now=NOW + timedelta(seconds=6), **args
        )
        check(
            store.latest_event_id() == before_read_event
            and len(args["receipt_repository"].list_all()) == before_close_count
            and len(args["acceptance_repository"].list_all()) == before_acceptance_count
            and second_read == integrity,
            "continuity ledger is deterministic and mutation-free",
        )

        request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Audit Operator"))
        with (
            patch.object(api, "operational_shift_close_receipt_repository", args["receipt_repository"]),
            patch.object(api, "operational_shift_open_acceptance_repository", args["acceptance_repository"]),
            patch.object(api, "operational_work_assignment_repository", args["assignment_repository"]),
            patch.object(api, "attachment_review_repository", args["attachment_repository"]),
            patch.object(api, "extraction_proposal_repository", args["proposal_repository"]),
            patch.object(api, "supplier_rfq_repository", args["supplier_repository"]),
            patch.object(api, "quote_approval_repository", args["approval_repository"]),
            patch.object(api, "quote_case_repository", args["quote_case_repository"]),
        ):
            api_result = api.get_operational_work_shift_continuity(request)
        check(
            api_result["scope"] == "organization_shift_continuity"
            and "audit operator" not in repr(api_result).lower(),
            "authenticated API exposes organization continuity without leaking requesting operator identity",
        )

    check(
        complete["authority"]["ledger_is_read_only_audit_projection"] is True
        and complete["authority"]["ledger_does_not_open_or_close_shift"] is True
        and complete["authority"]["ledger_does_not_assign_or_transfer_work"] is True
        and complete["authority"]["stale_evidence_is_not_by_itself_a_continuity_gap"] is True,
        "continuity ledger is audit evidence only and never becomes shift or workflow authority",
    )

    return {
        "name": "Operational shift continuity audit ledger",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_shift_continuity_ledger_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational shift continuity ledger regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
