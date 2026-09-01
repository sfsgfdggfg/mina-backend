from __future__ import annotations

from unittest.mock import patch
from fastapi import HTTPException

from src import api
from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.attachment_interpretation_review_service import (
    build_attachment_review_preview,
    create_attachment_interpretation_review,
)
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.simulation.attachment_interpretation_review_regressions import (
    _customer_interpretation, _retrieval, _supplier_interpretation,
)
from src.simulation.outlook_inbound_router_regressions import (
    CUSTOMER_EMAIL, SUPPLIER_EMAIL, _mail, _supplier_repository,
)


def evaluate_attachment_review_field_ux_regressions():
    failures=[]; passes=[]
    def check(condition,label): (passes if condition else failures).append(label)

    reviews=InMemoryAttachmentInterpretationReviewRepository()
    suppliers=_supplier_repository()
    proposals=InMemoryExtractionProposalRepository()
    customer=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="p1-59-customer",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("1"),interpretation=_customer_interpretation(),
        repository=reviews,supplier_repository=suppliers,trusted_customer_name="Pilot Customer",
    )
    baseline_count=len(proposals.list_all())
    preview=build_attachment_review_preview(customer,{"is_high_value":True})
    high_value=next(item for item in preview["fields"] if item["field"]=="is_high_value")
    customer_name=next(item for item in preview["fields"] if item["field"]=="customer_name")
    check(
        preview["apply_ready"] is True and len(preview["preview_token"])==64
        and high_value["category"]=="safety" and high_value["changed"] is True
        and preview["critical_attention_fields"]==["is_high_value"]
        and "critical_field_changed_by_operator" in high_value["attention_reasons"]
        and customer_name["editable"] is False
        and len(proposals.list_all())==baseline_count and reviews.get(customer.review_id).status=="pending",
        "customer field preview is read-only and highlights safety/locked fields",
    )
    locked=build_attachment_review_preview(customer,{"customer_name":"Spoofed Customer"})
    check(
        locked["apply_ready"] is False
        and "corrections_invalid_or_not_applyable" in locked["blockers"],
        "locked trusted customer identity fails closed in preview",
    )

    supplier_reviews=InMemoryAttachmentInterpretationReviewRepository()
    supplier_repo=_supplier_repository()
    supplier=create_attachment_interpretation_review(
        mail=_mail(sender=SUPPLIER_EMAIL,message_id="p1-59-supplier",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("2"),interpretation=_supplier_interpretation(),
        repository=supplier_reviews,supplier_repository=supplier_repo,rfq_id="rfq-router-1",
        correlation_method="supplier_identity",
    )
    rfq_before=supplier_repo.get_draft("rfq-router-1")
    sp=build_attachment_review_preview(supplier,{"cost":2300.0})
    cost=next(item for item in sp["fields"] if item["field"]=="cost")
    check(
        sp["apply_ready"] is True and cost["category"]=="commercial_critical"
        and cost["changed"] is True and "critical_field_changed_by_operator" in cost["attention_reasons"]
        and supplier_repo.get_draft("rfq-router-1")==rfq_before
        and not supplier_repo.list_responses("rfq-router-1"),
        "supplier preview highlights critical commercial changes without lifecycle mutation",
    )

    class _State: pilot_operator="P1-59 Operator"
    class _Request: state=_State()
    api_reviews=InMemoryAttachmentInterpretationReviewRepository()
    api_review=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="p1-59-api",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("3"),interpretation=_customer_interpretation(),
        repository=api_reviews,supplier_repository=_supplier_repository(),trusted_customer_name="Pilot Customer",
    )
    api_proposals=InMemoryExtractionProposalRepository(); api_suppliers=_supplier_repository()
    with patch.object(api,"attachment_review_repository",api_reviews), patch.object(
        api,"extraction_proposal_repository",api_proposals
    ), patch.object(api,"supplier_rfq_repository",api_suppliers):
        detail=api.get_attachment_review(api_review.review_id)
        api_preview=api.preview_attachment_review_endpoint(
            api_review.review_id,api.PreviewAttachmentReviewRequest(corrections={"is_high_value":False})
        )
        mismatch_blocked=False
        try:
            api.apply_attachment_review_endpoint(
                api_review.review_id,api.ApplyAttachmentReviewRequest(
                    corrections={"is_high_value":False},preview_token="0"*64
                ),_Request()
            )
        except HTTPException as exc:
            mismatch_blocked=exc.status_code==409
        still_pending=api_reviews.get(api_review.review_id).status=="pending" and not api_proposals.list_all()
        applied=api.apply_attachment_review_endpoint(
            api_review.review_id,api.ApplyAttachmentReviewRequest(
                corrections={"is_high_value":False},preview_token=api_preview["preview_token"]
            ),_Request()
        )
    check(
        detail["field_review"]["apply_ready"] is True
        and mismatch_blocked and still_pending and applied["status"]=="applied"
        and len(api_proposals.list_all())==1,
        "API requires the exact field preview token before attachment review apply",
    )
    check(
        "source_fingerprint" not in repr(detail) and "sha256" not in repr(detail)
        and "source_fingerprint" not in repr(api_preview) and "sha256" not in repr(api_preview),
        "field review UX exposes no attachment or source fingerprints",
    )
    return {"name":"Attachment review field-level UX","passed":not failures,"failures":failures,"passed_checks":passes}


def main():
    result=evaluate_attachment_review_field_ux_regressions()
    for x in result["passed_checks"]: print("PASS",x)
    for x in result["failures"]: print("FAIL",x)
    print("\nAttachment review field UX regressions:","PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
