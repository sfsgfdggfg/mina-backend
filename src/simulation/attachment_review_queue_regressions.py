from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src import api
from src.core.attachment_interpretation_review_repository import (
    InMemoryAttachmentInterpretationReviewRepository,
)
from src.core.attachment_interpretation_review_service import (
    create_attachment_interpretation_review,
    reject_attachment_interpretation_review,
)
from src.core.attachment_review_queue import build_attachment_review_queue
from src.simulation.attachment_interpretation_review_regressions import (
    _customer_interpretation,
    _retrieval,
    _supplier_interpretation,
)
from src.simulation.outlook_inbound_router_regressions import (
    CUSTOMER_EMAIL,
    SUPPLIER_EMAIL,
    _mail,
    _supplier_repository,
)


def _customer_interpretation_with(**updates):
    base = _customer_interpretation()
    assert base.customer_proposal is not None
    return base.model_copy(
        update={"customer_proposal": base.customer_proposal.model_copy(update=updates)}
    )


def evaluate_attachment_review_queue_regressions():
    failures=[]; passes=[]
    def check(condition,label): (passes if condition else failures).append(label)

    now=datetime(2026,9,1,12,0,tzinfo=timezone.utc)
    reviews=InMemoryAttachmentInterpretationReviewRepository()
    suppliers=_supplier_repository()

    urgent=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="p1-60-urgent",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("1"),
        interpretation=_customer_interpretation_with(
            required_delivery_date="2026-09-02",
            is_adr=None,
            is_temperature_controlled=None,
            is_high_value=None,
        ),
        repository=reviews,supplier_repository=suppliers,trusted_customer_name="Pilot Customer",
    )
    reviews.save(urgent.model_copy(update={"created_at":now-timedelta(hours=2)}))

    low=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="p1-60-low",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("2"),interpretation=_customer_interpretation(),
        repository=reviews,supplier_repository=suppliers,trusted_customer_name="Pilot Customer",
    )
    reviews.save(low.model_copy(update={"created_at":now-timedelta(hours=1)}))

    aged=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="p1-60-aged",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("3"),interpretation=_customer_interpretation(),
        repository=reviews,supplier_repository=suppliers,trusted_customer_name="Pilot Customer",
    )
    reviews.save(aged.model_copy(update={"created_at":now-timedelta(hours=50)}))

    supplier_review=create_attachment_interpretation_review(
        mail=_mail(sender=SUPPLIER_EMAIL,message_id="p1-60-stale",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("4"),interpretation=_supplier_interpretation(),
        repository=reviews,supplier_repository=suppliers,rfq_id="rfq-router-1",
        correlation_method="supplier_identity",
    )
    reviews.save(supplier_review.model_copy(update={"created_at":now-timedelta(hours=1)}))
    draft=suppliers.get_draft("rfq-router-1")
    suppliers.save_drafts([draft.model_copy(update={"subject":draft.subject+" changed"})])

    rejected=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="p1-60-rejected",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("5"),interpretation=_customer_interpretation(),
        repository=reviews,supplier_repository=suppliers,trusted_customer_name="Pilot Customer",
    )
    reject_attachment_interpretation_review(
        repository=reviews,review_id=rejected.review_id,operator_identity="Queue Operator",
        rejection_reason="Not actionable.",reviewed_at=now,
    )

    queue=build_attachment_review_queue(repository=reviews,supplier_repository=suppliers,now=now)
    ids=[item["review_id"] for item in queue["items"]]
    by_id={item["review_id"]:item for item in queue["items"]}
    check(
        queue["pending_count"]==4 and rejected.review_id not in ids
        and queue["priority_counts"]["critical"]==2,
        "queue contains only pending reviews and summarizes priority bands",
    )
    check(
        ids[0]==urgent.review_id
        and by_id[urgent.review_id]["priority_band"]=="critical"
        and by_id[urgent.review_id]["critical_attention_count"]==3
        and by_id[urgent.review_id]["days_until_nearest_deadline"]==1,
        "customer safety unknowns and near delivery date rise to critical priority",
    )
    check(
        by_id[supplier_review.review_id]["priority_band"]=="critical"
        and "supplier_rfq_snapshot_stale" in by_id[supplier_review.review_id]["priority_reasons"],
        "stale supplier RFQ snapshot is surfaced as critical review work",
    )
    check(
        by_id[aged.review_id]["priority_score"]>by_id[low.review_id]["priority_score"]
        and by_id[aged.review_id]["priority_band"]=="normal"
        and by_id[low.review_id]["priority_band"]=="low",
        "review age raises priority without overpowering critical signals",
    )

    freeform=create_attachment_interpretation_review(
        mail=_mail(sender=CUSTOMER_EMAIL,message_id="p1-60-freeform",has_attachments=True,attachment_manifest=[]),
        retrieval=_retrieval("6"),
        interpretation=_customer_interpretation_with(cargo_ready_date="next Friday"),
        repository=reviews,supplier_repository=suppliers,trusted_customer_name="Pilot Customer",
    )
    reviews.save(freeform.model_copy(update={"created_at":now-timedelta(hours=1)}))
    freeform_queue=build_attachment_review_queue(repository=reviews,supplier_repository=suppliers,now=now)
    freeform_item=next(item for item in freeform_queue["items"] if item["review_id"]==freeform.review_id)
    check(
        freeform_item["nearest_deadline_kind"] is None
        and freeform_item["days_until_nearest_deadline"] is None
        and not any("cargo_ready_" in reason for reason in freeform_item["priority_reasons"]),
        "free-form operational dates are never guessed into priority deadlines",
    )
    check(
        "candidate" not in repr(queue) and "subject" not in repr(queue)
        and "sha256" not in repr(queue) and "preview_token" not in repr(queue)
        and "Pilot Customer" not in repr(queue),
        "operational review queue remains privacy-minimal",
    )

    with patch.object(api,"attachment_review_repository",reviews), patch.object(
        api,"supplier_rfq_repository",suppliers
    ):
        api_queue=api.list_attachment_review_queue() if hasattr(api,"list_attachment_review_queue") else None
    check(
        api_queue is not None and api_queue.get("pending_count")==5,
        "authenticated API exposes deterministic attachment review queue",
    )
    return {"name":"Attachment review operational queue","passed":not failures,"failures":failures,"passed_checks":passes}


def main():
    result=evaluate_attachment_review_queue_regressions()
    for x in result["passed_checks"]: print("PASS",x)
    for x in result["failures"]: print("FAIL",x)
    print("\nAttachment review queue regressions:","PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1

if __name__=="__main__": raise SystemExit(main())
