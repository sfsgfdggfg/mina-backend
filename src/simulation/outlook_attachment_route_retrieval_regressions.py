from __future__ import annotations

from unittest.mock import patch

from src.core.attachment_content_verification import (
    AttachmentRetrievalResult,
    VerifiedAttachmentReceipt,
)
from src.core.mail import InboundAttachmentMetadata
from src.core.supplier_rfq import build_supplier_rfq_reference
from src.simulation.outlook_inbound_router_regressions import (
    CUSTOMER_EMAIL,
    SUPPLIER_EMAIL,
    RecordingSupplierParser,
    _mail,
    _profiles,
    _shipment,
    _sources,
    _supplier_repository,
)
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail


def _manifest(name="quote.pdf", mime="application/pdf"):
    return [
        InboundAttachmentMetadata(
            name=name,
            content_type=mime,
            size_bytes=100,
            kind="file",
            is_inline=False,
        )
    ]


class _Retriever:
    def __init__(self):
        self.calls = []

    def __call__(self, mail):
        self.calls.append(mail.message_deduplication_key)
        return AttachmentRetrievalResult(
            status="verified",
            reason_code="attachment_content_verified",
            attachment_count=1,
            total_size_bytes=100,
            verified_receipts=[
                VerifiedAttachmentReceipt(
                    name="quote.pdf",
                    content_type="application/pdf",
                    size_bytes=100,
                    sha256_hex="a" * 64,
                    content_profile="pdf",
                )
            ],
            content_download_performed=True,
        )


def evaluate_outlook_attachment_route_retrieval_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    def customer_parser(_):
        raise AssertionError("customer parser must not run for attachments")

    supplier_parser = RecordingSupplierParser()
    retriever = _Retriever()
    customer_mail = _mail(
        sender=CUSTOMER_EMAIL,
        message_id="trusted-customer-attachment",
        has_attachments=True,
        attachment_manifest=_manifest(),
    )
    with patch(
        "src.workflow.outlook_inbound_router.load_customer_memory",
        return_value=_profiles(),
    ):
        customer_result = process_controlled_outlook_inbound_mail(
            mail=customer_mail,
            shipment_parser=customer_parser,
            supplier_parser=supplier_parser,
            proposal_repository=InMemoryExtractionProposalRepository(),
            supplier_repository=_supplier_repository(),
            operational_data_sources=_sources(),
            attachment_retriever=retriever,
        )
    check(
        customer_result.get("inbound_route") == "customer"
        and customer_result.get("attachment_retrieval_status") == "verified"
        and customer_result.get("reason_code") == "outlook_attachment_content_verified_not_parsed"
        and len(retriever.calls) == 1
        and not supplier_parser.calls,
        "trusted customer route retrieves but never parses attachment",
    )

    untrusted_retriever = _Retriever()
    with patch(
        "src.workflow.outlook_inbound_router.load_customer_memory",
        return_value=_profiles(),
    ):
        untrusted = process_controlled_outlook_inbound_mail(
            mail=_mail(
                sender="outsider@example.invalid",
                message_id="untrusted-attachment",
                has_attachments=True,
                attachment_manifest=_manifest(),
            ),
            shipment_parser=customer_parser,
            supplier_parser=RecordingSupplierParser(),
            proposal_repository=InMemoryExtractionProposalRepository(),
            supplier_repository=_supplier_repository(),
            operational_data_sources=_sources(),
            attachment_retriever=untrusted_retriever,
        )
    check(
        untrusted.get("reason_code") == "sender_not_in_verified_inbound_scope"
        and not untrusted_retriever.calls,
        "untrusted attachment sender cannot trigger retrieval",
    )

    supplier_retriever = _Retriever()
    supplier_subject = (
        "Re: [" + build_supplier_rfq_reference("rfq-router-1") + "] RFQ"
    )
    supplier_parser2 = RecordingSupplierParser()
    with patch(
        "src.workflow.outlook_inbound_router.load_customer_memory",
        return_value=_profiles(),
    ):
        supplier_result = process_controlled_outlook_inbound_mail(
            mail=_mail(
                sender=SUPPLIER_EMAIL,
                message_id="trusted-supplier-attachment",
                subject=supplier_subject,
                has_attachments=True,
                attachment_manifest=_manifest(),
            ),
            shipment_parser=customer_parser,
            supplier_parser=supplier_parser2,
            proposal_repository=InMemoryExtractionProposalRepository(),
            supplier_repository=_supplier_repository(),
            operational_data_sources=_sources(),
            attachment_retriever=supplier_retriever,
        )
    check(
        supplier_result.get("inbound_route") == "supplier"
        and supplier_result.get("rfq_id") == "rfq-router-1"
        and supplier_result.get("attachment_retrieval_status") == "verified"
        and len(supplier_retriever.calls) == 1
        and not supplier_parser2.calls,
        "trusted supplier correlation retrieves but never parses attachment",
    )

    unsupported_retriever = _Retriever()
    with patch(
        "src.workflow.outlook_inbound_router.load_customer_memory",
        return_value=_profiles(),
    ):
        unsupported = process_controlled_outlook_inbound_mail(
            mail=_mail(
                sender=CUSTOMER_EMAIL,
                message_id="unsupported-attachment",
                has_attachments=True,
                attachment_manifest=_manifest(
                    name="notes.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            ),
            shipment_parser=customer_parser,
            supplier_parser=RecordingSupplierParser(),
            proposal_repository=InMemoryExtractionProposalRepository(),
            supplier_repository=_supplier_repository(),
            operational_data_sources=_sources(),
            attachment_retriever=unsupported_retriever,
        )
    check(
        unsupported.get("attachment_intake_status") == "manual_review"
        and not unsupported_retriever.calls,
        "metadata manual-review attachment never reaches retrieval boundary",
    )

    overlap_retriever = _Retriever()
    overlap_repo = _supplier_repository(
        recipient_email=CUSTOMER_EMAIL,
        rfq_ids=("rfq-overlap-attachment",),
    )
    overlap_subject = (
        "Re: [" + build_supplier_rfq_reference("rfq-overlap-attachment") + "]"
    )
    with patch(
        "src.workflow.outlook_inbound_router.load_customer_memory",
        return_value=_profiles(),
    ):
        overlap = process_controlled_outlook_inbound_mail(
            mail=_mail(
                sender=CUSTOMER_EMAIL,
                message_id="overlap-attachment",
                subject=overlap_subject,
                has_attachments=True,
                attachment_manifest=_manifest(),
            ),
            shipment_parser=customer_parser,
            supplier_parser=RecordingSupplierParser(),
            proposal_repository=InMemoryExtractionProposalRepository(),
            supplier_repository=overlap_repo,
            operational_data_sources=_sources(),
            attachment_retriever=overlap_retriever,
        )
    check(
        overlap.get("reason_code") == "sender_matches_customer_and_supplier"
        and not overlap_retriever.calls,
        "ambiguous customer supplier identity blocks retrieval",
    )

    return {
        "name": "Trusted-route attachment retrieval gate",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_outlook_attachment_route_retrieval_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAttachment route retrieval regressions: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
