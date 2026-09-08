from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from src.core.counterparty_discovery import discover_historical_counterparties
from src.core.master_data import MasterContact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master, create_supplier_master
from src.core.relationship_history import HistoricalMailMessage
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
    MicrosoftAuthConfigurationError,
)
from src.integrations.outlook_graph import OutlookGraphReadClient
from src.outlook_counterparty_discovery import (
    OutlookDiscoveryProfileError,
    _resolve_external_profile,
    build_readonly_auth_config,
)
from src.simulation.physical_temp import physical_temporary_directory
from src.workflow.counterparty_discovery import (
    CounterpartyDiscoveryAuthorizationError,
    run_outlook_counterparty_discovery,
)


NOW = datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc)


def _message(
    reference: str,
    *,
    sender: str,
    recipients: list[str],
    subject: str,
    body: str,
    minute: int,
) -> HistoricalMailMessage:
    return HistoricalMailMessage(
        source_reference=reference,
        sent_at=NOW.replace(minute=minute),
        sender_address=sender,
        recipient_addresses=recipients,
        subject=subject,
        body_text=body,
        source="synthetic",
    )


def _build_master_repository() -> InMemoryMasterDataRepository:
    repository = InMemoryMasterDataRepository()
    create_customer_master(
        repository=repository,
        entry_id="known-customer",
        customer_name="Known Customer",
        trusted_sender_addresses=["known@customer.example"],
        trusted_sender_domains=["customer.example"],
        contacts=[
            MasterContact(
                contact_name="Known Contact",
                email="known@customer.example",
                roles=["pricing"],
                is_primary=True,
            )
        ],
        updated_by="Synthetic Ops",
        created_at=NOW,
    )
    create_supplier_master(
        repository=repository,
        entry_id="known-supplier",
        supplier_name="Known Carrier",
        contacts=[
            MasterContact(
                contact_name="Carrier Pricing",
                email="rates@carrier.example",
                roles=["pricing"],
                is_primary=True,
            )
        ],
        service_types=["FTL"],
        equipment_types=["Tenteli / Curtainsider"],
        updated_by="Synthetic Ops",
        created_at=NOW,
    )
    return repository


def _history_messages() -> list[HistoricalMailMessage]:
    agency = "ops@agency.example"
    secret = "RAW BODY MUST NOT SURVIVE"
    items = [
        _message(
            "m1", sender="known@customer.example", recipients=[agency],
            subject="Quote Istanbul Berlin", body=secret, minute=1,
        ),
        _message(
            "m2", sender=agency, recipients=["known@customer.example"],
            subject="Re: Quote Istanbul Berlin", body="Agency reply", minute=2,
        ),
        _message(
            "m3", sender="rates@carrier.example", recipients=[agency],
            subject="RFQ Germany", body="Carrier quote", minute=3,
        ),
        _message(
            "m4", sender=agency,
            recipients=["new@newco.example", "sales@newco.example"],
            subject="New request", body="Agency outbound", minute=4,
        ),
        _message(
            "m5", sender="new@newco.example", recipients=[agency],
            subject="Re: New request", body="New company reply", minute=5,
        ),
        _message(
            "m6", sender=agency, recipients=["other@customer.example"],
            subject="Known domain", body="Agency outbound", minute=6,
        ),
    ]
    items.append(items[0].model_copy())
    return items


class _FakeHistoryClient:
    def __init__(self, *, messages: list[HistoricalMailMessage]):
        self.messages = messages
        self.last_message_rejections = []
        self.last_counterparty_discovery_scan = {
            "examined_message_count": len(messages),
            "accepted_message_count": len(messages),
            "truncated": False,
        }

    def list_counterparty_discovery_history(self, *, start_at, end_at, max_messages):
        return self.messages



class _GraphResponse:
    def __init__(self, payload):
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _GraphSession:
    def __init__(self, payloads):
        self.payloads = list(payloads) if isinstance(payloads, list) else [payloads]
        self.requests = []
        self.trust_env = True

    def request(
        self, method, url, *, headers, params, timeout, allow_redirects,
    ):
        if method != "GET":
            raise AssertionError("counterparty discovery attempted a write request")
        self.requests.append({
            "method": method, "url": url, "headers": headers,
            "params": params, "timeout": timeout,
            "allow_redirects": allow_redirects,
        })
        payload = self.payloads.pop(0) if self.payloads else {"value": []}
        return _GraphResponse(payload)

