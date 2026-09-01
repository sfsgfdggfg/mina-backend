from __future__ import annotations

from unittest.mock import patch

from src.core.attachment_content_verification import AttachmentRetrievalResult, VerifiedAttachmentReceipt
from src.core.attachment_safe_extraction import SafeAttachmentExtractionArtifact
from src.core.attachment_safe_interpretation import interpret_extracted_attachment_mail
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.mail import InboundAttachmentMetadata
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.core.supplier_rfq import build_supplier_rfq_reference
from src.simulation.outlook_inbound_router_regressions import (
    CUSTOMER_EMAIL, SUPPLIER_EMAIL, _mail, _profiles, _shipment, _sources, _supplier_repository,
)
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail
from src.workflow.outlook_pull import _safe_result_summary

SECRET_ATTACHMENT_TEXT = "Commercial offer 2300 EUR transit 5 days contact person@example.com"


def _manifest():
    return [InboundAttachmentMetadata(name="quote.pdf", content_type="application/pdf", size_bytes=100, kind="file", is_inline=False)]


class _Retriever:
    def __init__(self): self.calls=[]
    def __call__(self, mail):
        self.calls.append(mail.message_deduplication_key)
        return AttachmentRetrievalResult(
            status="verified", reason_code="attachment_content_verified", attachment_count=1, total_size_bytes=100,
            verified_receipts=[VerifiedAttachmentReceipt(name="quote.pdf", content_type="application/pdf", size_bytes=100, sha256_hex="c"*64, content_profile="pdf")],
            extracted_artifacts=[SafeAttachmentExtractionArtifact(
                name="quote.pdf", content_profile="pdf", extraction_kind="text", text=SECRET_ATTACHMENT_TEXT,
                character_count=len(SECRET_ATTACHMENT_TEXT), table_count=0, cell_count=0,
            )], extraction_attempted=True, content_download_performed=True,
        )


class _SupplierParser:
    def __init__(self): self.calls=[]
    def parse(self, safe_text):
        self.calls.append(safe_text)
        return SupplierResponseExtraction(status="quoted", cost=2300.0, currency="EUR", transit_time="5 days")


def evaluate_outlook_attachment_route_interpretation_regressions():
    failures=[]; passes=[]
    def check(condition,label): (passes if condition else failures).append(label)

    customer_repo=InMemoryExtractionProposalRepository(); customer_calls=[]
    def customer_parser(safe_text):
        customer_calls.append(safe_text); return _shipment()
    customer_mail=_mail(sender=CUSTOMER_EMAIL,message_id="attachment-customer-p1-57",has_attachments=True,attachment_manifest=_manifest())
    with patch("src.workflow.outlook_inbound_router.load_customer_memory", return_value=_profiles()):
        customer_result=process_controlled_outlook_inbound_mail(
            mail=customer_mail, shipment_parser=customer_parser, supplier_parser=_SupplierParser(),
            proposal_repository=customer_repo, supplier_repository=_supplier_repository(), operational_data_sources=_sources(),
            attachment_retriever=_Retriever(), attachment_interpreter=interpret_extracted_attachment_mail,
        )
    interpretation=customer_result.get("attachment_interpretation")
    check(
        customer_result.get("reason_code")=="outlook_attachment_content_interpreted_pending_review"
        and customer_result.get("attachment_interpretation_status")=="interpreted"
        and customer_result.get("attachment_interpretation_parser_called") is True
        and len(customer_calls)==1 and len(customer_repo.list_all())==0
        and interpretation is not None and interpretation.customer_proposal is not None,
        "customer attachment interpretation remains non-durable pending review",
    )

    supplier_repo=_supplier_repository(); supplier_parser=_SupplierParser(); retriever=_Retriever()
    subject="Re: ["+build_supplier_rfq_reference("rfq-router-1")+"] RFQ"
    supplier_mail=_mail(sender=SUPPLIER_EMAIL,message_id="attachment-supplier-p1-57",subject=subject,has_attachments=True,attachment_manifest=_manifest())
    with patch("src.workflow.outlook_inbound_router.load_customer_memory", return_value=_profiles()):
        supplier_result=process_controlled_outlook_inbound_mail(
            mail=supplier_mail, shipment_parser=customer_parser, supplier_parser=supplier_parser,
            proposal_repository=InMemoryExtractionProposalRepository(), supplier_repository=supplier_repo,
            operational_data_sources=_sources(), attachment_retriever=retriever,
            attachment_interpreter=interpret_extracted_attachment_mail,
        )
    supplier_interpretation=supplier_result.get("attachment_interpretation")
    draft=supplier_repo.get_draft("rfq-router-1")
    check(
        supplier_result.get("reason_code")=="outlook_attachment_content_interpreted_pending_review"
        and supplier_result.get("inbound_route")=="supplier" and len(supplier_parser.calls)==1
        and draft is not None and draft.status=="awaiting_response"
        and supplier_repo.list_responses("rfq-router-1")==[]
        and supplier_interpretation is not None and supplier_interpretation.supplier_extraction is not None,
        "supplier attachment interpretation cannot mutate RFQ lifecycle or response repository",
    )

    summary=_safe_result_summary(supplier_mail,supplier_result)
    check(
        summary.get("attachment_interpretation_status")=="interpreted"
        and summary.get("attachment_interpretation_parser_called") is True
        and SECRET_ATTACHMENT_TEXT not in repr(summary)
        and "2300" not in repr(summary)
        and "attachment_interpretation" not in summary,
        "operator summary exposes interpretation state without interpreted payload",
    )

    outsider_parser=_SupplierParser(); outsider_retriever=_Retriever()
    with patch("src.workflow.outlook_inbound_router.load_customer_memory", return_value=_profiles()):
        outsider=process_controlled_outlook_inbound_mail(
            mail=_mail(sender="outsider@example.invalid",message_id="attachment-outsider-p1-57",has_attachments=True,attachment_manifest=_manifest()),
            shipment_parser=customer_parser, supplier_parser=outsider_parser,
            proposal_repository=InMemoryExtractionProposalRepository(), supplier_repository=_supplier_repository(),
            operational_data_sources=_sources(), attachment_retriever=outsider_retriever,
            attachment_interpreter=interpret_extracted_attachment_mail,
        )
    check(
        outsider.get("reason_code")=="sender_not_in_verified_inbound_scope"
        and outsider_retriever.calls==[] and outsider_parser.calls==[],
        "untrusted attachment sender cannot reach retrieval or interpretation",
    )
    return {"name":"Trusted-route attachment interpretation gate","passed":not failures,"failures":failures,"passed_checks":passes}


def main():
    result=evaluate_outlook_attachment_route_interpretation_regressions()
    for label in result["passed_checks"]: print("PASS",label)
    for label in result["failures"]: print("FAIL",label)
    print("\nAttachment route interpretation regressions:","PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
