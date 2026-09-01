from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from src.core.attachment_content_verification import (
    AttachmentRetrievalResult, VerifiedAttachmentReceipt,
)
from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.attachment_interpretation_review_service import (
    AttachmentReviewConflictError,
    AttachmentReviewTransitionError,
    apply_attachment_interpretation_review,
    attachment_review_public_payload,
    create_attachment_interpretation_review,
    reject_attachment_interpretation_review,
)
from src.core.attachment_safe_interpretation import AttachmentInterpretationResult
from src.core.extraction_confirmation_repository import InMemoryExtractionProposalRepository
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteAttachmentInterpretationReviewRepository
from src.core.supplier_response_ingestion import SupplierResponseExtraction
from src.simulation.outlook_inbound_router_regressions import (
    CUSTOMER_EMAIL, SUPPLIER_EMAIL, _mail, _shipment, _supplier_repository,
)


def _retrieval(seed: str = "a"):
    return AttachmentRetrievalResult(
        status="verified",
        reason_code="attachment_content_verified",
        attachment_count=1,
        total_size_bytes=100,
        verified_receipts=[VerifiedAttachmentReceipt(
            name="controlled.pdf", content_type="application/pdf", size_bytes=100,
            sha256_hex=seed * 64, content_profile="pdf",
        )],
        content_download_performed=True,
    )


def _customer_interpretation():
    return AttachmentInterpretationResult(
        status="interpreted", reason_code="attachment_customer_interpretation_proposed",
        route="customer", parser_called=True, source_attachment_count=1,
        source_character_count=250, source_table_count=0,
        privacy_transform_version="p1.28-v3", source_profiles=["pdf"],
        customer_proposal=_shipment(),
    )


def _supplier_interpretation(cost=2200.0):
    return AttachmentInterpretationResult(
        status="interpreted", reason_code="attachment_supplier_interpretation_proposed",
        route="supplier", parser_called=True, source_attachment_count=1,
        source_character_count=120, source_table_count=0,
        privacy_transform_version="p1.28-v3", source_profiles=["pdf"],
        supplier_extraction=SupplierResponseExtraction(
            status="quoted", cost=cost, currency="EUR", transit_time="4 days"
        ),
    )


