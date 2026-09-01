from __future__ import annotations

from unittest.mock import patch

from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.attachment_safe_interpretation import AttachmentInterpretationResult
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.simulation.outlook_attachment_route_extraction_regressions import _ExtractingRetriever, _manifest
from src.simulation.outlook_inbound_router_regressions import (
    CUSTOMER_EMAIL, SUPPLIER_EMAIL, _mail, _profiles, _shipment, _sources, _supplier_repository,
)
from src.workflow.outlook_inbound_router import process_controlled_outlook_inbound_mail
from src.workflow.outlook_pull import _safe_result_summary


def evaluate_outlook_attachment_review_gate_regressions():
    failures=[]; passes=[]
    def check(condition,label): (passes if condition else failures).append(label)

    reviews=InMemoryAttachmentInterpretationReviewRepository()
    proposals=InMemoryExtractionProposalRepository()
    suppliers=_supplier_repository()
    retriever=_ExtractingRetriever()
    customer_calls=[]
    def customer_parser(value):
        customer_calls.append(value); return _shipment()
    class SupplierParser:
        def __init__(self): self.calls=[]
        def parse(self,value):
            self.calls.append(value)
            return SupplierResponseExtraction(status="quoted",cost=2200.0,currency="EUR")
    supplier_parser=SupplierParser()

    def interpreter(**kwargs):
        if kwargs["route"]=="customer":
            proposal=kwargs["shipment_parser"]("safe")
            return AttachmentInterpretationResult(
                status="interpreted",reason_code="attachment_customer_interpretation_proposed",
                route="customer",parser_called=True,source_attachment_count=1,
                source_character_count=55,source_table_count=0,privacy_transform_version="p1.28-v3",
                source_profiles=["pdf"],customer_proposal=proposal,
            )
        extraction=kwargs["supplier_parser"].parse("safe")
        return AttachmentInterpretationResult(
            status="interpreted",reason_code="attachment_supplier_interpretation_proposed",
            route="supplier",parser_called=True,source_attachment_count=1,
            source_character_count=55,source_table_count=0,privacy_transform_version="p1.28-v3",
            source_profiles=["pdf"],supplier_extraction=extraction,
        )

    customer_mail=_mail(
        sender=CUSTOMER_EMAIL,message_id="review-gate-customer",has_attachments=True,attachment_manifest=_manifest()
    )
    with patch("src.workflow.outlook_inbound_router.load_customer_memory",return_value=_profiles()):
        customer_result=process_controlled_outlook_inbound_mail(
            mail=customer_mail,shipment_parser=customer_parser,supplier_parser=supplier_parser,
            proposal_repository=proposals,supplier_repository=suppliers,operational_data_sources=_sources(),
            attachment_retriever=retriever,attachment_interpreter=interpreter,
            attachment_review_repository=reviews,
        )
    customer_review=reviews.get(customer_result.get("attachment_review_id"))
    summary=_safe_result_summary(customer_mail,customer_result)
    check(
        customer_result.get("reason_code")=="outlook_attachment_interpretation_review_required"
        and customer_result.get("attachment_review_status")=="pending"
        and customer_review is not None and customer_review.route=="customer"
        and not proposals.list_all() and not suppliers.list_responses()
        and summary.get("attachment_review_id")==customer_review.review_id
        and "customer_candidate" not in repr(summary) and "sha256" not in repr(summary),
        "customer interpretation creates pending review without downstream apply or payload leak",
    )
    with patch("src.workflow.outlook_inbound_router.load_customer_memory",return_value=_profiles()):
        duplicate=process_controlled_outlook_inbound_mail(
            mail=customer_mail,shipment_parser=customer_parser,supplier_parser=supplier_parser,
            proposal_repository=proposals,supplier_repository=suppliers,operational_data_sources=_sources(),
            attachment_retriever=retriever,attachment_interpreter=interpreter,attachment_review_repository=reviews,
        )
    check(
        duplicate.get("attachment_review_id")==customer_review.review_id and len(reviews.list_all())==1,
        "same verified interpretation fingerprint reuses the durable review case",
    )

    supplier_reviews=InMemoryAttachmentInterpretationReviewRepository()
    supplier_repo=_supplier_repository()
    supplier_mail=_mail(
        sender=SUPPLIER_EMAIL,message_id="review-gate-supplier",has_attachments=True,attachment_manifest=_manifest()
    )
    with patch("src.workflow.outlook_inbound_router.load_customer_memory",return_value=_profiles()):
        supplier_result=process_controlled_outlook_inbound_mail(
            mail=supplier_mail,shipment_parser=customer_parser,supplier_parser=supplier_parser,
            proposal_repository=InMemoryExtractionProposalRepository(),supplier_repository=supplier_repo,
            operational_data_sources=_sources(),attachment_retriever=_ExtractingRetriever(),
            attachment_interpreter=interpreter,attachment_review_repository=supplier_reviews,
        )
    supplier_review=supplier_reviews.get(supplier_result.get("attachment_review_id"))
    check(
        supplier_review is not None and supplier_review.route=="supplier"
        and supplier_review.rfq_id=="rfq-router-1"
        and supplier_repo.get_draft("rfq-router-1").status=="awaiting_response"
        and not supplier_repo.list_responses("rfq-router-1"),
        "supplier interpretation review freezes RFQ provenance without lifecycle mutation",
    )
    return {"name":"Outlook attachment review gate","passed":not failures,"failures":failures,"passed_checks":passes}


def main():
    result=evaluate_outlook_attachment_review_gate_regressions()
    for x in result["passed_checks"]: print("PASS",x)
    for x in result["failures"]: print("FAIL",x)
    print("\nOutlook attachment review gate regressions:","PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
