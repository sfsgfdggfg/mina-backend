from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.attachment_interpretation_review_repository import InMemoryAttachmentInterpretationReviewRepository
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.operational_work_assignment import OperationalWorkAssignment
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    DEFAULT_ASSIGNMENT_LEASE_SECONDS,
    OperationalWorkAssignmentConflictError,
    OperationalWorkAssignmentTransitionError,
    acknowledge_operational_work,
    assign_operational_work_to_me,
    assignment_public_payload,
    decorate_operational_work_queue,
    renew_operational_work_assignment,
    takeover_operational_work_assignment,
    work_state_fingerprint,
)
from src.core.operational_work_queue import build_operational_work_queue
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_approval_repository import InMemoryQuoteApprovalRepository
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.sqlite_repositories import (
    SQLiteAttachmentInterpretationReviewRepository,
    SQLiteExtractionProposalRepository,
    SQLiteOperationalWorkAssignmentRepository,
    SQLiteQuoteApprovalRepository,
    SQLiteQuoteCaseRepository,
    SQLiteSupplierRFQRepository,
)
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
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


def evaluate_operational_work_assignment_lease_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachments, proposals, suppliers, approvals, cases = _fixture()
    assignments = InMemoryOperationalWorkAssignmentRepository()
    queue = build_operational_work_queue(
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
        now=NOW,
    )
    work_id = next(item["work_id"] for item in queue["items"] if item["resource_id"] == "proposal-human")
    args = _args(assignments, attachments, proposals, suppliers, approvals, cases)
    before_counts = (
        len(proposals.list_all()), len(suppliers.list_drafts()),
        len(approvals.list_all()), len(cases.list_all()),
    )

    first = assign_operational_work_to_me(work_id=work_id, operator_name="Lease Operator Alpha", now=NOW, **args)
    expected_expiry = NOW + timedelta(seconds=DEFAULT_ASSIGNMENT_LEASE_SECONDS)
    public = assignment_public_payload(first, item=next(i for i in queue["items"] if i["work_id"] == work_id), now=NOW)
    check(
        first.lease_expires_at == expected_expiry
        and first.last_renewed_at == NOW
        and public["lease_status"] == "active"
        and public["lease_seconds_remaining"] == DEFAULT_ASSIGNMENT_LEASE_SECONDS
        and public["takeover_available"] is False
        and "work_state_sha256" not in repr(public),
        "new assignment receives a bounded privacy-safe lease",
    )

    ack_time = NOW + timedelta(minutes=10)
    ack = acknowledge_operational_work(work_id=work_id, operator_name="Lease Operator Alpha", now=ack_time, **args)
    ack_again = acknowledge_operational_work(work_id=work_id, operator_name="Lease Operator Alpha", now=ack_time, **args)
    check(
        ack.status == "acknowledged"
        and ack.lease_expires_at == ack_time + timedelta(seconds=DEFAULT_ASSIGNMENT_LEASE_SECONDS)
        and ack.last_renewed_at == ack_time
        and ack_again.lease_expires_at == ack.lease_expires_at,
        "first acknowledgement refreshes lease while repeated acknowledgement stays idempotent",
    )

    renew_time = NOW + timedelta(minutes=20)
    try:
        renew_operational_work_assignment(work_id=work_id, operator_name="Lease Operator Beta", now=renew_time, **args)
    except OperationalWorkAssignmentConflictError:
        foreign_renew_blocked = True
    else:
        foreign_renew_blocked = False
    renewed = renew_operational_work_assignment(work_id=work_id, operator_name="Lease Operator Alpha", now=renew_time, **args)
    try:
        takeover_operational_work_assignment(work_id=work_id, operator_name="Lease Operator Beta", now=renew_time, **args)
    except OperationalWorkAssignmentConflictError:
        early_takeover_blocked = True
    else:
        early_takeover_blocked = False
    check(
        foreign_renew_blocked and early_takeover_blocked
        and renewed.lease_expires_at == renew_time + timedelta(seconds=DEFAULT_ASSIGNMENT_LEASE_SECONDS),
        "only assignee may renew and active leases cannot be taken over",
    )

    expired_time = renewed.lease_expires_at + timedelta(seconds=1)
    expired_queue = decorate_operational_work_queue(
        build_operational_work_queue(
            attachment_repository=attachments,
            proposal_repository=proposals,
            supplier_repository=suppliers,
            approval_repository=approvals,
            quote_case_repository=cases,
            now=expired_time,
        ), assignments, now=expired_time,
    )
    expired_item = next(item for item in expired_queue["items"] if item["work_id"] == work_id)
    blocked = []
    for action in ("assign", "ack", "renew"):
        try:
            if action == "assign":
                assign_operational_work_to_me(work_id=work_id, operator_name="Lease Operator Beta", now=expired_time, **args)
            elif action == "ack":
                acknowledge_operational_work(work_id=work_id, operator_name="Lease Operator Alpha", now=expired_time, **args)
            else:
                renew_operational_work_assignment(work_id=work_id, operator_name="Lease Operator Alpha", now=expired_time, **args)
        except (OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError):
            blocked.append(action)
    takeover = takeover_operational_work_assignment(work_id=work_id, operator_name="Lease Operator Beta", now=expired_time, **args)
    check(
        expired_item["assignment_status"] == "expired"
        and expired_item["takeover_available"] is True
        and expired_queue["assignment_counts"]["expired"] >= 1
        and blocked == ["assign", "ack", "renew"]
        and takeover.assigned_to == "Lease Operator Beta"
        and takeover.generation == first.generation + 1
        and takeover.status == "assigned",
        "expired lease requires explicit takeover and starts a fresh generation",
    )

    current_item = next(i for i in queue["items"] if i["work_id"] == work_id)
    legacy = OperationalWorkAssignment(
        work_id=work_id,
        assigned_to="Legacy Operator",
        assigned_at=NOW,
        generation=takeover.generation + 1,
        work_state_sha256=work_state_fingerprint(current_item),
    )
    assignments.save(legacy)
    legacy_public = assignment_public_payload(legacy, item=current_item, now=NOW)
    legacy_takeover = takeover_operational_work_assignment(
        work_id=work_id, operator_name="Lease Operator Gamma", now=NOW, **args
    )
    check(
        legacy_public["assignment_status"] == "expired"
        and legacy_public["legacy_lease_missing"] is True
        and legacy_takeover.generation == legacy.generation + 1,
        "legacy active assignment without lease fails safe as expired and takeover-required",
    )

    request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Authenticated Lease Operator"))
    api_time = NOW
    with (
        patch.object(api, "operational_work_assignment_repository", assignments),
        patch.object(api, "attachment_review_repository", attachments),
        patch.object(api, "extraction_proposal_repository", proposals),
        patch.object(api, "supplier_rfq_repository", suppliers),
        patch.object(api, "quote_approval_repository", approvals),
        patch.object(api, "quote_case_repository", cases),
    ):
        current = assignments.get(work_id)
        expired = current.model_copy(update={"lease_expires_at": NOW - timedelta(seconds=1)})
        assignments.save(expired)
        api_takeover = api.takeover_operational_work_endpoint(work_id, request)
    check(
        api_takeover["assigned_to"] == "Authenticated Lease Operator"
        and api_takeover["lease_expires_at"] is not None
        and "work_state_sha256" not in api_takeover,
        "API takeover derives identity from authenticated operator and hides fingerprint",
    )

    after_counts = (
        len(proposals.list_all()), len(suppliers.list_drafts()),
        len(approvals.list_all()), len(cases.list_all()),
    )
    check(before_counts == after_counts, "lease renew/takeover coordination never mutates underlying workflow repositories")

    with TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "lease-race.sqlite3")
        a = SQLiteOperationalWorkAssignmentRepository(store)
        ar = SQLiteAttachmentInterpretationReviewRepository(store)
        p = SQLiteExtractionProposalRepository(store)
        s = SQLiteSupplierRFQRepository(store)
        q = SQLiteQuoteApprovalRepository(store)
        c = SQLiteQuoteCaseRepository(store)
        p.save(_proposal(proposal_id="proposal-lease-race", received_at=NOW, required_delivery_date="2026-09-03"))
        sqlite_args = _args(a, ar, p, s, q, c)
        race_id = "customer_extraction_confirmation:proposal-lease-race"
        assigned = assign_operational_work_to_me(work_id=race_id, operator_name="Original Lease Operator", now=NOW, **sqlite_args)
        race_time = assigned.lease_expires_at + timedelta(seconds=1)

        def takeover_race(name: str) -> str:
            try:
                takeover_operational_work_assignment(work_id=race_id, operator_name=name, now=race_time, **sqlite_args)
            except (OperationalWorkAssignmentConflictError, OperationalWorkAssignmentTransitionError):
                return "conflict"
            return "takeover"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(takeover_race, ["Takeover One", "Takeover Two"]))
        stored = a.get(race_id)
        check(
            sorted(outcomes) == ["conflict", "takeover"]
            and stored is not None and stored.generation == assigned.generation + 1,
            "SQLite serializes expired-lease takeover so exactly one operator wins",
        )

    return {
        "name": "Operational work assignment lease and stale-operator recovery",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_work_assignment_lease_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational work assignment lease regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