def evaluate_counterparty_discovery_regressions() -> dict[str, object]:
    failures: list[str] = []
    repository = _build_master_repository()
    messages = _history_messages()
    result = discover_historical_counterparties(
        messages=messages,
        agency_addresses=["ops@agency.example"],
        master_repository=repository,
    )
    if (
        result.input_message_count != 7
        or result.unique_message_count != 6
        or result.duplicate_message_count != 1
        or result.candidate_count != 5
        or result.unmatched_candidate_count != 2
        or result.known_candidate_count != 3
        or result.ambiguous_candidate_count != 0
        or result.domain_count != 3
    ):
        failures.append("discovery summary counts are incorrect")

    by_email = {item.email_address: item for item in result.candidates}
    expected_status = {
        "known@customer.example": "known_customer",
        "rates@carrier.example": "known_supplier",
        "other@customer.example": "known_customer_domain",
        "new@newco.example": "unmatched",
        "sales@newco.example": "unmatched",
    }
    for address, status in expected_status.items():
        item = by_email.get(address)
        if item is None or item.master_match_status != status:
            failures.append(f"discovery master-match status incorrect for {address}")

    new_candidate = by_email.get("new@newco.example")
    if (
        new_candidate is None
        or new_candidate.message_count != 2
        or new_candidate.inbound_count != 1
        or new_candidate.outbound_count != 1
        or new_candidate.thread_count != 1
    ):
        failures.append("unmatched candidate traffic evidence is incorrect")

    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    if (
        "RAW BODY MUST NOT SURVIVE" in serialized
        or "Quote Istanbul Berlin" in serialized
        or result.raw_body_persisted is not False
    ):
        failures.append("discovery output leaked raw subject/body content")

    domain = next(
        (item for item in result.domains if item.domain == "newco.example"),
        None,
    )
    if (
        domain is None
        or domain.candidate_address_count != 2
        or domain.contact_event_count != 3
        or domain.inbound_count != 1
        or domain.outbound_count != 2
    ):
        failures.append("domain-level discovery summary is incorrect")

    conflicting = _history_messages()[:-1]
    conflicting.append(
        conflicting[0].model_copy(update={"subject": "Conflicting reuse"})
    )
    try:
        discover_historical_counterparties(
            messages=conflicting,
            agency_addresses=["ops@agency.example"],
            master_repository=repository,
        )
    except ValueError:
        pass
    else:
        failures.append("conflicting historical source reference was not rejected")

    graph_session = _GraphSession({
        "value": [{
            "id": "graph-history-1",
            "conversationId": "conversation-1",
            "subject": "MUST NOT BE REQUESTED",
            "body": {"contentType": "text", "content": "MUST BE IGNORED"},
            "from": {"emailAddress": {"address": "outside@newco.example"}},
            "toRecipients": [{
                "emailAddress": {"address": "ops@agency.example"}
            }],
            "receivedDateTime": "2026-09-08T12:10:00+00:00",
            "isDraft": False,
        }]
    })
    graph_client = OutlookGraphReadClient(
        access_token="synthetic-graph-token",
        mailbox_id="ops@agency.example",
        session=graph_session,
    )
    graph_messages = graph_client.list_counterparty_discovery_history(
        start_at=NOW.replace(hour=11),
        end_at=NOW.replace(hour=13),
        max_messages=2,
    )
    graph_request = graph_session.requests[0]
    select_fields = str((graph_request.get("params") or {}).get("$select") or "")
    if (
        graph_request.get("method") != "GET"
        or "body" in select_fields.split(",")
        or "subject" in select_fields.split(",")
        or "conversationId" not in select_fields.split(",")
        or not graph_messages
        or graph_messages[0].body_text != ""
        or graph_messages[0].subject != ""
        or graph_messages[0].in_reply_to_reference != "conversation-1"
    ):
        failures.append("counterparty Graph discovery did not remain metadata-only")

    balanced_session = _GraphSession([
        {
            "value": [
                {
                    "id": "in-zero",
                    "conversationId": "conversation-zero",
                    "from": {"emailAddress": {"address": "zero@example.invalid"}},
                    "toRecipients": [], "ccRecipients": [], "bccRecipients": [],
                    "receivedDateTime": "2026-09-08T12:30:00+00:00", "isDraft": False,
                },
                {
                    "id": "in-cc",
                    "conversationId": "conversation-cc",
                    "from": {"emailAddress": {"address": "cc-sender@example.invalid"}},
                    "toRecipients": [],
                    "ccRecipients": [{"emailAddress": {"address": "ops@agency.example"}}],
                    "bccRecipients": [],
                    "receivedDateTime": "2026-09-08T12:20:00+00:00", "isDraft": False,
                },
                {
                    "id": "in-overflow",
                    "conversationId": "conversation-overflow",
                    "from": {"emailAddress": {"address": "overflow@example.invalid"}},
                    "toRecipients": [{"emailAddress": {"address": "ops@agency.example"}}],
                    "ccRecipients": [], "bccRecipients": [],
                    "receivedDateTime": "2026-09-08T12:10:00+00:00", "isDraft": False,
                },
            ],
            "@odata.nextLink": (
                "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$skiptoken=more"
            ),
        },
        {
            "value": [
                {
                    "id": "sent-bcc",
                    "conversationId": "conversation-bcc",
                    "from": {"emailAddress": {"address": "ops@agency.example"}},
                    "toRecipients": [], "ccRecipients": [],
                    "bccRecipients": [{"emailAddress": {"address": "bcc-target@example.invalid"}}],
                    "sentDateTime": "2026-09-08T12:25:00+00:00", "isDraft": False,
                },
                {
                    "id": "sent-too-many",
                    "conversationId": "conversation-too-many",
                    "from": {"emailAddress": {"address": "ops@agency.example"}},
                    "toRecipients": [
                        {"emailAddress": {"address": f"r{index}@example.invalid"}}
                        for index in range(51)
                    ],
                    "ccRecipients": [], "bccRecipients": [],
                    "sentDateTime": "2026-09-08T12:15:00+00:00", "isDraft": False,
                },
                {
                    "id": "sent-overflow",
                    "conversationId": "conversation-sent-overflow",
                    "from": {"emailAddress": {"address": "ops@agency.example"}},
                    "toRecipients": [{"emailAddress": {"address": "overflow2@example.invalid"}}],
                    "ccRecipients": [], "bccRecipients": [],
                    "sentDateTime": "2026-09-08T12:05:00+00:00", "isDraft": False,
                },
            ]
        },
    ])
    balanced_client = OutlookGraphReadClient(
        access_token="synthetic-graph-token",
        mailbox_id="ops@agency.example",
        session=balanced_session,
    )
    balanced_messages = balanced_client.list_counterparty_discovery_history(
        start_at=NOW.replace(hour=11), end_at=NOW.replace(hour=13), max_messages=4,
    )
    scan = balanced_client.last_counterparty_discovery_scan
    balanced_result = discover_historical_counterparties(
        messages=balanced_messages,
        agency_addresses=["ops@agency.example"],
        master_repository=InMemoryMasterDataRepository(),
    )
    balanced_by_email = {
        item.email_address: item for item in balanced_result.candidates
    }
    if (
        len(balanced_session.requests) != 2
        or not all(
            str((request.get("params") or {}).get("$orderby") or "").endswith(" desc")
            for request in balanced_session.requests
        )
        or any(
            field in str((request.get("params") or {}).get("$select") or "").split(",")
            for request in balanced_session.requests
            for field in ("body", "subject")
        )
        or not all(
            {"ccRecipients", "bccRecipients"}.issubset(
                set(str((request.get("params") or {}).get("$select") or "").split(","))
            )
            for request in balanced_session.requests
        )
        or scan.get("examined_message_count") != 4
        or scan.get("accepted_message_count") != 2
        or scan.get("rejected_message_count") != 2
        or scan.get("folder_examined_counts") != {"inbox": 2, "sentitems": 2}
        or scan.get("folder_quotas") != {"inbox": 2, "sentitems": 2}
        or scan.get("truncated") is not True
        or scan.get("newest_first") is not True
        or balanced_by_email.get("cc-sender@example.invalid") is None
        or balanced_by_email["cc-sender@example.invalid"].inbound_count != 1
        or balanced_by_email.get("bcc-target@example.invalid") is None
        or balanced_by_email["bcc-target@example.invalid"].outbound_count != 1
    ):
        failures.append("balanced discovery coverage/cap/Cc-Bcc handling is incorrect")

    range_session = _GraphSession({"value": []})
    range_client = OutlookGraphReadClient(
        access_token="synthetic-graph-token",
        mailbox_id="ops@agency.example",
        session=range_session,
    )
    try:
        range_client.list_counterparty_discovery_history(
            start_at=NOW - timedelta(days=371), end_at=NOW, max_messages=2,
        )
    except ValueError:
        pass
    else:
        failures.append("Graph discovery accepted a history window over 370 days")
    if range_session.requests:
        failures.append("Graph discovery validated the long range after provider access")

    with physical_temporary_directory() as temporary:
        root = Path(temporary)
        cache_path = root / "readonly-token-cache.json"
        config = MicrosoftAuthConfig(
            tenant_id="11111111-1111-1111-1111-111111111111",
            client_id="22222222-2222-2222-2222-222222222222",
            mailbox_id="ops@agency.example",
            token_cache_path=cache_path,
            scopes=("Mail.ReadBasic",),
        )
        token_calls: list[bool] = []

        def token_provider(_config):
            token_calls.append(True)
            return "synthetic-read-token"

        try:
            run_outlook_counterparty_discovery(
                config=config,
                start_at=NOW,
                end_at=NOW.replace(hour=13),
                max_messages=100,
                authorization_confirmed=False,
                master_repository=repository,
                token_provider=token_provider,
            )
        except CounterpartyDiscoveryAuthorizationError:
            pass
        else:
            failures.append("discovery ran without explicit historical authorization")
        if token_calls:
            failures.append("unauthorized discovery reached Outlook token acquisition")

        broad_read_config = MicrosoftAuthConfig(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            mailbox_id=config.mailbox_id,
            token_cache_path=config.token_cache_path,
            scopes=("Mail.Read",),
        )
        try:
            run_outlook_counterparty_discovery(
                config=broad_read_config,
                start_at=NOW,
                end_at=NOW.replace(hour=13),
                max_messages=100,
                authorization_confirmed=True,
                master_repository=repository,
                token_provider=token_provider,
            )
        except MicrosoftAuthConfigurationError:
            pass
        else:
            failures.append("discovery accepted broader Mail.Read authorization")
        if token_calls:
            failures.append("Mail.Read rejection happened after token acquisition")

        send_config = MicrosoftAuthConfig(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            mailbox_id=config.mailbox_id,
            token_cache_path=config.token_cache_path,
            scopes=("Mail.Read", "Mail.Send"),
        )
        try:
            run_outlook_counterparty_discovery(
                config=send_config,
                start_at=NOW,
                end_at=NOW.replace(hour=13),
                max_messages=100,
                authorization_confirmed=True,
                master_repository=repository,
                token_provider=token_provider,
            )
        except MicrosoftAuthConfigurationError:
            pass
        else:
            failures.append("discovery accepted Mail.Send authorization")
        if token_calls:
            failures.append("Mail.Send discovery rejection happened after token acquisition")

        try:
            run_outlook_counterparty_discovery(
                config=config,
                start_at=NOW - timedelta(days=371),
                end_at=NOW,
                max_messages=100,
                authorization_confirmed=True,
                master_repository=repository,
                token_provider=token_provider,
            )
        except ValueError:
            pass
        else:
            failures.append("workflow discovery accepted a history window over 370 days")
        if token_calls:
            failures.append("workflow validated the long range after token acquisition")

        workflow_messages = _history_messages()[:-1]
        fake_client = _FakeHistoryClient(messages=workflow_messages)

        def graph_factory(**_kwargs):
            return fake_client

        payload = run_outlook_counterparty_discovery(
            config=config,
            start_at=NOW,
            end_at=NOW.replace(hour=13),
            max_messages=100,
            authorization_confirmed=True,
            master_repository=repository,
            token_provider=token_provider,
            graph_client_factory=graph_factory,
        )
        if len(token_calls) != 1:
            failures.append("authorized discovery did not acquire exactly one read token")
        if fake_client.messages:
            failures.append("raw historical message batch was not cleared after discovery")
        payload_text = json.dumps(payload, default=str)
        if (
            "synthetic-read-token" in payload_text
            or payload.get("raw_messages_persisted") is not False
            or payload.get("master_data_mutated") is not False
            or payload.get("history_scan", {}).get("truncated") is not False
        ):
            failures.append("discovery workflow leaked token or claimed persistence/mutation")

        auth_profile = root / "outlook-readonly.env"
        auth_profile.write_text(
            "\n".join(
                [
                    "MINAI_OUTLOOK_TENANT_ID=11111111-1111-1111-1111-111111111111",
                    "MINAI_OUTLOOK_CLIENT_ID=22222222-2222-2222-2222-222222222222",
                    "MINAI_OUTLOOK_MAILBOX_ID=ops@agency.example",
                    f"MINAI_OUTLOOK_TOKEN_CACHE_PATH={cache_path}",
                ]
            ) + "\n",
            encoding="utf-8",
        )
        if os.name == "posix":
            os.chmod(auth_profile, 0o600)

        with patch.dict(
            os.environ,
            {
                "MINAI_OUTBOUND_MODE": "controlled_send",
                "OPENAI_API_KEY": "must-not-leak",
            },
            clear=False,
        ):
            readonly = build_readonly_auth_config(auth_profile)
        if (
            readonly.scopes != ("Mail.ReadBasic",)
            or readonly.mailbox_id != "ops@agency.example"
        ):
            failures.append("read-only auth profile inherited hostile parent authority")

        if os.name == "posix":
            permissive_profile = root / "permissive.env"
            permissive_profile.write_text(
                auth_profile.read_text(encoding="utf-8"), encoding="utf-8"
            )
            os.chmod(permissive_profile, 0o644)
            try:
                build_readonly_auth_config(permissive_profile)
            except OutlookDiscoveryProfileError:
                pass
            else:
                failures.append("permissive discovery auth profile was accepted")

        relative_cache_profile = root / "relative-cache.env"
        relative_cache_profile.write_text(
            auth_profile.read_text(encoding="utf-8").replace(
                str(cache_path), "~/readonly-token-cache.json"
            ),
            encoding="utf-8",
        )
        if os.name == "posix":
            os.chmod(relative_cache_profile, 0o600)
        try:
            build_readonly_auth_config(relative_cache_profile)
        except OutlookDiscoveryProfileError:
            pass
        else:
            failures.append("discovery auth profile expanded a non-literal token-cache path")

        forbidden_profile = root / "forbidden.env"
        forbidden_profile.write_text(
            auth_profile.read_text(encoding="utf-8")
            + "MINAI_OUTBOUND_MODE=controlled_send\n",
            encoding="utf-8",
        )
        if os.name == "posix":
            os.chmod(forbidden_profile, 0o600)
        try:
            build_readonly_auth_config(forbidden_profile)
        except OutlookDiscoveryProfileError:
            pass
        else:
            failures.append("discovery auth profile accepted outbound authority")

        try:
            _resolve_external_profile(Path(__file__).resolve())
        except OutlookDiscoveryProfileError:
            pass
        else:
            failures.append("repository-contained discovery auth profile was accepted")

    alias_result = discover_historical_counterparties(
        messages=[
            _message(
                "alias-1",
                sender="alias@agency.example",
                recipients=["alias-target@newco.example"],
                subject="Alias route",
                body="Transient",
                minute=7,
            )
        ],
        agency_addresses=["ops@agency.example", "alias@agency.example"],
        master_repository=InMemoryMasterDataRepository(),
    )
    if (
        alias_result.candidate_count != 1
        or alias_result.candidates[0].email_address
        != "alias-target@newco.example"
        or alias_result.candidates[0].outbound_count != 1
    ):
        failures.append("agency alias was not treated as agency-owned history")

    return {
        "name": "Read-only Outlook counterparty discovery",
        "passed": not failures,
        "failures": failures,
    }


def main() -> int:
    result = evaluate_counterparty_discovery_regressions()
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
