from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException

from src import api
from src.core.mail import (
    InboundMailEnvelope,
)
from src.core.pilot_access import (
    route_allowed,
)
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    MicrosoftAuthenticationError,
)
from src.integrations.outlook_graph import (
    OutlookGraphMessageRejection,
    OutlookGraphReadError,
)
from src.pilot_operator import (
    PilotOperatorClient,
    _build_parser,
    _execute,
)
from src.workflow.mail_ingestion import (
    InboundMailIdempotencyConflictError,
)
from src.workflow.outlook_pull import (
    pull_controlled_outlook_inbox,
)


TENANT = (
    "11111111-1111-1111-1111-111111111111"
)

CLIENT = (
    "22222222-2222-2222-2222-222222222222"
)

MAILBOX = "operations@example.invalid"

SECRET_TOKEN = (
    "outlook-regression-secret-access-token"
)


def _mail(
    message_id: str,
) -> InboundMailEnvelope:
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id=MAILBOX,
        sender_address="ops@pilot.example",
        recipient_addresses=[MAILBOX],
        subject="Freight inquiry",
        body_text=(
            "RAW CUSTOMER BODY MUST NOT "
            "APPEAR IN PULL SUMMARY"
        ),
        received_at=datetime(
            2026,
            8,
            18,
            9,
            0,
            tzinfo=timezone.utc,
        ),
        source="email",
    )


class _GraphClient:
    def __init__(
        self,
        *,
        access_token,
        mailbox_id,
        messages,
        capture,
        rejections=None,
    ):
        capture["token"] = access_token
        capture["mailbox"] = mailbox_id
        self.messages = messages
        self.capture = capture
        self.last_message_rejections = list(
            rejections or []
        )

    def list_inbox_messages(
        self,
        *,
        limit,
    ):
        self.capture["limit"] = limit
        return self.messages[:limit]


class _Response:
    def __init__(
        self,
        payload,
    ):
        self.status_code = 200
        self.payload = payload

    def json(self):
        return self.payload


class _Session:
    def __init__(self):
        self.calls = []
        self.trust_env = True

    def request(
        self,
        method,
        url,
        **kwargs,
    ):
        self.calls.append(
            {
                "method": method,
                "url": url,
                **kwargs,
            }
        )
        return _Response(
            {
                "pull_status": "complete",
            }
        )