def evaluate_attachment_interpretation_review_regressions():
    failures=[]; passes=[]
    def check(condition,label): (passes if condition else failures).append(label)

    reviews=InMemoryAttachmentInterpretationReviewRepository()
    proposals=InMemoryExtractionProposalRepository()
    suppliers=_supplier_repository()
    customer_mail=_mail(
        sender=CUSTOMER_EMAIL, message_id="review-customer-1",
        has_attachments=True, attachment_manifest=[],
    )
    # Review service consumes verified evidence and does not require the manifest itself.
    customer_review=create_attachment_interpretation_review(
        mail=customer_mail, retrieval=_retrieval(), interpretation=_customer_interpretation(),
        repository=reviews, supplier_repository=suppliers, trusted_customer_name="Pilot Customer",
    )
    public=attachment_review_public_payload(customer_review, include_candidate=True)
    check(
        customer_review.status=="pending" and public.get("candidate") is not None
        and "sha256" not in repr(public) and "source_fingerprint" not in repr(public),
        "customer interpretation becomes a durable review without exposing fingerprints",
    )
    old_privacy=_customer_interpretation().model_copy(
        update={"privacy_transform_version":"obsolete-transform"}
    )
    privacy_blocked=False
    try:
        create_attachment_interpretation_review(
            mail=_mail(sender=CUSTOMER_EMAIL,message_id="review-old-privacy",has_attachments=True,attachment_manifest=[]),
            retrieval=_retrieval("9"),interpretation=old_privacy,repository=reviews,
            supplier_repository=suppliers,trusted_customer_name="Pilot Customer",
        )
    except AttachmentReviewConflictError:
        privacy_blocked=True
    check(privacy_blocked,"non-approved privacy transform version cannot create an attachment review")

    applied=apply_attachment_interpretation_review(
        repository=reviews, review_id=customer_review.review_id,
        operator_identity="Pilot Operator", corrections={"is_high_value": False},
        proposal_repository=proposals, supplier_repository=suppliers,
    )
    proposal=proposals.get(applied.applied_proposal_id)
    check(
        applied.status=="applied" and proposal is not None
        and proposal.extraction_status=="proposed" and proposal.confirmed_shipment is None
        and proposal.source_attachment_review_id==customer_review.review_id
        and proposal.proposed_shipment.customer_name=="Pilot Customer"
        and proposal.proposed_shipment.is_high_value is False,
        "customer review apply creates only a traceable unconfirmed extraction proposal",
    )

    second_apply_blocked=False
    try:
        apply_attachment_interpretation_review(
            repository=reviews,review_id=customer_review.review_id,operator_identity="Pilot Operator",
            corrections={},proposal_repository=proposals,supplier_repository=suppliers,
        )
    except AttachmentReviewTransitionError:
        second_apply_blocked=True
    check(second_apply_blocked,"applied attachment review is terminal and cannot be applied twice")

    reject_reviews=InMemoryAttachmentInterpretationReviewRepository()
    reject_proposals=InMemoryExtractionProposalRepository()
    reject_review=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="review-reject-1",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("b"), interpretation=_customer_interpretation(),
        repository=reject_reviews, supplier_repository=suppliers, trusted_customer_name="Pilot Customer",
    )
    rejected=reject_attachment_interpretation_review(
        repository=reject_reviews, review_id=reject_review.review_id,
        operator_identity="Pilot Operator", rejection_reason="Attachment fields need manual verification.",
    )
    check(
        rejected.status=="rejected" and not reject_proposals.list_all(),
        "rejected customer review leaves downstream proposal state untouched",
    )

    rejected_terminal=False
    try:
        reject_attachment_interpretation_review(
            repository=reject_reviews,review_id=reject_review.review_id,
            operator_identity="Pilot Operator",rejection_reason="Again",
        )
    except AttachmentReviewTransitionError:
        rejected_terminal=True
    check(rejected_terminal,"rejected attachment review is terminal")

    supplier_repo=_supplier_repository()
    supplier_reviews=InMemoryAttachmentInterpretationReviewRepository()
    supplier_mail=_mail(sender=SUPPLIER_EMAIL,message_id="review-supplier-1",has_attachments=True,attachment_manifest=[])
    supplier_review=create_attachment_interpretation_review(
        mail=supplier_mail, retrieval=_retrieval("c"), interpretation=_supplier_interpretation(),
        repository=supplier_reviews, supplier_repository=supplier_repo, rfq_id="rfq-router-1",
        correlation_method="supplier_identity",
    )
    check(
        supplier_review.status=="pending"
        and supplier_repo.get_draft("rfq-router-1").status=="awaiting_response"
        and not supplier_repo.list_responses("rfq-router-1"),
        "supplier review creation has no RFQ lifecycle authority",
    )
    supplier_applied=apply_attachment_interpretation_review(
        repository=supplier_reviews, review_id=supplier_review.review_id,
        operator_identity="Pilot Operator", corrections={"cost": 2250.0},
        proposal_repository=InMemoryExtractionProposalRepository(), supplier_repository=supplier_repo,
    )
    responses=supplier_repo.list_responses("rfq-router-1")
    evidence=supplier_repo.get_ingested_message_evidence(supplier_review.source_message_key)
    check(
        supplier_applied.status=="applied"
        and supplier_repo.get_draft("rfq-router-1").status=="responded"
        and len(responses)==1 and responses[0].cost==2250.0
        and responses[0].recorded_by=="Pilot Operator"
        and responses[0].source_attachment_review_id==supplier_review.review_id
        and evidence is not None and evidence.get("attachment_review_id")==supplier_review.review_id
        and evidence.get("attachment_source_sha256")==supplier_review.source_fingerprint_sha256,
        "supplier review apply atomically creates traceable response and advances RFQ",
    )

    stale_repo=_supplier_repository()
    stale_reviews=InMemoryAttachmentInterpretationReviewRepository()
    stale=create_attachment_interpretation_review(
        mail=_mail(sender=SUPPLIER_EMAIL,message_id="review-stale-1",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("d"), interpretation=_supplier_interpretation(),
        repository=stale_reviews, supplier_repository=stale_repo, rfq_id="rfq-router-1",
        correlation_method="supplier_identity",
    )
    draft=stale_repo.get_draft("rfq-router-1")
    stale_repo.save_drafts([draft.model_copy(update={"subject": draft.subject + " updated"})])
    blocked=False
    try:
        apply_attachment_interpretation_review(
            repository=stale_reviews, review_id=stale.review_id,
            operator_identity="Pilot Operator", corrections={},
            proposal_repository=InMemoryExtractionProposalRepository(), supplier_repository=stale_repo,
        )
    except AttachmentReviewConflictError:
        blocked=True
    check(
        blocked and stale_reviews.get(stale.review_id).status=="pending"
        and not stale_repo.list_responses("rfq-router-1"),
        "stale Supplier RFQ snapshot blocks review apply without response mutation",
    )

    with TemporaryDirectory() as temp_dir:
        store=SQLitePilotStore(Path(temp_dir)/"review.sqlite3",retention_days=30)
        sqlite_reviews=SQLiteAttachmentInterpretationReviewRepository(store)
        durable=create_attachment_interpretation_review(
            mail=_mail(sender=CUSTOMER_EMAIL,message_id="review-sqlite-1",has_attachments=True,attachment_manifest=[]),
            retrieval=_retrieval("e"),interpretation=_customer_interpretation(),
            repository=sqlite_reviews,supplier_repository=_supplier_repository(),trusted_customer_name="Pilot Customer",
        )
        reloaded=SQLiteAttachmentInterpretationReviewRepository(store).get(durable.review_id)
        check(
            reloaded is not None and reloaded.source_fingerprint_sha256==durable.source_fingerprint_sha256
            and reloaded.attachment_evidence[0].sha256_hex=="e"*64
            and reloaded.customer_candidate is not None,
            "attachment review including hidden provenance survives SQLite round trip",
        )

    # API exposes candidate for detail review but never source/file hashes.
    from src import api
    api_reviews=InMemoryAttachmentInterpretationReviewRepository()
    api_proposals=InMemoryExtractionProposalRepository()
    api_suppliers=_supplier_repository()
    api_review=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="review-api-1",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("f"),interpretation=_customer_interpretation(),
        repository=api_reviews,supplier_repository=api_suppliers,trusted_customer_name="Pilot Customer",
    )
    class _State: pilot_operator="Authenticated Review Operator"
    class _Request: state=_State()
    with patch.object(api,"attachment_review_repository",api_reviews), patch.object(
        api,"extraction_proposal_repository",api_proposals
    ), patch.object(api,"supplier_rfq_repository",api_suppliers):
        listed=api.list_attachment_reviews()
        detail=api.get_attachment_review(api_review.review_id)
        applied_api=api.apply_attachment_review_endpoint(
            api_review.review_id,api.ApplyAttachmentReviewRequest(corrections={"is_high_value":False}),_Request()
        )
    check(
        listed["reviews"][0].get("candidate") is None
        and "subject" not in listed["reviews"][0]
        and "operator_corrections" not in listed["reviews"][0]
        and "rejection_reason" not in listed["reviews"][0]
        and detail.get("candidate") is not None
        and "sha256" not in repr(listed) and "sha256" not in repr(detail)
        and applied_api.get("status")=="applied"
        and applied_api.get("reviewed_by")=="Authenticated Review Operator"
        and api_proposals.list_all()[0].source_attachment_review_id==api_review.review_id,
        "authenticated API review list/detail/apply exposes candidate safely and applies traceably",
    )

    return {"name":"Attachment interpretation review lifecycle","passed":not failures,"failures":failures,"passed_checks":passes}


def main():
    result=evaluate_attachment_interpretation_review_regressions()
    for x in result["passed_checks"]: print("PASS",x)
    for x in result["failures"]: print("FAIL",x)
    print("\nAttachment interpretation review regressions:", "PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
