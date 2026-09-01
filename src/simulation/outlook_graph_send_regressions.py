from __future__ import annotations

from unittest.mock import patch

from src.core.mail import OutboundMailRequest
from src.integrations.microsoft_auth import MicrosoftAuthConfig
from src.integrations.outlook_graph import OutlookGraphSendClient


class _Response:
    def __init__(self, status_code: int, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self.headers = headers or {}


class _Session:
    def __init__(self, response: _Response):
        self.response = response
        self.requests = []
        self.trust_env = True

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return self.response


def _config() -> MicrosoftAuthConfig:
    return MicrosoftAuthConfig(
        tenant_id="consumers",
        client_id="11111111-1111-1111-1111-111111111111",
        mailbox_id="sender@example.invalid",
        token_cache_path=__import__("pathlib").Path("/tmp/minai-token-cache-test"),
    )


def _request() -> OutboundMailRequest:
    return OutboundMailRequest(
        operation_id="supplier-rfq:test-rfq",
        recipients=["supplier@example.invalid"],
        subject="RFQ",
        body_text="Please quote.",
        purpose="supplier_rfq",
    )


def evaluate_outlook_graph_send_regressions() -> dict:
    failures = []
    success_session = _Session(_Response(202, {"request-id": "graph-request-123"}))
    with patch("src.integrations.outlook_graph.acquire_silent_access_token", return_value="secret-token"):
        result = OutlookGraphSendClient(config=_config(), session=success_session).send(_request())
    method, url, kwargs = success_session.requests[0]
    if not (
        result.status == "sent"
        and result.provider_message_id == "graph-request-123"
        and result.sent_at is not None
        and method == "POST"
        and url.endswith("/me/sendMail")
        and kwargs["allow_redirects"] is False
        and kwargs["json"]["saveToSentItems"] is True
    ):
        failures.append("Graph 202 did not produce controlled sent evidence")

    failure_session = _Session(_Response(403, {"request-id": "denied"}))
    with patch("src.integrations.outlook_graph.acquire_silent_access_token", return_value="secret-token"):
        denied = OutlookGraphSendClient(config=_config(), session=failure_session).send(_request())
    if denied.status != "failed" or denied.provider_message_id is not None or denied.sent_at is not None:
        failures.append("Graph non-202 was incorrectly recorded as sent")

    return {"passed": not failures, "failures": failures}


def main() -> int:
    result = evaluate_outlook_graph_send_regressions()
    for failure in result["failures"]:
        print("FAIL", failure)
    if result["passed"]:
        print("PASS Outlook Graph send")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
