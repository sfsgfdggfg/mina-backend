from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.operational_work_assignment_repository import (
    InMemoryOperationalWorkAssignmentRepository,
)
from src.core.operational_work_assignment_service import (
    MY_WORK_EXPIRING_SOON_SECONDS,
    OperationalWorkAssignmentConflictError,
    OperationalWorkAssignmentTransitionError,
    acknowledge_operational_work,
    assign_operational_work_to_me,
    build_my_operational_work_view,
    handoff_operational_work,
)
from src.core.operational_work_queue import build_operational_work_queue
from src.simulation.operational_work_queue_regressions import NOW, _fixture


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
    return next(
        item["work_id"]
        for item in queue["items"]
        if item["resource_id"] == resource_id
    )


def evaluate_operational_work_my_handoff_regressions():
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
    approval_id = _work_id(queue, "approval-pending")
    follow_id = _work_id(queue, "follow-draft")

    assign_operational_work_to_me(
        work_id=proposal_id,
        operator_name="Shift Operator Alpha",
        now=NOW,
        **args,
    )
    assign_operational_work_to_me(
        work_id=approval_id,
        operator_name="Shift Operator Alpha",
        now=NOW + timedelta(minutes=10),
        **args,
    )
    acknowledge_operational_work(
        work_id=approval_id,
        operator_name="Shift Operator Alpha",
        now=NOW + timedelta(minutes=11),
        **args,
    )
    assign_operational_work_to_me(
        work_id=follow_id,
        operator_name="Shift Operator Beta",
        now=NOW + timedelta(minutes=5),
        **args,
    )

    view_time = NOW + timedelta(minutes=26)
    mine = build_my_operational_work_view(
        operator_name="Shift Operator Alpha",
        now=view_time,
        **args,
    )
    check(
        mine["scope"] == "authenticated_operator"
        and mine["active_count"] == 2
        and mine["acknowledged_count"] == 1
        and mine["expiring_soon_count"] == 1
        and [item["work_id"] for item in mine["items"]] == [proposal_id, approval_id]
        and mine["items"][0]["lease_attention"] == "expiring_soon"
        and mine["items"][0]["lease_seconds_remaining"] <= MY_WORK_EXPIRING_SOON_SECONDS
        and all(item.get("assigned_to") == "Shift Operator Alpha" for item in mine["items"]),
        "my-work view contains only the authenticated operator's active assignments and sorts lease urgency first",
    )
    check(
        follow_id not in {item["work_id"] for item in mine["items"]}
        and "work_state_sha256" not in repr(mine)
        and "subject" not in repr(mine).lower()
        and "currency" not in repr(mine).lower(),
        "my-work view excludes other operators and remains privacy-minimal",
    )

    after_expiry = build_my_operational_work_view(
        operator_name="Shift Operator Alpha",
        now=NOW + timedelta(minutes=31),
        **args,
    )
    check(
        proposal_id not in {item["work_id"] for item in after_expiry["items"]}
        and approval_id in {item["work_id"] for item in after_expiry["items"]},
        "expired assignments are excluded from my-work instead of being treated as active ownership",
    )

    attachments2, proposals2, suppliers2, approvals2, cases2 = _fixture()
    assignments2 = InMemoryOperationalWorkAssignmentRepository()
    args2 = _args(
        assignments2, attachments2, proposals2, suppliers2, approvals2, cases2
    )
    queue2 = build_operational_work_queue(
        attachment_repository=attachments2,
        proposal_repository=proposals2,
        supplier_repository=suppliers2,
        approval_repository=approvals2,
        quote_case_repository=cases2,
        now=NOW,
    )
    handoff_id = _work_id(queue2, "proposal-human")
    before_item = next(item for item in queue2["items"] if item["work_id"] == handoff_id)
    first = assign_operational_work_to_me(
        work_id=handoff_id,
        operator_name="Outgoing Operator",
        now=NOW,
        **args2,
    )

    try:
        handoff_operational_work(
            work_id=handoff_id,
            operator_name="Different Operator",
            now=NOW + timedelta(minutes=1),
            **args2,
        )
    except OperationalWorkAssignmentConflictError:
        foreign_blocked = True
    else:
        foreign_blocked = False

    before_counts = (
        len(proposals2.list_all()),
        len(suppliers2.list_drafts()),
        len(approvals2.list_all()),
        len(cases2.list_all()),
    )
    handed = handoff_operational_work(
        work_id=handoff_id,
        operator_name="Outgoing Operator",
        now=NOW + timedelta(minutes=2),
        **args2,
    )
    after_counts = (
        len(proposals2.list_all()),
        len(suppliers2.list_drafts()),
        len(approvals2.list_all()),
        len(cases2.list_all()),
    )
    successor = assign_operational_work_to_me(
        work_id=handoff_id,
        operator_name="Incoming Operator",
        now=NOW + timedelta(minutes=3),
        **args2,
    )
    queue_after = build_operational_work_queue(
        attachment_repository=attachments2,
        proposal_repository=proposals2,
        supplier_repository=suppliers2,
        approval_repository=approvals2,
        quote_case_repository=cases2,
        now=NOW + timedelta(minutes=3),
    )
    after_item = next(item for item in queue_after["items"] if item["work_id"] == handoff_id)
    check(
        foreign_blocked
        and handed.status == "released"
        and handed.release_reason == "shift_handoff"
        and handed.released_by == "Outgoing Operator"
        and successor.assigned_to == "Incoming Operator"
        and successor.generation == first.generation + 1,
        "shift handoff releases current ownership and requires the next operator to claim a fresh generation",
    )
    check(
        before_counts == after_counts
        and before_item["priority_score"] == after_item["priority_score"]
        and before_item["next_action"] == after_item["next_action"],
        "handoff is coordination-only and does not mutate workflow state, priority or next action",
    )

    attachments3, proposals3, suppliers3, approvals3, cases3 = _fixture()
    assignments3 = InMemoryOperationalWorkAssignmentRepository()
    args3 = _args(
        assignments3, attachments3, proposals3, suppliers3, approvals3, cases3
    )
    queue3 = build_operational_work_queue(
        attachment_repository=attachments3,
        proposal_repository=proposals3,
        supplier_repository=suppliers3,
        approval_repository=approvals3,
        quote_case_repository=cases3,
        now=NOW,
    )
    expired_id = _work_id(queue3, "proposal-human")
    assigned = assign_operational_work_to_me(
        work_id=expired_id,
        operator_name="Expired Operator",
        now=NOW,
        **args3,
    )
    try:
        handoff_operational_work(
            work_id=expired_id,
            operator_name="Expired Operator",
            now=assigned.lease_expires_at + timedelta(seconds=1),
            **args3,
        )
    except OperationalWorkAssignmentTransitionError:
        expired_blocked = True
    else:
        expired_blocked = False
    check(
        expired_blocked,
        "expired ownership cannot be shift-handed-off and must use the existing recovery path",
    )

    request = SimpleNamespace(state=SimpleNamespace(pilot_operator="API Shift Operator"))
    with (
        patch.object(api, "operational_work_assignment_repository", assignments3),
        patch.object(api, "attachment_review_repository", attachments3),
        patch.object(api, "extraction_proposal_repository", proposals3),
        patch.object(api, "supplier_rfq_repository", suppliers3),
        patch.object(api, "quote_approval_repository", approvals3),
        patch.object(api, "quote_case_repository", cases3),
    ):
        # Replace the expired generation with a current API-owned assignment.
        current = assignments3.get(expired_id)
        assignments3.save(current.model_copy(update={"status": "released"}))
        api.assign_operational_work_endpoint(expired_id, request)
        api_mine = api.list_my_operational_work(request)
        api_handoff = api.handoff_operational_work_endpoint(expired_id, request)
    check(
        api_mine["active_count"] == 1
        and api_mine["items"][0]["assigned_to"] == "API Shift Operator"
        and api_handoff["release_reason"] == "shift_handoff"
        and api_handoff["released_by"] == "API Shift Operator"
        and "work_state_sha256" not in repr(api_mine)
        and "work_state_sha256" not in api_handoff,
        "API scopes my-work and handoff identity to the authenticated operator without exposing fingerprints",
    )

    return {
        "name": "Operational work my-work view and shift handoff",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_work_my_handoff_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print(
        "\nOperational work my-work/handoff regressions:",
        "PASS" if result["passed"] else "FAIL",
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
