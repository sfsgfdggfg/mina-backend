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
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master, create_supplier_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
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
    body="Controlled inbound regression message.",
    has_attachments=False,
    attachment_manifest=None,
):
    return InboundMailEnvelope(
        external_message_id=message_id,
        provider_name="microsoft_graph",
        mailbox_id="pilot@example.invalid",
        sender_address=sender,
        subject=subject,
        body_text=body,
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
        overlap.get("inbound_route") == "supplier"
        and overlap.get("transactional_role") == "supplier_response"
        and overlap.get("ingestion_status") == "response_attached"
        and len(overlap_parser.calls) == 1
        and not overlap_customer_calls,
        "matched RFQ makes the message a supplier response even for a dual-role firm",
    )

    dual_role_masters = InMemoryMasterDataRepository()
    create_supplier_master(
        repository=dual_role_masters, entry_id="barsan",
        supplier_name="Barsan Global Logistics", updated_by="Regression",
        trusted_sender_addresses=["beytullah.bulbul@barsan.com"],
    )
    dual_role_jobs = InMemoryMinaJobRepository()
    dual_role_proposals = InMemoryExtractionProposalRepository()

    def dual_role_customer_parser(safe_text):
        return ShipmentProposalSnapshot.model_validate(
            _shipment().model_copy(update={
                "customer_name": "Beytullah Bülbül",
                "pickup_city": "Adana", "delivery_city": "Zagreb",
                "service_type": "LTL", "gross_weight_kg": 200,
                "pickup_contact_name": "Beytullah Bülbül",
                "delivery_address": "Slavonska avenija 1c, 10000 Zagreb Croatia",
            }).model_dump()
        )

    dual_role = process_controlled_outlook_inbound_mail(
        mail=_mail(
            sender="beytullah.bulbul@barsan.com",
            message_id="barsan-price-request-1",
            subject="Barsan Global Lojistik/ ADANA ZAGREB/ parsiyel yükleme",
            body=(
                "Barsan Global Lojistik Hırvatistan ofisinde size ulaşıyorum.\n"
                "Parsiyel yük için maliyet teklifi iletebilir misiniz? "
                "Yüreğir Adana - Zagreb, toplam 200 kg.\n\n"
                "Srdacan pozdrav / Kind regards/ Saygılarımla\n"
                "Beytullah Bülbül\nRegional Director\n"
                "Barsan Global Logistics d.o.o.\n"
                "Address : Slavonska avenija 1c\n10 000 Zagreb Croatia"
            ),
        ),
        shipment_parser=dual_role_customer_parser,
        supplier_parser=RecordingSupplierParser(),
        proposal_repository=dual_role_proposals,
        supplier_repository=InMemorySupplierRFQRepository(),
        operational_data_sources=None,
        master_data_repository=dual_role_masters,
        mina_job_repository=dual_role_jobs,
    )
    dual_role_job = dual_role_jobs.get(dual_role.get("job_id"))
    check(
        dual_role.get("transactional_role") == "customer_request"
        and dual_role.get("counterparty_verification_required") is True
        and dual_role.get("known_supplier_name") == "Barsan Global Logistics"
        and dual_role_job is not None
        and dual_role_job.stage == "inquiry_received"
        and dual_role_job.mina_code == "MINA2026/1"
        and dual_role_job.shipment.customer_name == "Barsan Global Logistics"
        and dual_role_job.shipment.pickup_contact_name is None
        and dual_role_job.shipment.delivery_address is None,
        "known supplier quote request uses company identity and rejects signature-only shipment contacts",
    )

    unknown_masters = InMemoryMasterDataRepository()
    unknown_jobs = InMemoryMinaJobRepository()
    unknown_proposals = InMemoryExtractionProposalRepository()
    unknown_company = process_controlled_outlook_inbound_mail(
        mail=_mail(
            sender="jane.doe@atlasfreight.example",
            message_id="unknown-company-price-request-1",
            subject="Mersin Vienna freight quote",
            body=(
                "Mersin - Vienna 2 palet için navlun teklifi rica ederiz.\n\n"
                "Kind regards / Saygılarımla\nJane Doe\nSales Manager\n"
                "Atlas Freight GmbH\nAddress: Ringstrasse 10, Vienna"
            ),
        ),
        shipment_parser=lambda _safe: ShipmentProposalSnapshot.model_validate(
            _shipment().model_copy(update={
                "customer_name": "Jane Doe", "pickup_city": "Mersin",
                "delivery_city": "Vienna", "gross_weight_kg": 500,
                "pickup_contact_name": "Jane Doe",
                "delivery_address": "Ringstrasse 10, Vienna",
            }).model_dump()
        ),
        supplier_parser=RecordingSupplierParser(),
        proposal_repository=unknown_proposals,
        supplier_repository=InMemorySupplierRFQRepository(),
        operational_data_sources=None,
        master_data_repository=unknown_masters,
        mina_job_repository=unknown_jobs,
    )
    unknown_job = unknown_jobs.get(unknown_company.get("job_id"))
    check(
        unknown_job is not None
        and unknown_job.shipment.customer_name == "Atlas Freight GmbH"
        and unknown_job.shipment.pickup_contact_name is None
        and unknown_job.shipment.delivery_address is None
        and unknown_company.get("counterparty_verification_required") is True,
        "unknown quote requester derives organization from signature without treating signature as shipment evidence",
    )

    create_customer_master(
        repository=unknown_masters, entry_id="atlas-customer",
        customer_name="Atlas Freight Customer", updated_by="Regression",
        trusted_sender_addresses=["jane.doe@atlasfreight.example"],
    )
    reverified_company = process_controlled_outlook_inbound_mail(
        mail=_mail(
            sender="jane.doe@atlasfreight.example",
            message_id="unknown-company-price-request-1",
            subject="Mersin Vienna freight quote",
            body=(
                "Mersin - Vienna 2 palet için navlun teklifi rica ederiz.\n\n"
                "Kind regards / Saygılarımla\nJane Doe\nSales Manager\n"
                "Atlas Freight GmbH\nAddress: Ringstrasse 10, Vienna"
            ),
        ),
        shipment_parser=lambda _safe: (_ for _ in ()).throw(
            AssertionError("duplicate verified intake must not re-run AI parser")
        ),
        supplier_parser=RecordingSupplierParser(),
        proposal_repository=unknown_proposals,
        supplier_repository=InMemorySupplierRFQRepository(),
        operational_data_sources=None,
        master_data_repository=unknown_masters,
        mina_job_repository=unknown_jobs,
    )
    verified_proposal = reverified_company.get("extraction_proposal")
    verified_job = unknown_jobs.get(reverified_company.get("job_id"))
    check(
        verified_proposal is not None
        and verified_proposal.trusted_customer_name == "Atlas Freight Customer"
        and verified_proposal.proposed_shipment.customer_name == "Atlas Freight Customer"
        and verified_job is not None
        and verified_job.job_id == unknown_job.job_id
        and verified_job.mina_code == unknown_job.mina_code
        and verified_job.shipment.customer_name == "Atlas Freight Customer"
        and verified_job.stage == "inquiry_received",
        "later customer verification binds the existing proposal and same MINA job without re-running AI",
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