def evaluate_outlook_pull_regressions():
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

    with TemporaryDirectory() as temp:
        config = MicrosoftAuthConfig(
            tenant_id=TENANT,
            client_id=CLIENT,
            mailbox_id=MAILBOX,
            token_cache_path=(
                Path(temp)
                / "token-cache.json"
            ),
        )

        capture = {}

        def factory(
            *,
            access_token,
            mailbox_id,
        ):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[
                    _mail("immutable-1"),
                ],
                capture=capture,
            )

        def processor(**kwargs):
            return {
                "result_type": (
                    "extraction_confirmation_required"
                ),
                "ingestion_status": "created",
                "extraction_proposal": {
                    "proposal_id": "proposal-1",
                },
            }

        result = pull_controlled_outlook_inbox(
            config=config,
            limit=5,
            shipment_parser=lambda value: value,
            proposal_repository=object(),
            operational_data_sources=object(),
            token_provider=(
                lambda value: SECRET_TOKEN
            ),
            graph_client_factory=factory,
            inbound_processor=processor,
        )

        check(
            capture == {
                "token": SECRET_TOKEN,
                "mailbox": MAILBOX,
                "limit": 5,
            },
            "server obtains token and passes it only to Graph client",
        )

        serialized = repr(result)

        check(
            SECRET_TOKEN not in serialized
            and (
                "RAW CUSTOMER BODY MUST NOT"
                not in serialized
            )
            and "ops@pilot.example"
            not in serialized,
            "pull summary omits token and raw mail content",
        )

        check(
            result["proposal_count"] == 1
            and result["results"][0][
                "proposal_id"
            ] == "proposal-1"
            and result[
                "mailbox_write_performed"
            ] is False
            and result[
                "automated_send_performed"
            ] is False,
            "pull returns minimal safe proposal summary",
        )

        rejection_capture = {}

        def rejection_factory(
            *,
            access_token,
            mailbox_id,
        ):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[
                    _mail("valid-after-empty"),
                ],
                capture=rejection_capture,
                rejections=[
                    OutlookGraphMessageRejection(
                        external_message_id=(
                            "empty-body-message"
                        ),
                        received_at=(
                            "2026-08-27T06:49:07Z"
                        ),
                        reason_code=(
                            "graph_empty_message_body"
                        ),
                    )
                ],
            )

        resilient = pull_controlled_outlook_inbox(
            config=config,
            limit=2,
            shipment_parser=lambda value: value,
            proposal_repository=object(),
            operational_data_sources=object(),
            token_provider=(
                lambda value: SECRET_TOKEN
            ),
            graph_client_factory=(
                rejection_factory
            ),
            inbound_processor=processor,
        )

        rejection_results = [
            item
            for item in resilient["results"]
            if item.get("reason_code")
            == "graph_empty_message_body"
        ]

        check(
            resilient["fetched_message_count"] == 2
            and resilient["handled_message_count"] == 2
            and resilient["manual_review_count"] == 1
            and resilient["proposal_count"] == 1
            and len(rejection_results) == 1
            and rejection_results[0]["inbound_route"]
            == "manual_review"
            and rejection_results[0]["ingestion_status"]
            == "blocked",
            "blank Graph message is surfaced without blocking pull",
        )

        def conflict_processor(**kwargs):
            raise (
                InboundMailIdempotencyConflictError(
                    "raw conflict secret"
                )
            )

        conflict = pull_controlled_outlook_inbox(
            config=config,
            limit=1,
            shipment_parser=lambda value: value,
            proposal_repository=object(),
            operational_data_sources=object(),
            token_provider=(
                lambda value: SECRET_TOKEN
            ),
            graph_client_factory=factory,
            inbound_processor=(
                conflict_processor
            ),
        )

        check(
            conflict["results"][0][
                "reason_code"
            ]
            == "inbound_message_id_conflict"
            and "secret"
            not in repr(conflict),
            "message-ID conflict is safely summarized",
        )

    check(
        route_allowed(
            "POST",
            "/inbound/outlook/pull",
        ),
        "Outlook pull is explicitly pilot-whitelisted",
    )

    session = _Session()

    client = PilotOperatorClient(
        base_url="http://127.0.0.1:8000",
        token=(
            "operator-regression-token-"
            "12345678901234567890"
        ),
        session=session,
    )

    client.pull_outlook(
        limit=7
    )

    call = session.calls[-1]

    check(
        call["method"] == "POST"
        and call["url"].endswith(
            "/inbound/outlook/pull"
        )
        and call["json"] == {
            "limit": 7,
        },
        "operator client uses authenticated MINAI pull endpoint",
    )

    parsed = _build_parser().parse_args(
        [
            "outlook",
            "pull",
            "--limit",
            "3",
        ]
    )

    class _OperatorFixture:
        def __init__(self):
            self.limit = None

        def pull_outlook(
            self,
            *,
            limit,
        ):
            self.limit = limit
            return {
                "pull_status": "complete"
            }

    fixture = _OperatorFixture()
    executed = _execute(
        fixture,
        parsed,
    )

    check(
        fixture.limit == 3
        and executed["pull_status"]
        == "complete",
        "operator CLI exposes controlled outlook pull",
    )

    with TemporaryDirectory() as temp:
        config = MicrosoftAuthConfig(
            tenant_id=TENANT,
            client_id=CLIENT,
            mailbox_id=MAILBOX,
            token_cache_path=(
                Path(temp)
                / "cache.json"
            ),
        )

        safe_api_result = {
            "provider": "microsoft_graph",
            "pull_status": "complete",
            "results": [],
            "mailbox_write_performed": False,
            "automated_send_performed": False,
        }

        with patch.object(
            api.MicrosoftAuthConfig,
            "from_environment",
            return_value=config,
        ), patch(
            "src.api."
            "pull_controlled_outlook_inbox",
            return_value=safe_api_result,
        ):
            endpoint_result = (
                api.pull_outlook_inbound(
                    api.OutlookPullRequest(
                        limit=2
                    )
                )
            )

        check(
            endpoint_result
            == safe_api_result,
            "API endpoint delegates to server-side pull",
        )

        reauth_status = None

        with patch.object(
            api.MicrosoftAuthConfig,
            "from_environment",
            return_value=config,
        ), patch(
            "src.api."
            "pull_controlled_outlook_inbox",
            side_effect=(
                MicrosoftAuthenticationError(
                    "outlook_reauthentication_required"
                )
            ),
        ):
            try:
                api.pull_outlook_inbound(
                    api.OutlookPullRequest(
                        limit=1
                    )
                )
            except HTTPException as exc:
                reauth_status = (
                    exc.status_code,
                    exc.detail,
                )

        check(
            reauth_status
            == (
                428,
                "outlook_reauthentication_required",
            ),
            "reauthentication requirement is explicit and safe",
        )

        graph_status = None

        with patch.object(
            api.MicrosoftAuthConfig,
            "from_environment",
            return_value=config,
        ), patch(
            "src.api."
            "pull_controlled_outlook_inbox",
            side_effect=OutlookGraphReadError(
                "microsoft_graph_http_503"
            ),
        ):
            try:
                api.pull_outlook_inbound(
                    api.OutlookPullRequest(
                        limit=1
                    )
                )
            except HTTPException as exc:
                graph_status = (
                    exc.status_code,
                    exc.detail,
                )

        check(
            graph_status
            == (
                503,
                "microsoft_graph_http_503",
            ),
            "Graph failure is safely exposed without provider payload",
        )

    return {
        "name": (
            "Controlled Outlook operator pull"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main() -> int:
    result = (
        evaluate_outlook_pull_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for failure in result["failures"]:
        print(f"FAIL {failure}")

    if result["passed"]:
        print(
            "\nOutlook operator pull "
            "regressions: PASS"
        )
        return 0

    print(
        "\nOutlook operator pull "
        "regressions: FAIL"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
