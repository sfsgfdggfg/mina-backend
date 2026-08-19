from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src import api
from src.ai.supplier_response_parser import (
    SupplierResponseParserUnavailableError,
)
from src.core.mail import (
    InboundMailEnvelope,
    MailSendResult,
)
from src.core.supplier_response_ingestion import (
    SupplierResponseExtraction,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    build_supplier_rfq_reference,
)
from src.core.supplier_rfq_lifecycle import (
    approve_supplier_rfq,
    send_supplier_rfq,
)
from src.core.pilot_store import (
    SQLitePilotStore,
)
from src.core.sqlite_repositories import (
    SQLiteSupplierRFQRepository,
)
from src.core.supplier_rfq_repository import (
    InMemorySupplierRFQRepository,
)
from src.integrations.microsoft_auth import (
    MicrosoftAuthConfig,
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
SUPPLIER = "pricing@supplier.example"
TOKEN = "supplier-pull-secret-token"



class _EmptyProposalRepository:
    """Supplier-only fixture with no prior customer ingestion."""

    def find_by_message_key(
        self,
        message_key: str,
    ):
        return None


def _repository(
    rfq_id="rfq-outlook-supplier",
):
    repository = (
        InMemorySupplierRFQRepository()
    )

    reference = (
        build_supplier_rfq_reference(
            rfq_id
        )
    )

    draft = SupplierRFQDraft(
        rfq_id=rfq_id,
        workflow_id=f"workflow-{rfq_id}",
        supplier_name="Regression Supplier",
        priority=1,
        recipient_email=SUPPLIER,
        subject=f"[{reference}] RFQ",
        body=f"RFQ Reference: {reference}",
    )

    repository.save_drafts([draft])

    approve_supplier_rfq(
        repository,
        rfq_id,
        approved_by="Regression Operator",
    )

    send_supplier_rfq(
        repository,
        rfq_id,
        MailSendResult(
            operation_id=(
                f"supplier-rfq:{rfq_id}"
            ),
            status="sent",
            reason="Regression send evidence.",
            provider_name=(
                "regression-provider"
            ),
            provider_message_id=(
                f"outbound-{rfq_id}"
            ),
            sent_at=datetime(
                2026,
                8,
                19,
                9,
                0,
                0,
            ),
        ),
    )

    return repository


def _mail(
    message_id,
    rfq_id="rfq-outlook-supplier",
    *,
    sender=SUPPLIER,
    body_text=None,
):
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id=MAILBOX,
        sender_address=sender,
        recipient_addresses=[MAILBOX],
        subject=(
            "Re: ["
            + build_supplier_rfq_reference(
                rfq_id
            )
            + "]"
        ),
        body_text=(
            body_text
            or (
                "We quote EUR 2200 all in. "
                "RAW SUPPLIER BODY MUST NOT "
                "APPEAR IN PULL SUMMARY."
            )
        ),
        received_at=datetime(
            2026,
            8,
            19,
            10,
            0,
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
    ):
        self.access_token = access_token
        self.mailbox_id = mailbox_id
        self.messages = messages

    def list_inbox_messages(
        self,
        *,
        limit,
    ):
        return self.messages[:limit]


class _SupplierParser:
    def __init__(self):
        self.calls = 0

    def parse(self, safe_text):
        self.calls += 1
        return SupplierResponseExtraction(
            status="quoted",
            cost=2200.0,
            currency="EUR",
        )


class _UnavailableParser:
    def parse(self, safe_text):
        raise (
            SupplierResponseParserUnavailableError(
                "provider secret must not escape"
            )
        )


def evaluate_outlook_supplier_pull_regressions():
    failures = []
    passes = []

    def check(condition, label):
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

        repository = _repository()
        parser = _SupplierParser()

        def graph_factory(
            *,
            access_token,
            mailbox_id,
        ):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[
                    _mail("supplier-message-1"),
                ],
            )

        with patch(
            "src.workflow."
            "outlook_inbound_router."
            "load_customer_memory",
            return_value=[],
        ):
            result = (
                pull_controlled_outlook_inbox(
                    config=config,
                    limit=5,
                    shipment_parser=(
                        lambda value: value
                    ),
                    supplier_parser=parser,
                    proposal_repository=_EmptyProposalRepository(),
                    supplier_repository=repository,
                    operational_data_sources=object(),
                    token_provider=(
                        lambda value: TOKEN
                    ),
                    graph_client_factory=(
                        graph_factory
                    ),
                )
            )

        summary = result["results"][0]

        check(
            result[
                "supplier_response_count"
            ]
            == 1
            and result["proposal_count"] == 0
            and summary[
                "inbound_route"
            ]
            == "supplier"
            and summary[
                "ingestion_status"
            ]
            == "response_attached"
            and summary["rfq_id"]
            == "rfq-outlook-supplier"
            and parser.calls == 1,
            "Outlook pull attaches verified supplier response",
        )

        serialized = repr(result)

        check(
            TOKEN not in serialized
            and SUPPLIER not in serialized
            and "RAW SUPPLIER BODY"
            not in serialized
            and "2200" not in serialized,
            "supplier pull summary remains privacy minimized",
        )

        with patch(
            "src.workflow."
            "outlook_inbound_router."
            "load_customer_memory",
            return_value=[],
        ):
            duplicate = (
                pull_controlled_outlook_inbox(
                    config=config,
                    limit=1,
                    shipment_parser=(
                        lambda value: value
                    ),
                    supplier_parser=parser,
                    proposal_repository=_EmptyProposalRepository(),
                    supplier_repository=repository,
                    operational_data_sources=object(),
                    token_provider=(
                        lambda value: TOKEN
                    ),
                    graph_client_factory=(
                        graph_factory
                    ),
                )
            )

        check(
            duplicate[
                "supplier_response_count"
            ]
            == 0
            and duplicate["results"][0][
                "ingestion_status"
            ]
            == "duplicate_response"
            and parser.calls == 1,
            "supplier Outlook message is idempotent",
        )

        def changed_body_factory(
            *,
            access_token,
            mailbox_id,
        ):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[
                    _mail(
                        "supplier-message-1",
                        body_text=(
                            "We now quote EUR 9999."
                        ),
                    ),
                ],
            )

        with patch(
            "src.workflow."
            "outlook_inbound_router."
            "load_customer_memory",
            return_value=[],
        ):
            changed_body = (
                pull_controlled_outlook_inbox(
                    config=config,
                    limit=1,
                    shipment_parser=(
                        lambda value: value
                    ),
                    supplier_parser=parser,
                    proposal_repository=_EmptyProposalRepository(),
                    supplier_repository=repository,
                    operational_data_sources=object(),
                    token_provider=(
                        lambda value: TOKEN
                    ),
                    graph_client_factory=(
                        changed_body_factory
                    ),
                )
            )

        check(
            changed_body["results"][0][
                "reason_code"
            ]
            == "inbound_message_id_conflict"
            and changed_body["results"][0][
                "ingestion_status"
            ]
            == "blocked"
            and parser.calls == 1
            and len(
                repository.list_responses()
            )
            == 1
            and "9999"
            not in repr(changed_body),
            "changed supplier body under same message ID conflicts",
        )

        def changed_sender_factory(
            *,
            access_token,
            mailbox_id,
        ):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[
                    _mail(
                        "supplier-message-1",
                        sender=(
                            "outsider@example.invalid"
                        ),
                    ),
                ],
            )

        with patch(
            "src.workflow."
            "outlook_inbound_router."
            "load_customer_memory",
            return_value=[],
        ):
            changed_sender = (
                pull_controlled_outlook_inbox(
                    config=config,
                    limit=1,
                    shipment_parser=(
                        lambda value: value
                    ),
                    supplier_parser=parser,
                    proposal_repository=_EmptyProposalRepository(),
                    supplier_repository=repository,
                    operational_data_sources=object(),
                    token_provider=(
                        lambda value: TOKEN
                    ),
                    graph_client_factory=(
                        changed_sender_factory
                    ),
                )
            )

        check(
            changed_sender["results"][0][
                "reason_code"
            ]
            == "inbound_message_id_conflict"
            and parser.calls == 1
            and "outsider@example.invalid"
            not in repr(changed_sender),
            "changed supplier sender under same message ID conflicts",
        )

        legacy_repository = _repository(
            "rfq-legacy-evidence"
        )
        legacy_mail = _mail(
            "supplier-legacy-message",
            "rfq-legacy-evidence",
        )
        legacy_key = (
            legacy_mail.message_deduplication_key
        )

        if legacy_key is None:
            raise RuntimeError(
                "Regression mail did not create "
                "a message key."
            )

        legacy_repository.record_ingested_message(
            legacy_key
        )

        legacy_parser = _SupplierParser()

        def legacy_factory(
            *,
            access_token,
            mailbox_id,
        ):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[legacy_mail],
            )

        with patch(
            "src.workflow."
            "outlook_inbound_router."
            "load_customer_memory",
            return_value=[],
        ):
            legacy_result = (
                pull_controlled_outlook_inbox(
                    config=config,
                    limit=1,
                    shipment_parser=(
                        lambda value: value
                    ),
                    supplier_parser=(
                        legacy_parser
                    ),
                    proposal_repository=_EmptyProposalRepository(),
                    supplier_repository=(
                        legacy_repository
                    ),
                    operational_data_sources=object(),
                    token_provider=(
                        lambda value: TOKEN
                    ),
                    graph_client_factory=(
                        legacy_factory
                    ),
                )
            )

        check(
            legacy_result["results"][0][
                "reason_code"
            ]
            == "inbound_message_id_conflict"
            and legacy_parser.calls == 0
            and not legacy_repository.list_responses(),
            "legacy supplier message evidence fails closed",
        )

        sqlite_path = (
            Path(temp)
            / "supplier-integrity.sqlite3"
        )
        sqlite_repository = (
            SQLiteSupplierRFQRepository(
                SQLitePilotStore(
                    sqlite_path
                )
            )
        )

        sqlite_repository.record_ingested_message(
            "microsoft_graph:"
            "operations@example.invalid:"
            "durable-evidence-1",
            body_sha256="abc123",
            sender_address=SUPPLIER,
        )

        reopened_repository = (
            SQLiteSupplierRFQRepository(
                SQLitePilotStore(
                    sqlite_path
                )
            )
        )

        durable_evidence = (
            reopened_repository
            .get_ingested_message_evidence(
                "microsoft_graph:"
                "operations@example.invalid:"
                "durable-evidence-1"
            )
        )

        check(
            durable_evidence
            == {
                "message_key": (
                    "microsoft_graph:"
                    "operations@example.invalid:"
                    "durable-evidence-1"
                ),
                "body_sha256": "abc123",
                "sender_address": SUPPLIER,
            },
            "supplier message integrity evidence is durable",
        )

        unavailable_repository = (
            _repository(
                "rfq-unavailable"
            )
        )

        def unavailable_factory(
            *,
            access_token,
            mailbox_id,
        ):
            return _GraphClient(
                access_token=access_token,
                mailbox_id=mailbox_id,
                messages=[
                    _mail(
                        "supplier-unavailable",
                        "rfq-unavailable",
                    ),
                    _mail(
                        "supplier-after-unavailable",
                        "rfq-unavailable",
                    ),
                ],
            )

        with patch(
            "src.workflow."
            "outlook_inbound_router."
            "load_customer_memory",
            return_value=[],
        ):
            unavailable = (
                pull_controlled_outlook_inbox(
                    config=config,
                    limit=2,
                    shipment_parser=(
                        lambda value: value
                    ),
                    supplier_parser=(
                        _UnavailableParser()
                    ),
                    proposal_repository=_EmptyProposalRepository(),
                    supplier_repository=(
                        unavailable_repository
                    ),
                    operational_data_sources=object(),
                    token_provider=(
                        lambda value: TOKEN
                    ),
                    graph_client_factory=(
                        unavailable_factory
                    ),
                )
            )

        check(
            unavailable["pull_status"]
            == "partial_parser_unavailable"
            and unavailable[
                "handled_message_count"
            ]
            == 1
            and unavailable["results"][0][
                "reason_code"
            ]
            == (
                "supplier_response_parser_unavailable"
            )
            and "secret"
            not in repr(unavailable),
            "supplier parser outage stops pull safely",
        )

        capture = {}
        sentinel_parser = object()

        def fake_pull(**kwargs):
            capture.update(kwargs)
            return {
                "provider": "microsoft_graph",
                "pull_status": "complete",
                "results": [],
                "mailbox_write_performed": False,
                "automated_send_performed": False,
            }

        with (
            patch.object(
                api.MicrosoftAuthConfig,
                "from_environment",
                return_value=config,
            ),
            patch(
                "src.api."
                "OpenAISupplierResponseParser",
                return_value=sentinel_parser,
            ),
            patch(
                "src.api."
                "pull_controlled_outlook_inbox",
                side_effect=fake_pull,
            ),
        ):
            endpoint = (
                api.pull_outlook_inbound(
                    api.OutlookPullRequest(
                        limit=4
                    )
                )
            )

        check(
            endpoint["pull_status"]
            == "complete"
            and capture["limit"] == 4
            and capture[
                "supplier_parser"
            ]
            is sentinel_parser
            and capture[
                "supplier_repository"
            ]
            is api.supplier_rfq_repository,
            "API wires production supplier path server-side",
        )

    return {
        "name": (
            "Controlled Outlook supplier reply pull"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = (
        evaluate_outlook_supplier_pull_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for failure in result["failures"]:
        print(f"FAIL {failure}")

    if result["passed"]:
        print(
            "\nOutlook supplier pull "
            "regressions: PASS"
        )
        return 0

    print(
        "\nOutlook supplier pull "
        "regressions: FAIL"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
