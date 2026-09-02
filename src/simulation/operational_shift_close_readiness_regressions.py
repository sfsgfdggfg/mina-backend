from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from src import api
from src.core.operational_shift_close_readiness import build_operational_shift_close_readiness
from src.core.operational_work_assignment_repository import InMemoryOperationalWorkAssignmentRepository
from src.core.operational_work_assignment_service import (
    acknowledge_operational_work,
    assign_operational_work_to_me,
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


def _queue(attachments, proposals, suppliers, approvals, cases, *, now=NOW):
    return build_operational_work_queue(
        attachment_repository=attachments,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=cases,
        now=now,
    )


def _cover_critical(queue, *, args, now=NOW):
    for item in queue["items"]:
        if item["priority_band"] == "critical":
            assign_operational_work_to_me(
                work_id=item["work_id"], operator_name="Coverage Operator", now=now, **args
            )


def _noncritical_work_id(queue):
    return next(item["work_id"] for item in queue["items"] if item["priority_band"] != "critical")


def evaluate_operational_shift_close_readiness_regressions():
    failures: list[str] = []
    passes: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachments, proposals, suppliers, approvals, cases = _fixture()
    assignments = InMemoryOperationalWorkAssignmentRepository()
    args = _args(assignments, attachments, proposals, suppliers, approvals, cases)
    queue = _queue(attachments, proposals, suppliers, approvals, cases)
    _cover_critical(queue, args=args)

    ready = build_operational_shift_close_readiness(
        operator_name="Closing Operator", now=NOW, **args
    )
    check(
        ready["ready_to_close"] is True
        and ready["readiness"] == "ready"
        and ready["blocker_count"] == 0
        and all(item["passed"] for item in ready["checks"].values()),
        "shift close becomes ready only when current ownership, handoff and critical coverage checks are clear",
    )

    active_id = _noncritical_work_id(queue)
    assign_operational_work_to_me(
        work_id=active_id, operator_name="Closing Operator", now=NOW, **args
    )
    acknowledge_operational_work(
        work_id=active_id, operator_name="Closing Operator", now=NOW + timedelta(minutes=1), **args
    )
    current = assignments.get(active_id)
    assignments.save(current.model_copy(update={"lease_expires_at": NOW + timedelta(minutes=4)}))
    before_history = len(assignments.list_history())
    before_counts = (
        len(proposals.list_all()), len(suppliers.list_drafts()),
        len(approvals.list_all()), len(cases.list_all()),
    )
    active_blocked = build_operational_shift_close_readiness(
        operator_name="Closing Operator", now=NOW + timedelta(minutes=2), **args
    )
    after_counts = (
        len(proposals.list_all()), len(suppliers.list_drafts()),
        len(approvals.list_all()), len(cases.list_all()),
    )
    check(
        active_blocked["ready_to_close"] is False
        and "active_assignments_remaining" in active_blocked["blocker_codes"]
        and "active_assignment_lease_expiring_soon" in active_blocked["warning_codes"]
        and active_blocked["active_work"]["count"] == 1,
        "active work blocks shift close and near-expiry lease attention is surfaced separately",
    )
    check(
        len(assignments.list_history()) == before_history and before_counts == after_counts,
        "shift-close readiness is mutation-free",
    )

    attachments2, proposals2, suppliers2, approvals2, cases2 = _fixture()
    assignments2 = InMemoryOperationalWorkAssignmentRepository()
    args2 = _args(assignments2, attachments2, proposals2, suppliers2, approvals2, cases2)
    queue2 = _queue(attachments2, proposals2, suppliers2, approvals2, cases2)
    _cover_critical(queue2, args=args2, now=NOW - timedelta(minutes=31))
    expired_id = _noncritical_work_id(queue2)
    assign_operational_work_to_me(
        work_id=expired_id,
        operator_name="Closing Operator",
        now=NOW - timedelta(minutes=31),
        **args2,
    )
    expired = build_operational_shift_close_readiness(
        operator_name="Closing Operator", now=NOW, **args2
    )
    check(
        expired["ready_to_close"] is False
        and expired["active_work"]["count"] == 0
        and expired["expired_work"]["count"] == 1
        and "expired_assignments_require_recovery" in expired["blocker_codes"]
        and expired["expired_work"]["items"][0]["takeover_available"] is True,
        "expired current assignment blocks close even though it is absent from My Work",
    )

    attachments3, proposals3, suppliers3, approvals3, cases3 = _fixture()
    assignments3 = InMemoryOperationalWorkAssignmentRepository()
    args3 = _args(assignments3, attachments3, proposals3, suppliers3, approvals3, cases3)
    queue3 = _queue(attachments3, proposals3, suppliers3, approvals3, cases3)
    _cover_critical(queue3, args=args3)
    handoff_id = _noncritical_work_id(queue3)
    assign_operational_work_to_me(
        work_id=handoff_id, operator_name="Closing Operator", now=NOW, **args3
    )
    handoff_operational_work(
        work_id=handoff_id,
        operator_name="Closing Operator",
        now=NOW + timedelta(minutes=1),
        **args3,
    )
    incomplete = build_operational_shift_close_readiness(
        operator_name="Closing Operator", now=NOW + timedelta(minutes=2), **args3
    )
    check(
        incomplete["ready_to_close"] is False
        and incomplete["incomplete_handoffs"]["count"] == 1
        and incomplete["incomplete_handoffs"]["items"][0]["current_disposition"] == "available_unassigned"
        and "recent_handoffs_incomplete" in incomplete["blocker_codes"],
        "handoff remains incomplete until the current work state is covered by a successor",
    )
    assign_operational_work_to_me(
        work_id=handoff_id,
        operator_name="Incoming Operator",
        now=NOW + timedelta(minutes=3),
        **args3,
    )
    completed = build_operational_shift_close_readiness(
        operator_name="Closing Operator", now=NOW + timedelta(minutes=4), **args3
    )
    check(
        completed["ready_to_close"] is True
        and completed["incomplete_handoffs"]["count"] == 0,
        "successor claim completes recent handoff coverage without transferring workflow authority",
    )

    attachments4, proposals4, suppliers4, approvals4, cases4 = _fixture()
    assignments4 = InMemoryOperationalWorkAssignmentRepository()
    args4 = _args(assignments4, attachments4, proposals4, suppliers4, approvals4, cases4)
    critical_blocked = build_operational_shift_close_readiness(
        operator_name="Closing Operator", now=NOW, **args4
    )
    check(
        critical_blocked["ready_to_close"] is False
        and critical_blocked["critical_unassigned"]["count"] > 0
        and "critical_unassigned_work_requires_coverage" in critical_blocked["blocker_codes"],
        "critical unassigned work blocks shift close until coverage exists",
    )

    attachments5, proposals5, suppliers5, approvals5, cases5 = _fixture()
    assignments5 = InMemoryOperationalWorkAssignmentRepository()
    args5 = _args(assignments5, attachments5, proposals5, suppliers5, approvals5, cases5)
    queue5 = _queue(attachments5, proposals5, suppliers5, approvals5, cases5)
    critical_items = [item for item in queue5["items"] if item["priority_band"] == "critical"]
    for index, item in enumerate(critical_items):
        assign_operational_work_to_me(
            work_id=item["work_id"],
            operator_name="Coverage Operator",
            now=(NOW - timedelta(minutes=31) if index == 0 else NOW),
            **args5,
        )
    expired_critical = build_operational_shift_close_readiness(
        operator_name="Closing Operator", now=NOW, **args5
    )
    check(
        expired_critical["ready_to_close"] is False
        and expired_critical["critical_unassigned"]["count"] >= 1
        and any(
            item.get("assignment_status") == "expired"
            for item in expired_critical["critical_unassigned"]["items"]
        ),
        "critical work with expired other-operator lease is uncovered and blocks close readiness",
    )

    rendered = repr(active_blocked).lower() + repr(expired).lower() + repr(incomplete).lower()
    check(
        "work_state_sha256" not in rendered
        and "subject" not in rendered
        and "currency" not in rendered
        and "customer_name" not in rendered
        and "supplier_name" not in rendered
        and "assigned_to" not in rendered,
        "shift-close readiness remains privacy-minimal and exposes no internal fingerprint or party data",
    )

    request = SimpleNamespace(state=SimpleNamespace(pilot_operator="Closing Operator"))
    with (
        patch.object(api, "operational_work_assignment_repository", assignments4),
        patch.object(api, "attachment_review_repository", attachments4),
        patch.object(api, "extraction_proposal_repository", proposals4),
        patch.object(api, "supplier_rfq_repository", suppliers4),
        patch.object(api, "quote_approval_repository", approvals4),
        patch.object(api, "quote_case_repository", cases4),
    ):
        api_readiness = api.get_operational_work_shift_close_readiness(request)
    check(
        api_readiness["scope"] == "authenticated_operator"
        and api_readiness["ready_to_close"] is False
        and "work_state_sha256" not in repr(api_readiness),
        "authenticated API scopes shift-close readiness to the token owner",
    )

    check(
        ready["authority"]["readiness_does_not_close_shift"] is True
        and ready["authority"]["existing_workflow_guards_remain_authoritative"] is True
        and set(ready["remediation"]) == {
            "active_assignments_remaining",
            "expired_assignments_require_recovery",
            "recent_handoffs_incomplete",
            "critical_unassigned_work_requires_coverage",
        },
        "readiness exposes only descriptive recovery routing and never becomes close or workflow authority",
    )

    return {
        "name": "Operational shift close readiness and handoff completeness",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_shift_close_readiness_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational shift-close readiness regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
