from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.core.customer_memory import (
    CustomerMemoryProfile,
)
from src.core.extraction_confirmation import (
    ShipmentProposalSnapshot,
)
from src.core.extraction_confirmation_repository import (
    InMemoryExtractionProposalRepository,
)
from src.core.mail import (
    InboundAttachmentMetadata,
    InboundMailEnvelope,
    MailSendResult,
)
from src.core.models import Package, Shipment
from src.core.operational_data import (
    OperationalDataSources,
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
from src.core.supplier_rfq_repository import (
    InMemorySupplierRFQRepository,
)
from src.workflow.outlook_inbound_router import (
    process_controlled_outlook_inbound_mail,
)


CUSTOMER_EMAIL = "ops@pilot.example"
SUPPLIER_EMAIL = "pricing@supplier.example"


def _sources():
    root = Path(
        "/approved/external/test-pack"
    )

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


def _profiles(
    *,
    customer_email=CUSTOMER_EMAIL,
):
    return [
        CustomerMemoryProfile(
            customer_name="Pilot Customer",
            active=True,
            trusted_sender_addresses=[
                customer_email
            ],
        )
    ]


def _shipment():
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
    sender,
    message_id,
    subject="Freight inquiry",
    has_attachments=False,
    attachment_manifest=None,
):
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id="pilot@example.invalid",
        sender_address=sender,
        subject=subject,
        body_text=(
            "Controlled inbound regression message."
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
        has_attachments=has_attachments,
        attachment_manifest=list(attachment_manifest or []),
        source="email",
    )


