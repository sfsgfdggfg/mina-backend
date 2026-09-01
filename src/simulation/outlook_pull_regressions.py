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


        attachment_capture = {}

        def attachment_factory(*, access_token, mailbox_id):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[_mail("attachment-summary-1")],
                capture=attachment_capture,
            )

        def attachment_processor(**kwargs):
            return {
                "result_type": "inbound_mail_manual_review_required",
                "ingestion_status": "blocked",
                "reason_code": "outlook_attachments_not_supported",
                "inbound_route": "manual_review",
                "attachment_intake_status": "metadata_allowlisted",
                "attachment_intake_reason_code": "attachment_metadata_allowlisted",
                "attachment_count": 2,
                "attachment_total_size_bytes": 8192,
                "attachment_retrieval_status": "verified",
                "attachment_retrieval_reason_code": "attachment_content_verified",
                "attachment_content_download_performed": True,
                "attachment_verified_count": 2,
                "attachment_verification_receipts": [
                    {"sha256_hex": "secret-file-fingerprint"}
                ],
            }

        attachment_summary = pull_controlled_outlook_inbox(
            config=config,
            limit=1,
            shipment_parser=lambda value: value,
            proposal_repository=object(),
            operational_data_sources=object(),
            token_provider=lambda value: SECRET_TOKEN,
            graph_client_factory=attachment_factory,
            inbound_processor=attachment_processor,
        )

        check(
            attachment_summary["manual_review_count"] == 1
            and attachment_summary["results"][0]["attachment_intake_status"]
            == "metadata_allowlisted"
            and attachment_summary["results"][0]["attachment_count"] == 2
            and attachment_summary["results"][0]["attachment_total_size_bytes"] == 8192
            and attachment_summary["results"][0]["attachment_retrieval_status"] == "verified"
            and attachment_summary["results"][0]["attachment_verified_count"] == 2
            and attachment_summary["results"][0]["attachment_content_download_performed"] is True
            and "secret-file-fingerprint" not in repr(attachment_summary),
            "pull safely surfaces retrieval status without file hash",
        )

        extraction_preference = {"new_calls": 0, "old_calls": 0, "interpreter_injected": False}

        class _ExtractionPreferenceClient(_GraphClient):
            def retrieve_and_extract_allowlisted_attachments(self, mail):
                extraction_preference["new_calls"] += 1
                return "new-extraction-boundary"

            def retrieve_allowlisted_attachments(self, mail):
                extraction_preference["old_calls"] += 1
                raise AssertionError("P1-55 fallback must not win when P1-56 is available")

        preference_capture = {}

        def preference_factory(*, access_token, mailbox_id):
            return _ExtractionPreferenceClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[_mail("extraction-preference-1")],
                capture=preference_capture,
            )

        def preference_processor(**kwargs):
            extraction_preference["interpreter_injected"] = callable(
                kwargs.get("attachment_interpreter")
            )
            selected = kwargs["attachment_retriever"](kwargs["mail"])
            return {
                "result_type": "inbound_mail_manual_review_required",
                "ingestion_status": "blocked",
                "reason_code": "outlook_attachment_content_extracted_not_interpreted",
                "inbound_route": "customer",
                "attachment_extraction_status": "extracted",
                "attachment_extraction_reason_code": "attachment_safe_extraction_complete",
                "attachment_extracted_count": 1,
                "attachment_extracted_character_count": 123,
                "attachment_extracted_table_count": 0,
                "selected_boundary": selected,
            }

        preference_result = pull_controlled_outlook_inbox(
            config=config,
            limit=1,
            shipment_parser=lambda value: value,
            proposal_repository=object(),
            operational_data_sources=object(),
            interpret_attachments=True,
            token_provider=lambda value: SECRET_TOKEN,
            graph_client_factory=preference_factory,
            inbound_processor=preference_processor,
        )

        check(
            extraction_preference == {"new_calls": 1, "old_calls": 0, "interpreter_injected": True}
            and preference_result["results"][0]["attachment_extraction_status"] == "extracted"
            and preference_result["results"][0]["attachment_extracted_character_count"] == 123,
            "explicit opt-in prefers P1-56 extraction and injects P1-57 interpretation boundary",
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
            "interpret_attachments": False,
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
            self.interpret_attachments = None

        def pull_outlook(
            self,
            *,
            limit,
            interpret_attachments=False,
        ):
            self.limit = limit
            self.interpret_attachments = interpret_attachments
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
        and fixture.interpret_attachments is False
        and executed["pull_status"]
        == "complete",
        "operator CLI exposes controlled outlook pull",
    )

    parsed_interpret = _build_parser().parse_args(
        ["outlook", "pull", "--limit", "2", "--interpret-attachments"]
    )
    interpret_fixture = _OperatorFixture()
    _execute(interpret_fixture, parsed_interpret)
    check(
        interpret_fixture.limit == 2
        and interpret_fixture.interpret_attachments is True,
        "attachment interpretation requires explicit operator CLI opt-in",
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
        ) as pull_mock:
            endpoint_result = (
                api.pull_outlook_inbound(
                    api.OutlookPullRequest(
                        limit=2
                    )
                )
            )

        check(
            endpoint_result == safe_api_result
            and pull_mock.call_args.kwargs.get("interpret_attachments") is False,
            "API endpoint defaults attachment interpretation off",
        )

        with patch.object(
            api.MicrosoftAuthConfig,
            "from_environment",
            return_value=config,
        ), patch(
            "src.api.pull_controlled_outlook_inbox",
            return_value=safe_api_result,
        ) as opt_in_mock:
            api.pull_outlook_inbound(
                api.OutlookPullRequest(limit=2, interpret_attachments=True)
            )
        check(
            opt_in_mock.call_args.kwargs.get("interpret_attachments") is True,
            "API forwards explicit attachment interpretation opt-in",
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
