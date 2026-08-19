from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.core.customer_memory import (
    CustomerMemoryProfile,
)
from src.core.data_provenance import (
    DataProvenanceError,
)
from src.core.extraction_confirmation import (
    ShipmentProposalSnapshot,
)
from src.core.extraction_confirmation_repository import (
    InMemoryExtractionProposalRepository,
)
from src.core.mail import InboundMailEnvelope
from src.core.models import Package, Shipment
from src.core.operational_data import (
    OperationalDataSources,
)
from src.workflow.outlook_inbound_ingestion import (
    process_controlled_outlook_customer_mail,
)


def _sources() -> OperationalDataSources:
    root = Path("/approved/external/test-pack")
    return OperationalDataSources(
        provenance_registry_path=(
            root / "provenance_registry.json"
        ),
        customer_memory_path=(
            root / "customer_memory.json"
        ),
        supplier_capabilities_path=(
            root / "supplier_capabilities.json"
        ),
    )


def _shipment() -> ShipmentProposalSnapshot:
    shipment = Shipment(
        customer_name="Pilot Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        service_type="FTL",
        cargo_ready_date="2026-09-10",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[
            Package(
                package_type="pallet",
                quantity=20,
                length_cm=120,
                width_cm=80,
                height_cm=150,
                weight_kg=1000,
            )
        ],
    )

    return ShipmentProposalSnapshot.model_validate(
        shipment.model_dump()
    )


def _mail(
    *,
    message_id: str,
    sender: str = "ops@pilot.example",
    has_attachments: bool = False,
) -> InboundMailEnvelope:
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id="operations@example.invalid",
        sender_address=sender,
        sender_name="Customer Operator",
        recipient_addresses=[
            "operations@example.invalid"
        ],
        subject="Freight inquiry",
        body_text=(
            "Please quote Adana to Hamburg.\n"
            "Contact john@example.com"
        ),
        received_at=datetime(
            2026,
            8,
            18,
            8,
            30,
            tzinfo=timezone.utc,
        ),
        has_attachments=has_attachments,
        source="email",
    )


def _trusted_profiles():
    return [
        CustomerMemoryProfile(
            customer_name="Pilot Customer",
            active=True,
            trusted_sender_addresses=[
                "ops@pilot.example"
            ],
        )
    ]