def _supplier_repository(
    *,
    recipient_email=SUPPLIER_EMAIL,
    rfq_ids=("rfq-router-1",),
):
    repository = (
        InMemorySupplierRFQRepository()
    )

    for index, rfq_id in enumerate(
        rfq_ids,
        start=1,
    ):
        reference = (
            build_supplier_rfq_reference(
                rfq_id
            )
        )

        draft = SupplierRFQDraft(
            rfq_id=rfq_id,
            workflow_id=(
                f"workflow-{rfq_id}"
            ),
            supplier_name=(
                "Regression Supplier"
            ),
            priority=index,
            recipient_email=(
                recipient_email
            ),
            subject=(
                f"[{reference}] RFQ"
            ),
            body=(
                f"RFQ Reference: {reference}"
            ),
        )

        repository.save_drafts(
            [draft]
        )

        draft = approve_supplier_rfq(
            repository,
            rfq_id,
            approved_by=(
                "Regression Operator"
            ),
        )

        send_supplier_rfq(
            repository,
            rfq_id,
            MailSendResult(
                operation_id=(
                    f"supplier-rfq:{rfq_id}"
                ),
                status="sent",
                reason=(
                    "Regression send evidence."
                ),
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


class RecordingSupplierParser:
    def __init__(self):
        self.calls = []

    def parse(self, safe_text):
        self.calls.append(
            safe_text
        )

        return SupplierResponseExtraction(
            status="quoted",
            cost=2200.0,
            currency="EUR",
        )


def evaluate_outlook_inbound_router_regressions():
    failures = []
    passes = []

    def check(condition, label):
        if condition:
            passes.append(label)
        else:
            failures.append(label)

    proposal_repository = (
        InMemoryExtractionProposalRepository()
    )

    customer_calls = []

    def shipment_parser(safe_text):
        customer_calls.append(
            safe_text
        )
        return _shipment()

    supplier_repository = (
        _supplier_repository()
    )

    supplier_parser = (
        RecordingSupplierParser()
    )

    with (
        patch(
            "src.workflow."
            "outlook_inbound_router."
            "load_customer_memory",
            return_value=_profiles(),
        ),
        patch(
            "src.workflow."
            "outlook_inbound_ingestion."
            "load_customer_memory",
            return_value=_profiles(),
        ),
    ):
        customer_result = (
            process_controlled_outlook_inbound_mail(
                mail=_mail(
                    sender=CUSTOMER_EMAIL,
                    message_id="customer-1",
                ),
                shipment_parser=shipment_parser,
                supplier_parser=(
                    supplier_parser
                ),
                proposal_repository=(
                    proposal_repository
                ),
                supplier_repository=(
                    supplier_repository
                ),
                operational_data_sources=(
                    _sources()
                ),
            )
        )

    check(
        customer_result.get(
            "inbound_route"
        )
        == "customer"
        and customer_result.get(
            "result_type"
        )
        == (
            "extraction_confirmation_required"
        )
        and len(customer_calls) == 1
        and not supplier_parser.calls,
        "trusted customer routes only to customer parser",
    )

    supplier_subject = (
        "Re: ["
        + build_supplier_rfq_reference(
            "rfq-router-1"
        )
        + "] RFQ"
    )

    with patch(
        "src.workflow."
        "outlook_inbound_router."
        "load_customer_memory",
        return_value=_profiles(),
    ):
        supplier_result = (
            process_controlled_outlook_inbound_mail(
                mail=_mail(
                    sender=SUPPLIER_EMAIL,
                    message_id="supplier-1",
                    subject=supplier_subject,
                ),
                shipment_parser=shipment_parser,
                supplier_parser=(
                    supplier_parser
                ),
                proposal_repository=(
                    proposal_repository
                ),
                supplier_repository=(
                    supplier_repository
                ),
                operational_data_sources=(
                    _sources()
                ),
            )
        )

    check(
        supplier_result.get(
            "inbound_route"
        )
        == "supplier"
        and supplier_result.get(
            "ingestion_status"
        )
        == "response_attached"
        and len(supplier_parser.calls)
        == 1
        and len(customer_calls)
        == 1,
        "verified supplier routes only to supplier parser",
    )

    overlap_repository = (
        _supplier_repository(
            recipient_email=(
                CUSTOMER_EMAIL
            ),
            rfq_ids=(
                "rfq-overlap",
            ),
        )
    )

    overlap_parser = (
        RecordingSupplierParser()
    )

    overlap_customer_calls = []

    def overlap_customer_parser(
        safe_text
    ):
        overlap_customer_calls.append(
            safe_text
        )
        return _shipment()

    overlap_subject = (
        "Re: ["
        + build_supplier_rfq_reference(
            "rfq-overlap"
        )
        + "]"
    )

    with patch(
        "src.workflow."
        "outlook_inbound_router."
        "load_customer_memory",
        return_value=_profiles(),
    ):
        overlap = (
            process_controlled_outlook_inbound_mail(
                mail=_mail(
                    sender=CUSTOMER_EMAIL,
                    message_id="overlap-1",
                    subject=overlap_subject,
                ),
                shipment_parser=(
                    overlap_customer_parser
                ),
                supplier_parser=(
                    overlap_parser
                ),
                proposal_repository=(
                    InMemoryExtractionProposalRepository()
                ),
                supplier_repository=(
                    overlap_repository
                ),
                operational_data_sources=(
                    _sources()
                ),
            )
        )

    check(
        overlap.get(
            "reason_code"
        )
        == (
            "sender_matches_customer_and_supplier"
        )
        and not overlap_parser.calls
        and not overlap_customer_calls,
        "customer supplier identity overlap blocks before AI",
    )

    ambiguous_repository = (
        _supplier_repository(
            rfq_ids=(
                "rfq-amb-a",
                "rfq-amb-b",
            ),
        )
    )

    ambiguous_parser = (
        RecordingSupplierParser()
    )

    with patch(
        "src.workflow."
        "outlook_inbound_router."
        "load_customer_memory",
        return_value=_profiles(),
    ):
        ambiguous = (
            process_controlled_outlook_inbound_mail(
                mail=_mail(
                    sender=SUPPLIER_EMAIL,
                    message_id="ambiguous-1",
                ),
                shipment_parser=shipment_parser,
                supplier_parser=(
                    ambiguous_parser
                ),
                proposal_repository=(
                    proposal_repository
                ),
                supplier_repository=(
                    ambiguous_repository
                ),
                operational_data_sources=(
                    _sources()
                ),
            )
        )

    check(
        ambiguous.get(
            "reason_code"
        )
        == (
            "supplier_rfq_correlation_ambiguous"
        )
        and not ambiguous_parser.calls,
        "ambiguous supplier RFQ blocks before AI",
    )

    unrelated_parser = (
        RecordingSupplierParser()
    )

    with patch(
        "src.workflow."
        "outlook_inbound_router."
        "load_customer_memory",
        return_value=_profiles(),
    ):
        unrelated = (
            process_controlled_outlook_inbound_mail(
                mail=_mail(
                    sender=(
                        "outsider@example.invalid"
                    ),
                    message_id="outsider-1",
                ),
                shipment_parser=shipment_parser,
                supplier_parser=(
                    unrelated_parser
                ),
                proposal_repository=(
                    proposal_repository
                ),
                supplier_repository=(
                    _supplier_repository()
                ),
                operational_data_sources=(
                    _sources()
                ),
            )
        )

    check(
        unrelated.get(
            "reason_code"
        )
        == (
            "sender_not_in_verified_inbound_scope"
        )
        and not unrelated_parser.calls,
        "untrusted unrelated sender blocks before AI",
    )

    attachment_parser = (
        RecordingSupplierParser()
    )

    attachment_customer_calls = []

    def attachment_customer_parser(
        safe_text
    ):
        attachment_customer_calls.append(
            safe_text
        )
        return _shipment()

    with patch(
        "src.workflow."
        "outlook_inbound_router."
        "load_customer_memory",
        return_value=_profiles(),
    ):
        attachment = (
            process_controlled_outlook_inbound_mail(
                mail=_mail(
                    sender=CUSTOMER_EMAIL,
                    message_id="attachment-1",
                    has_attachments=True,
                    attachment_manifest=[
                        InboundAttachmentMetadata(
                            name="quote.pdf",
                            content_type="application/pdf",
                            size_bytes=4096,
                            kind="file",
                        )
                    ],
                ),
                shipment_parser=(
                    attachment_customer_parser
                ),
                supplier_parser=(
                    attachment_parser
                ),
                proposal_repository=(
                    proposal_repository
                ),
                supplier_repository=(
                    _supplier_repository()
                ),
                operational_data_sources=(
                    _sources()
                ),
            )
        )

    check(
        attachment.get(
            "reason_code"
        )
        == (
            "outlook_attachment_retrieval_not_available"
        )
        and attachment.get("inbound_route") == "customer"
        and attachment.get("attachment_intake_status")
        == "metadata_allowlisted"
        and attachment.get("attachment_retrieval_status")
        == "manual_review"
        and attachment.get("attachment_intake_reason_code")
        == "attachment_metadata_allowlisted"
        and not attachment_parser.calls
        and not attachment_customer_calls,
        "allowlisted attachments require controlled retriever before AI",
    )

    invalid_provider_parser = (
        RecordingSupplierParser()
    )

    invalid_customer_calls = []

    def invalid_customer_parser(
        safe_text
    ):
        invalid_customer_calls.append(
            safe_text
        )
        return _shipment()

    invalid_mail = _mail(
        sender=CUSTOMER_EMAIL,
        message_id="invalid-provider-1",
    ).model_copy(
        update={
            "provider_name": "manual",
        }
    )

    invalid_provider = (
        process_controlled_outlook_inbound_mail(
            mail=invalid_mail,
            shipment_parser=(
                invalid_customer_parser
            ),
            supplier_parser=(
                invalid_provider_parser
            ),
            proposal_repository=(
                proposal_repository
            ),
            supplier_repository=(
                _supplier_repository()
            ),
            operational_data_sources=(
                _sources()
            ),
        )
    )

    check(
        invalid_provider.get(
            "reason_code"
        )
        == (
            "outlook_provider_metadata_invalid"
        )
        and not invalid_provider_parser.calls
        and not invalid_customer_calls,
        "non Graph provider blocks before routing",
    )

    return {
        "name": (
            "Deterministic Outlook inbound router"
        ),
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = (
        evaluate_outlook_inbound_router_regressions()
    )

    for label in result[
        "passed_checks"
    ]:
        print(f"PASS {label}")

    for failure in result[
        "failures"
    ]:
        print(f"FAIL {failure}")

    if result["passed"]:
        print(
            "\nOutlook inbound router "
            "regressions: PASS"
        )
        return 0

    print(
        "\nOutlook inbound router "
        "regressions: FAIL"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
