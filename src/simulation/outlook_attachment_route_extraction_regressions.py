from __future__ import annotations

from unittest.mock import patch

from src.core.attachment_content_verification import (
    AttachmentRetrievalResult,
    VerifiedAttachmentReceipt,
)
from src.core.attachment_safe_extraction import SafeAttachmentExtractionArtifact
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundAttachmentMetadata
from src.simulation.outlook_inbound_router_regressions import (
    CUSTOMER_EMAIL,
    RecordingSupplierParser,
    _mail,
    _profiles,
    _sources,
    _supplier_repository,
)
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail
from src.workflow.outlook_pull import _safe_result_summary


SECRET_EXTRACTED_TEXT = "PRIVATE ATTACHMENT CONTENT MUST NOT APPEAR IN OPERATOR SUMMARY"


def _manifest():
    return [
        InboundAttachmentMetadata(
            name="quote.pdf",
            content_type="application/pdf",
            size_bytes=100,
            kind="file",
            is_inline=False,
        )
    ]


class _ExtractingRetriever:
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
                    sha256_hex="b" * 64,
                    content_profile="pdf",
                )
            ],
            extracted_artifacts=[
                SafeAttachmentExtractionArtifact(
                    name="quote.pdf",
                    content_profile="pdf",
                    extraction_kind="text",
                    text=SECRET_EXTRACTED_TEXT,
                    character_count=len(SECRET_EXTRACTED_TEXT),
                    table_count=0,
                    cell_count=0,
                )
            ],
            extraction_attempted=True,
            content_download_performed=True,
        )


def evaluate_outlook_attachment_route_extraction_regressions():
    failures = []
    passes = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    def customer_parser(_):
        raise AssertionError("customer AI parser must not run for extracted attachment")

    supplier_parser = RecordingSupplierParser()
    retriever = _ExtractingRetriever()
    mail = _mail(
        sender=CUSTOMER_EMAIL,
        message_id="trusted-customer-extracted-attachment",
        has_attachments=True,
        attachment_manifest=_manifest(),
    )
    with patch(
        "src.workflow.outlook_inbound_router.load_customer_memory",
        return_value=_profiles(),
    ):
        result = process_controlled_outlook_inbound_mail(
            mail=mail,
            shipment_parser=customer_parser,
            supplier_parser=supplier_parser,
            proposal_repository=InMemoryExtractionProposalRepository(),
            supplier_repository=_supplier_repository(),
            operational_data_sources=_sources(),
            attachment_retriever=retriever,
        )

    check(
        result.get("inbound_route") == "customer"
        and result.get("reason_code") == "outlook_attachment_content_extracted_not_interpreted"
        and result.get("attachment_extraction_status") == "extracted"
        and result.get("attachment_extracted_count") == 1
        and result.get("attachment_extracted_character_count") == len(SECRET_EXTRACTED_TEXT)
        and result.get("attachment_extracted_table_count") == 0
        and len(retriever.calls) == 1
        and not supplier_parser.calls,
        "trusted route extracts attachment but does not invoke AI",
    )

    artifacts = result.get("attachment_extraction_artifacts")
    check(
        artifacts
        and artifacts[0].text == SECRET_EXTRACTED_TEXT,
        "extracted artifact remains available only inside routing result",
    )

    safe_summary = _safe_result_summary(mail, result)
    check(
        safe_summary.get("attachment_extraction_status") == "extracted"
        and safe_summary.get("attachment_extracted_count") == 1
        and safe_summary.get("attachment_extracted_character_count") == len(SECRET_EXTRACTED_TEXT)
        and SECRET_EXTRACTED_TEXT not in repr(safe_summary)
        and SECRET_EXTRACTED_TEXT not in repr(result)
        and "attachment_extraction_artifacts" not in safe_summary,
        "operator summary exposes extraction counts but not extracted content",
    )

    return {
        "name": "Trusted-route attachment extraction gate",
        "passed": not failures,
        "failures": failures,
        "passed_checks": passes,
    }


def main():
    result = evaluate_outlook_attachment_route_extraction_regressions()
    for label in result["passed_checks"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAttachment route extraction regressions: " + ("PASS" if result["passed"] else "FAIL"))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