def evaluate_outlook_inbound_gate_regressions():
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

    repository = (
        InMemoryExtractionProposalRepository()
    )
    parsed_bodies: list[str] = []

    def parser(
        body: str,
    ) -> ShipmentProposalSnapshot:
        parsed_bodies.append(str(body))
        return _shipment()

    mail = _mail(
        message_id="immutable-message-1"
    )

    with patch(
        "src.workflow."
        "outlook_inbound_ingestion."
        "load_customer_memory",
        return_value=_trusted_profiles(),
    ):
        first = (
            process_controlled_outlook_customer_mail(
                mail=mail,
                shipment_parser=parser,
                proposal_repository=repository,
                operational_data_sources=_sources(),
            )
        )

        duplicate = (
            process_controlled_outlook_customer_mail(
                mail=mail,
                shipment_parser=parser,
                proposal_repository=repository,
                operational_data_sources=_sources(),
            )
        )

    check(
        first["result_type"]
        == "extraction_confirmation_required"
        and first["ingestion_status"]
        == "created"
        and first["inbound_gate_status"]
        == "pass",
        "trusted Outlook sender reaches proposal only",
    )

    check(
        len(parsed_bodies) == 1
        and "<EMAIL_REDACTED>"
        in parsed_bodies[0]
        and "john@example.com"
        not in parsed_bodies[0],
        "privacy transform runs before parser",
    )

    proposal = first["extraction_proposal"]
    stored_mail = proposal.inbound_mail

    check(
        stored_mail.provider_name
        == "microsoft_graph"
        and stored_mail.mailbox_id
        == "operations@example.invalid"
        and stored_mail.external_message_id
        == "immutable-message-1"
        and stored_mail.privacy_transformed
        is True
        and stored_mail.raw_body_sha256
        is not None,
        "provider metadata survives privacy boundary",
    )

    check(
        duplicate["ingestion_status"]
        == "duplicate_existing_proposal"
        and len(parsed_bodies) == 1,
        "duplicate Outlook mail does not reparse",
    )

    attachment_calls = len(parsed_bodies)

    with patch(
        "src.workflow."
        "outlook_inbound_ingestion."
        "load_customer_memory",
        return_value=_trusted_profiles(),
    ):
        attachment_result = (
            process_controlled_outlook_customer_mail(
                mail=_mail(
                    message_id="attachment-1",
                    has_attachments=True,
                ),
                shipment_parser=parser,
                proposal_repository=repository,
                operational_data_sources=_sources(),
            )
        )

    check(
        attachment_result["result_type"]
        == "inbound_mail_manual_review_required"
        and attachment_result["reason_code"]
        == "outlook_attachments_not_supported"
        and len(parsed_bodies)
        == attachment_calls,
        "attachment blocks before parser",
    )

    untrusted_calls = len(parsed_bodies)

    with patch(
        "src.workflow."
        "outlook_inbound_ingestion."
        "load_customer_memory",
        return_value=_trusted_profiles(),
    ):
        untrusted = (
            process_controlled_outlook_customer_mail(
                mail=_mail(
                    message_id="untrusted-1",
                    sender="other@example.test",
                ),
                shipment_parser=parser,
                proposal_repository=repository,
                operational_data_sources=_sources(),
            )
        )

    check(
        untrusted["result_type"]
        == "inbound_sender_verification_required"
        and untrusted["reason_code"]
        == "sender_not_in_verified_pilot_scope"
        and len(parsed_bodies)
        == untrusted_calls,
        "untrusted sender blocks before parser",
    )

    ambiguous_profiles = [
        CustomerMemoryProfile(
            customer_name="Pilot Customer A",
            active=True,
            trusted_sender_domains=[
                "pilot.example"
            ],
        ),
        CustomerMemoryProfile(
            customer_name="Pilot Customer B",
            active=True,
            trusted_sender_domains=[
                "pilot.example"
            ],
        ),
    ]

    ambiguous_calls = len(parsed_bodies)

    with patch(
        "src.workflow."
        "outlook_inbound_ingestion."
        "load_customer_memory",
        return_value=ambiguous_profiles,
    ):
        ambiguous = (
            process_controlled_outlook_customer_mail(
                mail=_mail(
                    message_id="ambiguous-1"
                ),
                shipment_parser=parser,
                proposal_repository=repository,
                operational_data_sources=_sources(),
            )
        )

    check(
        ambiguous["reason_code"]
        == (
            "sender_matches_multiple_pilot_customers"
        )
        and len(parsed_bodies)
        == ambiguous_calls,
        "ambiguous trusted sender blocks",
    )

    missing_sources_calls = len(parsed_bodies)

    missing_sources = (
        process_controlled_outlook_customer_mail(
            mail=_mail(
                message_id="no-sources-1"
            ),
            shipment_parser=parser,
            proposal_repository=repository,
            operational_data_sources=None,
        )
    )

    check(
        missing_sources["result_type"]
        == "data_provenance_blocked"
        and len(parsed_bodies)
        == missing_sources_calls,
        "missing pilot data blocks before parser",
    )

    provenance_calls = len(parsed_bodies)

    with patch(
        "src.workflow."
        "outlook_inbound_ingestion."
        "load_customer_memory",
        side_effect=DataProvenanceError(
            "raw internal path must not escape"
        ),
    ):
        provenance = (
            process_controlled_outlook_customer_mail(
                mail=_mail(
                    message_id="bad-provenance-1"
                ),
                shipment_parser=parser,
                proposal_repository=repository,
                operational_data_sources=_sources(),
            )
        )

    check(
        provenance["result_type"]
        == "data_provenance_blocked"
        and provenance["reason_code"]
        == "pilot_customer_data_unverified"
        and "path"
        not in str(provenance)
        and len(parsed_bodies)
        == provenance_calls,
        "provenance failure sanitized and blocks",
    )

    spoofed_calls = len(parsed_bodies)

    spoofed = _mail(
        message_id="spoofed-1"
    ).model_copy(
        update={
            "provider_name": "manual",
        }
    )

    with patch(
        "src.workflow."
        "outlook_inbound_ingestion."
        "load_customer_memory",
        return_value=_trusted_profiles(),
    ):
        spoofed_result = (
            process_controlled_outlook_customer_mail(
                mail=spoofed,
                shipment_parser=parser,
                proposal_repository=repository,
                operational_data_sources=_sources(),
            )
        )

    check(
        spoofed_result["result_type"]
        == "inbound_mail_rejected"
        and len(parsed_bodies)
        == spoofed_calls,
        "non-Graph provider claim rejected",
    )

    pretransformed_calls = len(parsed_bodies)

    pretransformed = _mail(
        message_id="pretransformed-1"
    ).model_copy(
        update={
            "privacy_transformed": True,
        }
    )

    pretransformed_result = (
        process_controlled_outlook_customer_mail(
            mail=pretransformed,
            shipment_parser=parser,
            proposal_repository=repository,
            operational_data_sources=_sources(),
        )
    )

    check(
        pretransformed_result["result_type"]
        == "inbound_mail_rejected"
        and len(parsed_bodies)
        == pretransformed_calls,
        "pre-transformed provider payload rejected",
    )

    return {
        "name": (
            "Controlled Outlook inbound gate"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main() -> int:
    result = (
        evaluate_outlook_inbound_gate_regressions()
    )

    for label in result["passed_checks"]:
        print(f"PASS {label}")

    for failure in result["failures"]:
        print(f"FAIL {failure}")

    if result["passed"]:
        print(
            "\nOutlook inbound gate "
            "regressions: PASS"
        )
        return 0

    print(
        "\nOutlook inbound gate "
        "regressions: FAIL"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
