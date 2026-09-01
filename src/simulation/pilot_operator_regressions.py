from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.pilot_operator import (
    DEFAULT_TIMEOUT_SECONDS,
    OperatorAPIError,
    OperatorConfigurationError,
    PilotOperatorClient,
    main,
    validate_base_url,
)


class _Response:
    def __init__(self, status_code: int = 200, payload=None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {"status": "ok"}

    def json(self):
        return self._payload


class _Session:
    def __init__(self, responses=None) -> None:
        self.responses = list(responses or [_Response()])
        self.calls: list[dict] = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if len(self.responses) == 1:
            return self.responses[0]
        return self.responses.pop(0)


def _client(session: _Session) -> PilotOperatorClient:
    return PilotOperatorClient(
        base_url="http://127.0.0.1:8000",
        token="regression-secret-token-value",
        session=session,
    )


def _last_contract(session: _Session) -> tuple[str, str, object]:
    call = session.calls[-1]
    return (
        call["method"],
        call["url"].removeprefix("http://127.0.0.1:8000"),
        call["json"],
    )


def evaluate_pilot_operator_regressions() -> dict:
    failures: list[str] = []

    try:
        PilotOperatorClient(base_url="http://127.0.0.1:8000", token="")
    except OperatorConfigurationError:
        pass
    else:
        failures.append("operator client accepted a missing token")

    for public_url in (
        "https://8.8.8.8:8000",
        "https://example.com",
        "ftp://127.0.0.1",
        "http://10.42.1.9:8000",
        "http://[fd00::10]:8000",
    ):
        try:
            validate_base_url(public_url)
        except OperatorConfigurationError:
            pass
        else:
            failures.append(f"unsafe base URL was accepted: {public_url}")
    for safe_url in (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://10.42.1.9:8443",
        "http://[::1]:8000",
        "https://[fd00::10]:8443",
    ):
        try:
            validate_base_url(safe_url)
        except OperatorConfigurationError as exc:
            failures.append(f"safe base URL was rejected: {safe_url}: {exc}")

    session = _Session()
    client = _client(session)
    status = client.status()
    status_call = session.calls[0]
    if status != {
        "health": {"status": "ok"},
        "authentication": "ok",
    }:
        failures.append("status did not verify health and authentication")
    if [call["url"] for call in session.calls[:2]] != [
        "http://127.0.0.1:8000/health",
        "http://127.0.0.1:8000/supplier-rfqs",
    ]:
        failures.append("status did not use an authenticated read check")
    if status_call["headers"] != {
        "Authorization": "Bearer regression-secret-token-value"
    }:
        failures.append("bearer Authorization header was not sent")
    if status_call["timeout"] != DEFAULT_TIMEOUT_SECONDS:
        failures.append("safe request timeout was not configured")
    if status_call["allow_redirects"] is not False:
        failures.append("HTTP redirects were not disabled")
    if session.trust_env is not False:
        failures.append("environment proxy inheritance was not disabled")

    contracts = []
    client.process_email(
        email_text="Operational email body",
        sender_address="customer@example.test",
        sender_name="Customer Operator",
        subject="Freight request",
        external_message_id="external-1",
    )
    contracts.append(
        (
            _last_contract(session),
            (
                "POST",
                "/process-email",
                {
                    "email_text": "Operational email body",
                    "sender_address": "customer@example.test",
                    "sender_name": "Customer Operator",
                    "subject": "Freight request",
                    "external_message_id": "external-1",
                },
            ),
        )
    )
    client.list_attachment_review_queue()
    contracts.append((_last_contract(session), ("GET", "/attachment-review-queue", None)))
    client.get_operational_work_queue()
    contracts.append((_last_contract(session), ("GET", "/operational-work-queue", None)))
    client.get_operational_shift_summary()
    contracts.append((_last_contract(session), ("GET", "/operational-work-shift-summary", None)))
    client.get_my_operational_work()
    contracts.append((_last_contract(session), ("GET", "/operational-work-my", None)))
    client.get_operational_work_item("customer_extraction_confirmation:proposal-1")
    contracts.append((
        _last_contract(session),
        ("GET", "/operational-work-items/customer_extraction_confirmation%3Aproposal-1", None),
    ))
    client.assign_operational_work_to_me("customer_extraction_confirmation:proposal-1")
    contracts.append((
        _last_contract(session),
        ("POST", "/operational-work-items/customer_extraction_confirmation%3Aproposal-1/assign-to-me", {}),
    ))
    client.acknowledge_operational_work("customer_extraction_confirmation:proposal-1")
    contracts.append((
        _last_contract(session),
        ("POST", "/operational-work-items/customer_extraction_confirmation%3Aproposal-1/acknowledge", {}),
    ))
    client.renew_operational_work_assignment("customer_extraction_confirmation:proposal-1")
    contracts.append((
        _last_contract(session),
        ("POST", "/operational-work-items/customer_extraction_confirmation%3Aproposal-1/renew", {}),
    ))
    client.takeover_operational_work_assignment("customer_extraction_confirmation:proposal-1")
    contracts.append((
        _last_contract(session),
        ("POST", "/operational-work-items/customer_extraction_confirmation%3Aproposal-1/takeover", {}),
    ))
    client.handoff_operational_work("customer_extraction_confirmation:proposal-1")
    contracts.append((
        _last_contract(session),
        ("POST", "/operational-work-items/customer_extraction_confirmation%3Aproposal-1/handoff", {}),
    ))
    client.release_operational_work("customer_extraction_confirmation:proposal-1")
    contracts.append((
        _last_contract(session),
        ("POST", "/operational-work-items/customer_extraction_confirmation%3Aproposal-1/release", {}),
    ))
    client.list_attachment_reviews()
    contracts.append((_last_contract(session), ("GET", "/attachment-reviews", None)))
    client.get_attachment_review("review-1")
    contracts.append(
        (_last_contract(session), ("GET", "/attachment-reviews/review-1", None))
    )
    client.preview_attachment_review("review-1", {"is_high_value": False})
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/attachment-reviews/review-1/preview", {"corrections": {"is_high_value": False}}),
        )
    )
    client.apply_attachment_review(
        "review-1", preview_token="a" * 64, corrections={"is_high_value": False}
    )
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/attachment-reviews/review-1/apply", {
                "corrections": {"is_high_value": False}, "preview_token": "a" * 64
            }),
        )
    )
    client.reject_attachment_review("review-2", "Needs manual verification")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/attachment-reviews/review-2/reject", {"rejection_reason": "Needs manual verification"}),
        )
    )
    client.get_proposal("proposal-1")
    contracts.append(
        (_last_contract(session), ("GET", "/extraction-proposals/proposal-1", None))
    )
    corrections = {
        "transport_mode": "road",
        "is_adr": False,
        "is_temperature_controlled": False,
        "is_high_value": False,
    }
    client.confirm_proposal("proposal-1", corrections)
    contracts.append(
        (
            _last_contract(session),
            (
                "POST",
                "/extraction-proposals/proposal-1/confirm",
                {"corrections": corrections},
            ),
        )
    )
    client.resume_proposal("proposal-1")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/extraction-proposals/proposal-1/resume", None),
        )
    )
    client.list_rfqs()
    contracts.append((_last_contract(session), ("GET", "/supplier-rfqs", None)))
    client.get_rfq("rfq-1")
    contracts.append((_last_contract(session), ("GET", "/supplier-rfqs/rfq-1", None)))
    client.approve_rfq("rfq-1")
    contracts.append(
        (_last_contract(session), ("POST", "/supplier-rfqs/rfq-1/approve", {}))
    )
    client.send_rfq("rfq-1")
    contracts.append(
        (_last_contract(session), ("POST", "/supplier-rfqs/rfq-1/send", {}))
    )
    client.record_rfq_manually_sent("rfq-1")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/supplier-rfqs/rfq-1/record-manually-sent", {}),
        )
    )
    client.list_rfq_follow_ups("rfq-1")
    contracts.append(
        (_last_contract(session), ("GET", "/supplier-rfqs/rfq-1/follow-ups", None))
    )
    client.get_rfq_follow_up("follow-up-1")
    contracts.append(
        (
            _last_contract(session),
            ("GET", "/supplier-rfq-follow-ups/follow-up-1", None),
        )
    )
    client.approve_rfq_follow_up("follow-up-1")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/supplier-rfq-follow-ups/follow-up-1/approve", {}),
        )
    )
    client.send_rfq_follow_up("follow-up-1")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/supplier-rfq-follow-ups/follow-up-1/send", {}),
        )
    )
    client.record_rfq_follow_up_manually_sent("follow-up-1")
    contracts.append(
        (
            _last_contract(session),
            (
                "POST",
                "/supplier-rfq-follow-ups/follow-up-1/record-manually-sent",
                {},
            ),
        )
    )
    response = {
        "supplier_name": "Supplier One",
        "rfq_priority": 1,
        "status": "quoted",
        "cost": 1500,
        "currency": "EUR",
        "source": "manual",
    }
    client.record_rfq_response("rfq-1", **response)
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/supplier-rfqs/rfq-1/responses", response),
        )
    )
    client.resume_quote_workflow("workflow-1")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/supplier-rfq-workflows/workflow-1/resume-quote", None),
        )
    )
    pricing_override = {
        "method": "fixed_profit",
        "value": 300,
    }
    client.resume_quote_workflow(
        "workflow-2", quote_pricing_override=pricing_override
    )
    contracts.append(
        (
            _last_contract(session),
            (
                "POST",
                "/supplier-rfq-workflows/workflow-2/resume-quote",
                {"quote_pricing_override": pricing_override},
            ),
        )
    )
    client.list_approvals()
    contracts.append((_last_contract(session), ("GET", "/quote-approvals", None)))
    client.get_approval("approval-1")
    contracts.append(
        (_last_contract(session), ("GET", "/quote-approvals/approval-1", None))
    )
    client.approve_quote("approval-1")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/quote-approvals/approval-1/approve", {}),
        )
    )
    client.reject_quote("approval-2", "Commercial terms rejected")
    contracts.append(
        (
            _last_contract(session),
            (
                "POST",
                "/quote-approvals/approval-2/reject",
                {"rejection_reason": "Commercial terms rejected"},
            ),
        )
    )
    client.invalidate_quote("approval-3")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/quote-approvals/approval-3/invalidate", None),
        )
    )
    client.list_cases()
    contracts.append((_last_contract(session), ("GET", "/quote-cases", None)))
    client.get_case("case-1")
    contracts.append((_last_contract(session), ("GET", "/quote-cases/case-1", None)))
    client.get_case_final_output("case-1")
    contracts.append(
        (
            _last_contract(session),
            ("GET", "/quote-cases/case-1/final-output", None),
        )
    )
    client.record_case_manually_sent(
        "case-1",
        expected_approval_id="approval-4",
        recipient_email="customer@example.test",
    )
    contracts.append(
        (
            _last_contract(session),
            (
                "POST",
                "/quote-cases/case-1/record-manually-sent",
                {
                    "expected_approval_id": "approval-4",
                    "recipient_email": "customer@example.test",
                },
            ),
        )
    )
    client.revise_case(
        "case-1",
        expected_approval_id="approval-4",
        subject="Ahmet selam",
        body="Guncellenmis musteri teklif maili.",
        final_price=2250,
        operator_note="Customer relationship tone adjusted.",
    )
    contracts.append(
        (
            _last_contract(session),
            (
                "POST",
                "/quote-cases/case-1/revise",
                {
                    "expected_approval_id": "approval-4",
                    "subject": "Ahmet selam",
                    "body": "Guncellenmis musteri teklif maili.",
                    "final_price": 2250,
                    "operator_note": "Customer relationship tone adjusted.",
                },
            ),
        )
    )
    for actual, expected in contracts:
        if actual != expected:
            failures.append(f"operator request contract mismatch: {actual}")

    requested_paths = [
        call["url"].removeprefix("http://127.0.0.1:8000")
        for call in session.calls
    ]
    forbidden_paths = {
        "/quotes/prepare-send",
        "/supplier-responses/ingest",
    }
    if forbidden_paths.intersection(requested_paths):
        failures.append("operator client exposed an automated outbound path")
    public_methods = {
        name
        for name in dir(PilotOperatorClient)
        if not name.startswith("_")
    }
    if "send_rfq" not in public_methods:
        failures.append("operator client does not expose controlled supplier RFQ send")
    if "send_rfq_follow_up" not in public_methods:
        failures.append("operator client does not expose controlled supplier follow-up send")
    if {"send_quote", "prepare_quote_send"}.intersection(public_methods):
        failures.append("operator client exposes a legacy automated send method")

    blocked_session = _Session([_Response(status_code=409, payload={"detail": "already sent"})])
    blocked_client = _client(blocked_session)
    try:
        blocked_client.send_rfq("rfq-blocked")
    except OperatorAPIError:
        pass
    else:
        failures.append("operator supplier send treated HTTP 409 as success")

    blocked_stderr = io.StringIO()
    with patch.object(
        PilotOperatorClient,
        "from_environment",
        return_value=blocked_client,
    ), contextlib.redirect_stderr(blocked_stderr):
        blocked_exit = main(["rfq", "send", "rfq-blocked"])
    if blocked_exit != 2:
        failures.append("blocked supplier send CLI did not exit nonzero")

    expected_error_text = {
        401: "Authentication failed",
        403: "Access denied",
        404: "not found",
        409: "Lifecycle conflict",
        426: "HTTPS",
        422: "Input or correction",
        503: "safety block",
    }
    for status, expected_text in expected_error_text.items():
        error_client = _client(_Session([_Response(status, {"secret": "raw"})]))
        try:
            error_client.status()
        except OperatorAPIError as exc:
            message = str(exc)
            if expected_text not in message or "raw" in message:
                failures.append(f"unsafe {status} error mapping: {message}")
        else:
            failures.append(f"HTTP {status} was not mapped to a safe error")

    redirect_client = _client(_Session([_Response(302)]))
    try:
        redirect_client.status()
    except OperatorAPIError:
        pass
    else:
        failures.append("redirect response was accepted")

    recovery_paths = {
        "/operational-work-queue",
        "/operational-work-my",
        "/operational-work-items/customer_extraction_confirmation%3Aproposal-1",
        "/attachment-review-queue",
        "/attachment-reviews",
        "/attachment-reviews/review-1",
        "/attachment-reviews/review-1/preview",
        "/extraction-proposals/proposal-1",
        "/supplier-rfqs",
        "/supplier-rfqs/rfq-1",
        "/supplier-rfqs/rfq-1/follow-ups",
        "/supplier-rfq-follow-ups/follow-up-1",
        "/quote-approvals",
        "/quote-approvals/approval-1",
        "/quote-cases",
        "/quote-cases/case-1",
        "/quote-cases/case-1/final-output",
    }
    if not recovery_paths.issubset(requested_paths):
        failures.append("interrupted workflow lacks read/list recovery calls")

    cli_session = _Session(
        [
            _Response(
                200,
                {
                    "case_id": "case-cli",
                    "delivery_mode": "manual_external_operation",
                    "automated_send_performed": False,
                },
            )
        ]
    )
    cli_client = _client(cli_session)
    cli_stdout = io.StringIO()
    cli_stderr = io.StringIO()

    with patch.object(
        PilotOperatorClient,
        "from_environment",
        return_value=cli_client,
    ):
        with contextlib.redirect_stdout(cli_stdout), contextlib.redirect_stderr(
            cli_stderr
        ):
            cli_exit = main(["case", "final", "case-cli"])

    if cli_exit != 0:
        failures.append("case final CLI command failed")

    if not cli_session.calls:
        failures.append("case final CLI made no API request")
    else:
        cli_method, cli_path, cli_payload = _last_contract(cli_session)
        if (
            cli_method,
            cli_path,
            cli_payload,
        ) != (
            "GET",
            "/quote-cases/case-cli/final-output",
            None,
        ):
            failures.append(
                "case final CLI mapped to the wrong API contract"
            )

    if "manual_external_operation" not in cli_stdout.getvalue():
        failures.append(
            "case final CLI did not print final handoff result"
        )

    sent_cli_session = _Session([_Response(200, {"source": "customer_quote_manual_sent_service"})])
    sent_cli_client = _client(sent_cli_session)
    sent_cli_stdout = io.StringIO()
    sent_cli_stderr = io.StringIO()
    with patch.object(
        PilotOperatorClient,
        "from_environment",
        return_value=sent_cli_client,
    ):
        with contextlib.redirect_stdout(sent_cli_stdout), contextlib.redirect_stderr(
            sent_cli_stderr
        ):
            sent_cli_exit = main([
                "case",
                "manual-sent",
                "case-cli",
                "--approval-id",
                "approval-cli",
                "--recipient-email",
                "customer@example.test",
            ])
    if sent_cli_exit != 0:
        failures.append("case manual-sent CLI command failed")
    elif _last_contract(sent_cli_session) != (
        "POST",
        "/quote-cases/case-cli/record-manually-sent",
        {
            "expected_approval_id": "approval-cli",
            "recipient_email": "customer@example.test",
        },
    ):
        failures.append("case manual-sent CLI mapped to the wrong API contract")


    work_queue_cli_session = _Session([_Response(200, {"pending_count": 0, "items": []})])
    work_queue_cli_client = _client(work_queue_cli_session)
    with patch.object(PilotOperatorClient, "from_environment", return_value=work_queue_cli_client):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            work_queue_cli_exit = main(["work", "queue"])
    if work_queue_cli_exit != 0:
        failures.append("operational work queue CLI command failed")
    elif _last_contract(work_queue_cli_session) != (
        "GET", "/operational-work-queue", None,
    ):
        failures.append("operational work queue CLI mapped to the wrong API contract")

    shift_summary_cli_session = _Session([_Response(200, {"overview": {"pending_count": 0}})])
    shift_summary_cli_client = _client(shift_summary_cli_session)
    with patch.object(PilotOperatorClient, "from_environment", return_value=shift_summary_cli_client):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            shift_summary_cli_exit = main(["work", "shift-summary"])
    if shift_summary_cli_exit != 0:
        failures.append("operational shift summary CLI command failed")
    elif _last_contract(shift_summary_cli_session) != (
        "GET", "/operational-work-shift-summary", None,
    ):
        failures.append("operational shift summary CLI mapped to the wrong API contract")

    work_mine_cli_session = _Session([_Response(200, {"active_count": 0, "items": []})])
    work_mine_cli_client = _client(work_mine_cli_session)
    with patch.object(PilotOperatorClient, "from_environment", return_value=work_mine_cli_client):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            work_mine_cli_exit = main(["work", "mine"])
    if work_mine_cli_exit != 0:
        failures.append("operational my-work CLI command failed")
    elif _last_contract(work_mine_cli_session) != (
        "GET", "/operational-work-my", None,
    ):
        failures.append("operational my-work CLI mapped to the wrong API contract")

    work_get_cli_session = _Session([_Response(200, {"work_item": {"work_id": "quote_approval:approval-1"}})])
    work_get_cli_client = _client(work_get_cli_session)
    with patch.object(PilotOperatorClient, "from_environment", return_value=work_get_cli_client):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            work_get_cli_exit = main(["work", "get", "quote_approval:approval-1"])
    if work_get_cli_exit != 0:
        failures.append("operational work detail CLI command failed")
    elif _last_contract(work_get_cli_session) != (
        "GET", "/operational-work-items/quote_approval%3Aapproval-1", None,
    ):
        failures.append("operational work detail CLI mapped to the wrong API contract")

    for action, suffix in (("assign", "assign-to-me"), ("ack", "acknowledge"), ("renew", "renew"), ("takeover", "takeover"), ("handoff", "handoff"), ("release", "release")):
        work_mutation_session = _Session([_Response(200, {"status": "assigned"})])
        work_mutation_client = _client(work_mutation_session)
        with patch.object(PilotOperatorClient, "from_environment", return_value=work_mutation_client):
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                work_mutation_exit = main(["work", action, "quote_approval:approval-1"])
        if work_mutation_exit != 0:
            failures.append(f"operational work {action} CLI command failed")
        elif _last_contract(work_mutation_session) != (
            "POST", f"/operational-work-items/quote_approval%3Aapproval-1/{suffix}", {},
        ):
            failures.append(f"operational work {action} CLI mapped to the wrong API contract")

    queue_cli_session = _Session([_Response(200, {"pending_count": 0, "items": []})])
    queue_cli_client = _client(queue_cli_session)
    with patch.object(PilotOperatorClient, "from_environment", return_value=queue_cli_client):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            queue_cli_exit = main(["attachment-review", "queue"])
    if queue_cli_exit != 0:
        failures.append("attachment review queue CLI command failed")
    elif _last_contract(queue_cli_session) != (
        "GET", "/attachment-review-queue", None,
    ):
        failures.append("attachment review queue CLI mapped to the wrong API contract")

    review_preview_cli_session = _Session([_Response(200, {"apply_ready": True, "preview_token": "b" * 64})])
    review_preview_cli_client = _client(review_preview_cli_session)
    with patch.object(PilotOperatorClient, "from_environment", return_value=review_preview_cli_client):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            review_preview_cli_exit = main([
                "attachment-review", "preview", "review-cli",
                "--corrections", '{"is_high_value": false}',
            ])
    if review_preview_cli_exit != 0:
        failures.append("attachment review preview CLI command failed")
    elif _last_contract(review_preview_cli_session) != (
        "POST", "/attachment-reviews/review-cli/preview",
        {"corrections": {"is_high_value": False}},
    ):
        failures.append("attachment review preview CLI mapped to the wrong API contract")

    review_cli_session = _Session([_Response(200, {"status": "applied"})])
    review_cli_client = _client(review_cli_session)
    with patch.object(PilotOperatorClient, "from_environment", return_value=review_cli_client):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            review_cli_exit = main([
                "attachment-review", "apply", "review-cli",
                "--corrections", '{"is_high_value": false}',
                "--preview-token", "b" * 64,
            ])
    if review_cli_exit != 0:
        failures.append("attachment review apply CLI command failed")
    elif _last_contract(review_cli_session) != (
        "POST", "/attachment-reviews/review-cli/apply",
        {"corrections": {"is_high_value": False}, "preview_token": "b" * 64},
    ):
        failures.append("attachment review apply CLI mapped to the wrong API contract")

    follow_up_cli_session = _Session([_Response(200, {"status": "approved"})])
    follow_up_cli_client = _client(follow_up_cli_session)
    with patch.object(
        PilotOperatorClient,
        "from_environment",
        return_value=follow_up_cli_client,
    ):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(
            io.StringIO()
        ):
            follow_up_cli_exit = main([
                "rfq",
                "follow-up-approve",
                "follow-up-cli",
            ])
    if follow_up_cli_exit != 0:
        failures.append("RFQ follow-up approve CLI command failed")
    elif _last_contract(follow_up_cli_session) != (
        "POST",
        "/supplier-rfq-follow-ups/follow-up-cli/approve",
        {},
    ):
        failures.append("RFQ follow-up approve CLI mapped to the wrong API contract")

    follow_up_send_cli_session = _Session([_Response(200, {"delivery": {"status": "sent"}})])
    follow_up_send_cli_client = _client(follow_up_send_cli_session)
    with patch.object(
        PilotOperatorClient,
        "from_environment",
        return_value=follow_up_send_cli_client,
    ):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            follow_up_send_cli_exit = main([
                "rfq", "follow-up-send", "follow-up-cli"
            ])
    if follow_up_send_cli_exit != 0:
        failures.append("RFQ follow-up send CLI command failed")
    elif _last_contract(follow_up_send_cli_session) != (
        "POST", "/supplier-rfq-follow-ups/follow-up-cli/send", {}
    ):
        failures.append("RFQ follow-up send CLI mapped to the wrong API contract")

    blocked_follow_up_send_session = _Session([_Response(409, {"detail": "stale"})])
    blocked_follow_up_send_client = _client(blocked_follow_up_send_session)
    with patch.object(
        PilotOperatorClient,
        "from_environment",
        return_value=blocked_follow_up_send_client,
    ):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            blocked_follow_up_send_exit = main([
                "rfq", "follow-up-send", "follow-up-cli"
            ])
    if blocked_follow_up_send_exit != 2:
        failures.append("blocked RFQ follow-up send CLI did not exit nonzero")

    secret = "never-print-this-bearer-token"
    stdout = io.StringIO()
    stderr = io.StringIO()
    with patch.dict(
        "os.environ",
        {
            "MINAI_PILOT_BASE_URL": "http://127.0.0.1:8000",
            "MINAI_PILOT_TOKEN": secret,
        },
        clear=True,
    ):
        with patch.object(
            PilotOperatorClient,
            "status",
            side_effect=OperatorAPIError("Authentication failed."),
        ):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main(["status"])
    if secret in stdout.getvalue() or secret in stderr.getvalue():
        failures.append("bearer token was printed")

    with TemporaryDirectory() as temp_dir:
        before = set(Path(temp_dir).iterdir())
        with patch("pathlib.Path.cwd", return_value=Path(temp_dir)):
            _client(_Session()).status()
        after = set(Path(temp_dir).iterdir())
        if after != before:
            failures.append("operator client persisted a secret or local state")

    return {
        "name": "Minimal authenticated pilot operator client",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = evaluate_pilot_operator_regressions()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
