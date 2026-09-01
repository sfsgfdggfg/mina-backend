from __future__ import annotations

from unittest.mock import patch

from fastapi import HTTPException

from src import api
from src.core.operational_work_detail import (
    OperationalWorkItemNotFoundError,
    build_operational_work_item_detail,
)
from src.core.operational_work_queue import build_operational_work_queue
from src.simulation.operational_work_queue_regressions import (
    NOW,
    _fixture,
    _state_snapshot,
)


def evaluate_operational_work_detail_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    attachment_reviews, proposals, suppliers, approvals, quote_cases = _fixture()
    before = _state_snapshot(attachment_reviews, proposals, suppliers, approvals, quote_cases)
    queue = build_operational_work_queue(
        attachment_repository=attachment_reviews,
        proposal_repository=proposals,
        supplier_repository=suppliers,
        approval_repository=approvals,
        quote_case_repository=quote_cases,
        now=NOW,
    )

    details = {}
    for item in queue["items"]:
        details[item["resource_id"]] = build_operational_work_item_detail(
            work_id=item["work_id"],
            attachment_repository=attachment_reviews,
            proposal_repository=proposals,
            supplier_repository=suppliers,
            approval_repository=approvals,
            quote_case_repository=quote_cases,
            now=NOW,
        )

    proposal = details["proposal-human"]
    check(
        proposal["diagnostics"]["recovery_mode"] == "human_confirmation_required"
        and proposal["diagnostics"]["state_checks"]["unknown_safety_field_count"] == 3
        and set(proposal["diagnostics"]["state_checks"]["unknown_safety_fields"])
        == {"is_adr", "is_temperature_controlled", "is_high_value"}
        and proposal["operator_commands"][0]["argv"][:2] == ["proposal", "get"]
        and proposal["operator_commands"][1]["requires"] == ["corrections_json_if_needed"],
        "customer work detail explains safety gaps and controlled confirmation recovery",
    )

    draft = details["follow-draft"]
    approved = details["follow-approved"]
    check(
        draft["diagnostics"]["recovery_mode"] == "controlled_follow_up_action"
        and draft["operator_commands"][-1]["argv"][:2] == ["rfq", "follow-up-approve"]
        and approved["operator_commands"][-1]["argv"][:2] == ["rfq", "follow-up-send"],
        "supplier follow-up detail maps current state to existing guarded commands",
    )

    gap = details["rfq-gap"]
    check(
        gap["diagnostics"]["state_checks"]["active_follow_up_count"] == 0
        and gap["diagnostics"]["recovery_mode"] == "controlled_workflow_resume"
        and gap["operator_commands"][-1]["argv"][:2] == ["workflow", "resume-quote"]
        and "clarification_required_without_active_follow_up" in gap["blocking_reasons"],
        "clarification gap detail uses real workflow resume recovery without auto-repair",
    )

    orphan = details["approval-orphan"]
    pending = details["approval-pending"]
    check(
        orphan["diagnostics"]["recovery_mode"] == "inspect_state"
        and orphan["diagnostics"]["state_checks"]["linked_case_count"] == 0
        and len(orphan["operator_commands"]) == 1
        and "quote_approval_case_missing" in orphan["blocking_reasons"]
        and pending["diagnostics"]["recovery_mode"] == "human_decision_required"
        and {command["argv"][1] for command in pending["operator_commands"][1:]}
        == {"approve", "reject"},
        "quote approval detail blocks inconsistent state and guides valid decisions",
    )

    attachment_resource_id = next(
        item["resource_id"] for item in queue["items"]
        if item["work_type"] == "attachment_review"
    )
    attachment = details[attachment_resource_id]
    check(
        attachment["diagnostics"]["recovery_mode"] == "inspect_then_preview"
        and all(command["argv"][0] == "attachment-review" for command in attachment["operator_commands"])
        and attachment["authority"]["detail_is_read_only"] is True,
        "attachment detail preserves get-preview authority chain",
    )

    representation = repr(details)
    check(
        "PRIVATE CUSTOMER NAME" not in representation
        and "PRIVATE CUSTOMER SUBJECT" not in representation
        and "private-customer@example.invalid" not in representation
        and "PRIVATE SUPPLIER NAME" not in representation
        and "PRIVATE FOLLOW UP BODY" not in representation
        and "private-detail-that-must-not-leak" not in representation
        and "PRIVATE QUOTE SUBJECT" not in representation
        and "999999" not in representation
        and "sha256" not in representation
        and "preview_token" not in representation,
        "work detail remains privacy-minimal while exposing recovery metadata",
    )

    after = _state_snapshot(attachment_reviews, proposals, suppliers, approvals, quote_cases)
    check(before == after, "building work detail is mutation-free")

    stale_error = False
    try:
        build_operational_work_item_detail(
            work_id="quote_approval:does-not-exist",
            attachment_repository=attachment_reviews,
            proposal_repository=proposals,
            supplier_repository=suppliers,
            approval_repository=approvals,
            quote_case_repository=quote_cases,
            now=NOW,
        )
    except OperationalWorkItemNotFoundError:
        stale_error = True
    check(stale_error, "inactive or stale work IDs fail closed as not found")

    with (
        patch.object(api, "attachment_review_repository", attachment_reviews),
        patch.object(api, "extraction_proposal_repository", proposals),
        patch.object(api, "supplier_rfq_repository", suppliers),
        patch.object(api, "quote_approval_repository", approvals),
        patch.object(api, "quote_case_repository", quote_cases),
    ):
        api_detail = api.get_operational_work_item("customer_extraction_confirmation:proposal-human")
        api_404 = False
        try:
            api.get_operational_work_item("quote_approval:missing")
        except HTTPException as exc:
            api_404 = exc.status_code == 404
    check(
        api_detail["work_item"]["resource_id"] == "proposal-human" and api_404,
        "authenticated API exposes current work detail and rejects stale IDs",
    )

    return {
        "name": "Operational work item detail and recovery",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_operational_work_detail_regressions()
    for item in result["passed_checks"]:
        print("PASS", item)
    for item in result["failures"]:
        print("FAIL", item)
    print("\nOperational work detail regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
