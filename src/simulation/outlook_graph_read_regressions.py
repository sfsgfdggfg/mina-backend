from __future__ import annotations

from typing import Any

from src.integrations.outlook_graph import (
    MAX_PULL_MESSAGES,
    OutlookGraphMessageError,
    OutlookGraphReadClient,
    OutlookGraphReadError,
    normalize_graph_message,
)


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: Any,
    ) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(
        self,
        responses: list[_FakeResponse],
    ) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.trust_env = True

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None,
        timeout: float,
        allow_redirects: bool,
    ) -> _FakeResponse:
        if method != "GET":
            raise AssertionError(
                "Outlook adapter attempted a write request."
            )

        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "params": params,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )

        if not self.responses:
            raise AssertionError(
                "Unexpected network request."
            )

        return self.responses.pop(0)


def _graph_message(
    *,
    message_id: str = "AAMkAbC123",
    content_type: str = "text",
    is_draft: bool = False,
    has_attachments: bool = True,
) -> dict[str, Any]:
    return {
        "id": message_id,
        "subject": "Freight inquiry",
        "body": {
            "contentType": content_type,
            "content": (
                "Please quote Adana to Hamburg."
            ),
        },
        "from": {
            "emailAddress": {
                "address": "OPS@CUSTOMER.EXAMPLE",
                "name": "Customer Operator",
            }
        },
        "toRecipients": [
            {
                "emailAddress": {
                    "address": (
                        "operations@example.invalid"
                    ),
                    "name": "Operations",
                }
            }
        ],
        "receivedDateTime": (
            "2026-08-18T08:30:00+00:00"
        ),
        "hasAttachments": has_attachments,
        "isDraft": is_draft,
    }


