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
    client.record_rfq_manually_sent("rfq-1")
    contracts.append(
        (
            _last_contract(session),
            ("POST", "/supplier-rfqs/rfq-1/record-manually-sent", {}),
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
    for actual, expected in contracts:
        if actual != expected:
            failures.append(f"operator request contract mismatch: {actual}")

    requested_paths = [
        call["url"].removeprefix("http://127.0.0.1:8000")
        for call in session.calls
    ]
    forbidden_paths = {
        "/supplier-rfqs/rfq-1/send",
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
    if {"send_rfq", "send_quote", "prepare_quote_send"}.intersection(public_methods):
        failures.append("operator client exposes an automated send method")

    expected_error_text = {
        401: "Authentication failed",
        403: "Access denied",
        404: "not found",
        409: "Lifecycle conflict",
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
        "/extraction-proposals/proposal-1",
        "/supplier-rfqs",
        "/supplier-rfqs/rfq-1",
        "/quote-approvals",
        "/quote-approvals/approval-1",
        "/quote-cases",
        "/quote-cases/case-1",
    }
    if not recovery_paths.issubset(requested_paths):
        failures.append("interrupted workflow lacks read/list recovery calls")

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
