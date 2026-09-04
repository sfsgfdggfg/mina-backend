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
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    OperationalWorkAssignmentConflictError,
    OperationalWorkAssignmentNotFoundError,
    acknowledge_operational_work,
    assign_operational_work_to_me,
    assignment_public_payload,
    decorate_operational_work_queue,
    release_operational_work,
)
from src.core.operational_work_detail import build_operational_work_item_detail
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


def evaluate_operational_work_assignment_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachments, proposals, suppliers, approvals, cases = _fixture()
    assignments = InMemoryOperationalWorkAssignmentRepository()
    queue_before = build_operational_work_queue(
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
        now=NOW,
    )
    work_id = next(
        item["work_id"]
        for item in queue_before["items"]
        if item["resource_id"] == "proposal-human"
    )
    service_args = _args(assignments, attachments, proposals, suppliers, approvals, cases)

    first = assign_operational_work_to_me(
        work_id=work_id, operator_name="Operator Alpha", now=NOW, **service_args
    )
    repeated = assign_operational_work_to_me(
        work_id=work_id, operator_name="Operator Alpha", now=NOW, **service_args
    )
    check(
        first.status == "assigned"
        and repeated.generation == first.generation
        and proposals.get("proposal-human").extraction_status == "proposed",
        "assignment is durable/idempotent and does not confirm underlying work",
    )

    try:
        assign_operational_work_to_me(
            work_id=work_id, operator_name="Operator Beta", now=NOW, **service_args
        )
    except OperationalWorkAssignmentConflictError:
        second_blocked = True
    else:
        second_blocked = False
    check(second_blocked, "another operator cannot claim the same current work state")

    ack_time = NOW + timedelta(seconds=75)
    try:
        acknowledge_operational_work(
            work_id=work_id, operator_name="Operator Beta", now=ack_time, **service_args
        )
    except OperationalWorkAssignmentConflictError:
        foreign_ack_blocked = True
    else:
        foreign_ack_blocked = False
    ack = acknowledge_operational_work(
        work_id=work_id, operator_name="Operator Alpha", now=ack_time, **service_args
    )
    ack_again = acknowledge_operational_work(
        work_id=work_id, operator_name="Operator Alpha", now=ack_time, **service_args
    )
    ack_payload = assignment_public_payload(ack, now=ack_time)
    check(
        foreign_ack_blocked
        and ack.status == "acknowledged"
        and ack.acknowledged_at is not None
        and ack_again.acknowledged_at == ack.acknowledged_at
        and ack_payload.get("first_look_seconds") == 75,
        "only assignee may acknowledge and acknowledgement durably measures first-look time",
    )

    try:
        release_operational_work(
            work_id=work_id,
            operator_name="Operator Beta",
            assignment_repository=assignments,
            now=ack_time,
        )
    except OperationalWorkAssignmentConflictError:
        foreign_release_blocked = True
    else:
        foreign_release_blocked = False
    released = release_operational_work(
        work_id=work_id,
        operator_name="Operator Alpha",
        assignment_repository=assignments,
        now=ack_time,
    )
    beta = assign_operational_work_to_me(
        work_id=work_id, operator_name="Operator Beta", now=ack_time, **service_args
    )
    check(
        foreign_release_blocked
        and released.status == "released"
        and beta.generation == first.generation + 1,
        "only assignee may release and released work can be reassigned",
    )

    queue_after = decorate_operational_work_queue(
        build_operational_work_queue(
            attachment_repository=attachments,
            proposal_repository=proposals,
            supplier_repository=suppliers,
            approval_repository=approvals,
            quote_case_repository=cases,
            now=NOW,
        ),
        assignments,
    )
    before_item = next(item for item in queue_before["items"] if item["work_id"] == work_id)
    after_item = next(item for item in queue_after["items"] if item["work_id"] == work_id)
    detail = build_operational_work_item_detail(
        work_id=work_id,
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
        assignment_repository=assignments,
        now=NOW,
    )
    check(
        after_item["assigned_to"] == "Operator Beta"
        and after_item["priority_score"] == before_item["priority_score"]
        and after_item["priority_band"] == before_item["priority_band"]
        and detail["assignment"]["assigned_to"] == "Operator Beta"
        and "work_state_sha256" not in repr(queue_after)
        and "work_state_sha256" not in repr(detail),
        "queue/detail expose safe assignment metadata without changing priority or fingerprint privacy",
    )

    follow_work_id = next(
        item["work_id"]
        for item in queue_before["items"]
        if item["resource_id"] == "follow-draft"
    )
    alpha_follow = assign_operational_work_to_me(
        work_id=follow_work_id, operator_name="Operator Alpha", now=NOW, **service_args
    )
    follow = suppliers.get_follow_up_draft("follow-draft")
    suppliers.save_follow_up_drafts([follow.model_copy(update={"status": "approved"})])
    changed_queue = decorate_operational_work_queue(
        build_operational_work_queue(
            attachment_repository=attachments,
            proposal_repository=proposals,
            supplier_repository=suppliers,
            approval_repository=approvals,
            quote_case_repository=cases,
            now=NOW,
        ), assignments,
    )
    changed = next(item for item in changed_queue["items"] if item["work_id"] == follow_work_id)
    beta_follow = assign_operational_work_to_me(
        work_id=follow_work_id, operator_name="Operator Beta", now=NOW, **service_args
    )
    check(
        changed["assignment_status"] == "unassigned"
        and changed.get("stale_assignment_present") is True
        and beta_follow.generation == alpha_follow.generation + 1,
        "work-state changes invalidate old assignment without blocking a fresh claim",
    )

    missing_id = "customer_extraction_confirmation:missing-proposal"
    try:
        assign_operational_work_to_me(
            work_id=missing_id, operator_name="Operator Alpha", now=NOW, **service_args
        )
    except OperationalWorkAssignmentNotFoundError:
        stale_blocked = True
    else:
        stale_blocked = False
    check(stale_blocked, "resolved or stale work IDs cannot be newly assigned")

    request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Operator Gamma"))
    with (
        patch.object(api, "operational_work_assignment_repository", assignments),
        patch.object(api, "attachment_review_repository", attachments),
        patch.object(api, "extraction_proposal_repository", proposals),
        patch.object(api, "supplier_rfq_repository", suppliers),
        patch.object(api, "quote_approval_repository", approvals),
        patch.object(api, "quote_case_repository", cases),
    ):
        release_operational_work(
            work_id=work_id,
            operator_name="Operator Beta",
            assignment_repository=assignments,
            now=NOW,
        )
        api_assignment = api.assign_operational_work_endpoint(work_id, request)
        api_queue = api.list_operational_work_queue()
    check(
        api_assignment["assigned_to"] == "Operator Gamma"
        and "work_state_sha256" not in api_assignment
        and any(
            item.get("assigned_to") == "Operator Gamma"
            for item in api_queue["items"]
            if item["work_id"] == work_id
        ),
        "API derives assignee from authenticated operator and never exposes state fingerprint",
    )

    with TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "assignment.sqlite3")
        sqlite_assignments = SQLiteOperationalWorkAssignmentRepository(store)
        sqlite_attachments = SQLiteAttachmentInterpretationReviewRepository(store)
        sqlite_proposals = SQLiteExtractionProposalRepository(store)
        sqlite_suppliers = SQLiteSupplierRFQRepository(store)
        sqlite_approvals = SQLiteQuoteApprovalRepository(store)
        sqlite_cases = SQLiteQuoteCaseRepository(store)
        sqlite_proposals.save(
            _proposal(
                proposal_id="proposal-race",
                received_at=NOW,
                required_delivery_date="2026-09-03",
            )
        )
        sqlite_args = _args(
            sqlite_assignments,
            sqlite_attachments,
            sqlite_proposals,
            sqlite_suppliers,
            sqlite_approvals,
            sqlite_cases,
        )
        race_work_id = "customer_extraction_confirmation:proposal-race"

        def claim(name: str) -> str:
            try:
                assign_operational_work_to_me(
                    work_id=race_work_id,
                    operator_name=name,
                    now=NOW,
                    **sqlite_args,
                )
            except OperationalWorkAssignmentConflictError:
                return "conflict"
            return "assigned"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(claim, ["Race Operator One", "Race Operator Two"]))
        stored = sqlite_assignments.get(race_work_id)
        check(
            sorted(outcomes) == ["assigned", "conflict"]
            and stored is not None
            and stored.status == "assigned",
            "SQLite BEGIN IMMEDIATE serializes concurrent assignment so exactly one operator wins",
        )

    return {
        "name": "Operational work assignment and acknowledgement",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_work_assignment_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational work assignment regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