def evaluate_outlook_graph_read_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(
        condition: bool,
        label: str,
    ) -> None:
        if condition:
            passes.append(label)
        else:
            failures.append(label)

    fake = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "value": [
                        _graph_message()
                    ]
                },
            )
        ]
    )

    client = OutlookGraphReadClient(
        access_token="regression-secret-token",
        mailbox_id="Operations@Example.Invalid",
        session=fake,
    )

    messages = client.list_inbox_messages(
        limit=1
    )

    request = fake.requests[0]
    mail = messages[0]

    check(
        request["method"] == "GET"
        and request["url"].endswith(
            "/me/mailFolders/inbox/messages"
        )
        and request["allow_redirects"] is False,
        "GET-only Graph request",
    )

    prefer = request["headers"].get(
        "Prefer",
        "",
    )

    check(
        'IdType="ImmutableId"' in prefer
        and (
            'outlook.body-content-type="text"'
            in prefer
        ),
        "immutable IDs and text body requested",
    )

    select_fields = (
        request["params"] or {}
    ).get("$select", "")

    check(
        "hasAttachments" in select_fields
        and "body" in select_fields
        and "receivedDateTime" in select_fields,
        "required Graph fields selected",
    )

    check(
        mail.provider_name == "microsoft_graph"
        and mail.mailbox_id
        == "operations@example.invalid"
        and mail.external_message_id
        == "AAMkAbC123"
        and mail.sender_address
        == "ops@customer.example"
        and mail.body_text
        == "Please quote Adana to Hamburg."
        and mail.has_attachments is True,
        "provider message normalized",
    )

    check(
        mail.message_deduplication_key
        == (
            "microsoft_graph:"
            "operations@example.invalid:"
            "AAMkAbC123"
        ),
        "provider mailbox message deduplication key",
    )

    case_variant = normalize_graph_message(
        _graph_message(
            message_id="aamkabc123"
        ),
        mailbox_id="operations@example.invalid",
    )

    check(
        case_variant.message_deduplication_key
        != mail.message_deduplication_key,
        "Graph message IDs remain case sensitive",
    )

    other_mailbox = normalize_graph_message(
        _graph_message(),
        mailbox_id="other@example.invalid",
    )

    check(
        other_mailbox.message_deduplication_key
        != mail.message_deduplication_key,
        "mailbox identity separates deduplication",
    )

    html_rejected = False
    try:
        normalize_graph_message(
            _graph_message(
                content_type="html"
            ),
            mailbox_id="operations@example.invalid",
        )
    except OutlookGraphMessageError as exc:
        html_rejected = (
            exc.code
            == "graph_non_text_body_rejected"
        )

    check(
        html_rejected,
        "non-text Graph body rejected",
    )

    draft_rejected = False
    try:
        normalize_graph_message(
            _graph_message(
                is_draft=True
            ),
            mailbox_id="operations@example.invalid",
        )
    except OutlookGraphMessageError as exc:
        draft_rejected = (
            exc.code
            == "graph_draft_message_rejected"
        )

    check(
        draft_rejected,
        "draft Graph message rejected",
    )

    hostile_session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "value": [],
                    "@odata.nextLink": (
                        "https://evil.example/"
                        "steal-token"
                    ),
                },
            )
        ]
    )

    hostile_client = OutlookGraphReadClient(
        access_token="do-not-leak",
        mailbox_id="operations@example.invalid",
        session=hostile_session,
    )

    hostile_rejected = False
    try:
        hostile_client.list_inbox_messages(
            limit=2
        )
    except OutlookGraphReadError as exc:
        hostile_rejected = (
            exc.code
            == "graph_next_link_invalid"
        )

    check(
        hostile_rejected,
        "hostile Graph pagination link rejected",
    )

    failure_session = _FakeSession(
        [
            _FakeResponse(
                403,
                {
                    "error": {
                        "message": (
                            "raw provider secret "
                            "must not escape"
                        )
                    }
                },
            )
        ]
    )

    failure_client = OutlookGraphReadClient(
        access_token="private-token",
        mailbox_id="operations@example.invalid",
        session=failure_session,
    )

    safe_failure = False
    try:
        failure_client.list_inbox_messages(
            limit=1
        )
    except OutlookGraphReadError as exc:
        safe_failure = (
            exc.code
            == "microsoft_graph_http_403"
            and "secret" not in str(exc)
            and "private-token" not in str(exc)
        )

    check(
        safe_failure,
        "Graph HTTP failure sanitized",
    )

    redirect_session = _FakeSession(
        [
            _FakeResponse(
                302,
                {},
            )
        ]
    )

    redirect_client = OutlookGraphReadClient(
        access_token="private-token",
        mailbox_id="operations@example.invalid",
        session=redirect_session,
    )

    redirect_rejected = False
    try:
        redirect_client.list_inbox_messages(
            limit=1
        )
    except OutlookGraphReadError as exc:
        redirect_rejected = (
            exc.code
            == "microsoft_graph_redirect_refused"
        )

    check(
        redirect_rejected,
        "Graph redirect refused",
    )

    malformed_session = _FakeSession(
        [
            _FakeResponse(
                200,
                {
                    "unexpected": []
                },
            )
        ]
    )

    malformed_client = OutlookGraphReadClient(
        access_token="private-token",
        mailbox_id="operations@example.invalid",
        session=malformed_session,
    )

    malformed_rejected = False
    try:
        malformed_client.list_inbox_messages(
            limit=1
        )
    except OutlookGraphReadError as exc:
        malformed_rejected = (
            exc.code
            == "microsoft_graph_messages_missing"
        )

    check(
        malformed_rejected,
        "malformed Graph payload rejected",
    )

    bounded = True
    for invalid_limit in (
        0,
        MAX_PULL_MESSAGES + 1,
        True,
    ):
        try:
            client.list_inbox_messages(
                limit=invalid_limit
            )
            bounded = False
        except ValueError:
            pass

    check(
        bounded,
        "Graph pull size bounded",
    )

    check(
        all(
            item["method"] == "GET"
            for item in (
                fake.requests
                + hostile_session.requests
                + failure_session.requests
                + redirect_session.requests
                + malformed_session.requests
            )
        ),
        "regression adapter performed no writes",
    )

    return {
        "name": (
            "Controlled read-only Outlook "
            "Graph ingestion"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main() -> int:
    result = (
        evaluate_outlook_graph_read_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for failure in result["failures"]:
        print(f"FAIL {failure}")

    if result["passed"]:
        print(
            "\nOutlook Graph read-only "
            "regressions: PASS"
        )
        return 0

    print(
        "\nOutlook Graph read-only "
        "regressions: FAIL"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
