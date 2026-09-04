from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.requests import Request

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import (
    InMemoryLearningFactRepository,
    LearningFactConflictError,
    SQLiteLearningFactRepository,
)
from src.core.learning_fact_service import (
    build_learning_fact_view,
    confirm_learning_fact,
    create_learning_fact,
    list_learning_facts,
    reject_learning_fact,
)
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master, create_supplier_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job
from src.core.mina_job_view import build_mina_job_detail
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository


NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _evidence(source_type="email", reference="message-123", summary="Repeated explicit evidence."):
    return LearningEvidence(
        source_type=source_type,
        source_reference=reference,
        observed_at=NOW - timedelta(days=1),
        summary=summary,
    )


def evaluate_learning_fact_provenance_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    customer = create_customer_master(
        repository=masters, entry_id="customer-learning", customer_name="Beta Enerji",
        updated_by="Operator", created_at=NOW,
    )
    supplier = create_supplier_master(
        repository=masters, entry_id="supplier-learning", supplier_name="TransLog",
        updated_by="Operator", created_at=NOW,
    )
    repo = InMemoryLearningFactRepository()

    proposed = create_learning_fact(
        repository=repo, entry_id="fact-1", subject_type="customer",
        subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key="communication.prefers_proactive_updates", value=True,
        confidence=0.99, source_type="minai_inference", evidence=[_evidence()],
        created_by="MINAI", occurred_at=NOW, master_repository=masters,
    )
    check(
        proposed.status == "proposed" and proposed.confidence_band == "high"
        and not proposed.runtime_authoritative
        and list_learning_facts(repository=repo, runtime_only=True) == [],
        "high-confidence proposed learning remains non-authoritative until human confirmation",
    )

    retried = create_learning_fact(
        repository=repo, entry_id="fact-1", subject_type="customer",
        subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key="communication.prefers_proactive_updates", value=True,
        confidence=0.99, source_type="minai_inference", evidence=[_evidence()],
        created_by="Different Worker", occurred_at=NOW + timedelta(minutes=1), master_repository=masters,
    )
    try:
        create_learning_fact(
            repository=repo, entry_id="fact-1", subject_type="customer",
            subject_id=customer.customer_id, subject_label=customer.customer_name,
            fact_key="communication.prefers_proactive_updates", value=False,
            confidence=0.99, source_type="minai_inference", evidence=[_evidence()],
            created_by="MINAI", occurred_at=NOW + timedelta(minutes=2), master_repository=masters,
        )
        idempotency_conflict = False
    except LearningFactConflictError:
        idempotency_conflict = True
    check(
        retried.fact_id == proposed.fact_id and retried.created_by == "MINAI" and idempotency_conflict,
        "learning fact creation is idempotent and rejects entry identity drift",
    )

    confirmed = confirm_learning_fact(
        repository=repo, fact_id=proposed.fact_id, reviewed_by="Operator",
        review_note="Customer communication history confirms this preference.",
        occurred_at=NOW + timedelta(minutes=3),
    )
    check(
        confirmed.status == "confirmed" and confirmed.runtime_authoritative
        and confirmed.reviewed_by == "Operator"
        and [item.fact_id for item in list_learning_facts(repository=repo, runtime_only=True)] == [confirmed.fact_id],
        "human confirmation is the authority boundary for runtime learning",
    )

    duplicate = create_learning_fact(
        repository=repo, entry_id="fact-duplicate", subject_type="customer",
        subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key=confirmed.fact_key, value=False, confidence=0.70,
        source_type="email", evidence=[_evidence(reference="message-456")],
        created_by="MINAI", occurred_at=NOW + timedelta(minutes=4), master_repository=masters,
    )
    try:
        confirm_learning_fact(
            repository=repo, fact_id=duplicate.fact_id, reviewed_by="Operator",
            review_note="Should require explicit replacement.", occurred_at=NOW + timedelta(minutes=5),
        )
        duplicate_authority_blocked = False
    except LearningFactConflictError:
        duplicate_authority_blocked = True
    check(
        duplicate_authority_blocked and confirmed.status == "confirmed",
        "a second confirmed value cannot silently overwrite an active subject key",
    )

    replacement = create_learning_fact(
        repository=repo, entry_id="fact-replacement", subject_type="customer",
        subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key=confirmed.fact_key, value=False, confidence=0.91,
        source_type="operation_history", evidence=[_evidence(
            source_type="operation_history", reference="customer-history-2026q3",
            summary="Recent confirmed operations show the communication preference changed.",
        )],
        supersedes_fact_id=confirmed.fact_id, created_by="MINAI",
        occurred_at=NOW + timedelta(minutes=6), master_repository=masters,
    )
    replacement = confirm_learning_fact(
        repository=repo, fact_id=replacement.fact_id, reviewed_by="Operator",
        review_note="Preference changed; replace the prior confirmed fact.",
        occurred_at=NOW + timedelta(minutes=7),
    )
    old = repo.get(confirmed.fact_id)
    runtime = list_learning_facts(repository=repo, subject_type="customer", subject_id=customer.customer_id, runtime_only=True)
    check(
        old.status == "superseded" and old.superseded_by_fact_id == replacement.fact_id
        and old.reviewed_at == confirmed.reviewed_at and old.reviewed_by == confirmed.reviewed_by
        and old.superseded_at == NOW + timedelta(minutes=7) and old.superseded_by == "Operator"
        and replacement.status == "confirmed" and len(runtime) == 1 and runtime[0].fact_id == replacement.fact_id,
        "explicit replacement preserves original confirmation and separate supersession history",
    )

    rejected = create_learning_fact(
        repository=repo, entry_id="fact-rejected", subject_type="supplier",
        subject_id=supplier.supplier_id, subject_label=supplier.supplier_name,
        fact_key="communication.responds_fast", value=True, confidence=0.55,
        source_type="minai_inference", evidence=[_evidence(reference="supplier-history")],
        created_by="MINAI", occurred_at=NOW + timedelta(minutes=8), master_repository=masters,
    )
    rejected = reject_learning_fact(
        repository=repo, fact_id=rejected.fact_id, reviewed_by="Operator",
        review_note="Evidence is too weak and inconsistent.", occurred_at=NOW + timedelta(minutes=9),
    )
    try:
        confirm_learning_fact(
            repository=repo, fact_id=rejected.fact_id, reviewed_by="Operator",
            review_note="Cannot revive rejected fact.", occurred_at=NOW + timedelta(minutes=10),
        )
        rejected_frozen = False
    except LearningFactConflictError:
        rejected_frozen = True
    check(
        rejected.status == "rejected" and rejected_frozen and not rejected.runtime_authoritative,
        "rejected learning is immutable and cannot become runtime authority",
    )

    try:
        create_learning_fact(
            repository=repo, entry_id="bad-customer", subject_type="customer",
            subject_id="missing", subject_label="Missing", fact_key="profile.test", value="x",
            confidence=0.5, source_type="manual", evidence=[_evidence()], created_by="Operator",
            occurred_at=NOW, master_repository=masters,
        )
        missing_subject_blocked = False
    except ValueError:
        missing_subject_blocked = True
    check(missing_subject_blocked, "customer and supplier learning requires an existing master subject")

    try:
        create_learning_fact(
            repository=repo, entry_id="oversize-fact", subject_type="route",
            subject_id="TR>DE", subject_label="TR-DE", fact_key="notes.oversize",
            value="x" * 2001, confidence=0.5, source_type="manual", evidence=[_evidence()],
            created_by="Operator", occurred_at=NOW,
        )
        bounded_value = False
    except ValueError:
        bounded_value = True
    check(bounded_value, "learning fact values are bounded instead of becoming raw-message storage")

    route_fact = create_learning_fact(
        repository=repo, entry_id="route-fact", subject_type="route",
        subject_id="TR>DE:road:ftl", subject_label="Türkiye → Almanya / Road FTL",
        fact_key="timing.friday_border_risk", value="higher", confidence=0.82,
        source_type="operation_history", evidence=[_evidence(
            source_type="operation_history", reference="route-aggregate-2026q3",
            summary="Friday departures showed longer border waiting in the reviewed sample.",
        )], created_by="MINAI", occurred_at=NOW,
    )
    check(route_fact.status == "proposed", "route learning can exist without inventing a separate route master record")

    jobs = InMemoryMinaJobRepository()
    job = create_manual_mina_job(
        repository=jobs, manual_intake_id="learning-job", intake_channel="phone",
        job_kind="approved_job", shipment=Shipment(
            customer_name="Beta Enerji", pickup_country="Türkiye", delivery_country="Almanya",
            transport_mode="road", service_type="FTL",
        ), opened_by="Operator", opened_at=NOW,
    )
    operation_fact = create_learning_fact(
        repository=repo, entry_id="operation-fact", subject_type="operation",
        subject_id=job.job_id, subject_label=job.mina_code,
        fact_key="operation.customer_update_effective", value=True, confidence=0.88,
        source_type="operation_history", evidence=[_evidence(
            source_type="operation_history", reference=job.mina_code,
            summary="Proactive update prevented a delivery appointment escalation.",
        )], created_by="MINAI", occurred_at=NOW, mina_repository=jobs,
    )
    detail = build_mina_job_detail(
        repository=jobs, supplier_repository=InMemorySupplierRFQRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        action_repository=InMemoryAutomationActionRepository(),
        learning_fact_repository=repo, job_id=job.job_id, now=NOW,
    )
    check(
        detail["learning"]["proposed_count"] == 1
        and detail["learning"]["facts"][0]["fact_id"] == operation_fact.fact_id,
        "MINA job detail exposes operation-specific learning facts without making them authoritative",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "learning.sqlite3", retention_days=30)
        durable_repo = SQLiteLearningFactRepository(store)
        durable = create_learning_fact(
            repository=durable_repo, entry_id="durable-fact", subject_type="route",
            subject_id="TR>DE", subject_label="Türkiye → Almanya", fact_key="timing.border_risk",
            value="elevated", confidence=0.87, source_type="operation_history",
            evidence=[_evidence(source_type="operation_history", reference="aggregate-1")],
            created_by="MINAI", occurred_at=NOW,
        )
        durable = confirm_learning_fact(
            repository=durable_repo, fact_id=durable.fact_id, reviewed_by="Operator",
            review_note="Reviewed aggregate supports this route fact.", occurred_at=NOW + timedelta(minutes=1),
        )
        store.purge_expired(now=NOW + timedelta(days=60))
        reopened = SQLiteLearningFactRepository(store)
        retained = reopened.find_by_entry_id("durable-fact")
        check(
            retained is not None and retained.fact_id == durable.fact_id and retained.status == "confirmed",
            "learning facts evidence review and idempotency index survive ordinary retention purge",
        )

    import src.api as api
    original_learning = api.learning_fact_repository
    original_master = api.master_data_repository
    api_learning = InMemoryLearningFactRepository()
    api_master = InMemoryMasterDataRepository()
    api_customer = create_customer_master(
        repository=api_master, entry_id="api-learning-customer", customer_name="API Learning Customer",
        updated_by="Operator", created_at=NOW,
    )
    api.learning_fact_repository = api_learning
    api.master_data_repository = api_master
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Operator"
    try:
        api_fact = api.post_learning_fact(
            api.LearningFactCreateRequest(
                entry_id="api-fact", subject_type="customer", subject_id=api_customer.customer_id,
                subject_label=api_customer.customer_name, fact_key="communication.prefers_email",
                value=True, confidence=0.95, source_type="email", evidence=[_evidence()],
            ), request,
        )
        pre_runtime = api.get_learning_facts(
            subject_type="customer", subject_id=api_customer.customer_id,
            status=None, runtime_only=True,
        )
        api_confirmed = api.confirm_learning_fact_api(
            api_fact["fact_id"], api.LearningFactReviewRequest(review_note="Explicit history verified."), request,
        )
        customer_view = api.get_customer_learning_facts(api_customer.customer_id)
    finally:
        api.learning_fact_repository = original_learning
        api.master_data_repository = original_master
    check(
        pre_runtime["facts"] == [] and api_confirmed["status"] == "confirmed"
        and customer_view["confirmed_count"] == 1 and len(customer_view["runtime_facts"]) == 1,
        "learning fact APIs preserve proposed review and runtime-only authority boundaries",
    )

    check(
        route_allowed("GET", "/learning-facts")
        and route_allowed("POST", "/learning-facts")
        and route_allowed("GET", "/learning-facts/fact-1")
        and route_allowed("POST", "/learning-facts/fact-1/confirm")
        and route_allowed("POST", "/learning-facts/fact-1/reject")
        and route_allowed("GET", "/master-data/customers/customer-1/learning-facts")
        and route_allowed("GET", "/master-data/suppliers/supplier-1/learning-facts")
        and route_allowed("GET", "/mina-jobs/job-1/learning-facts"),
        "pilot access explicitly allows controlled learning-fact review surfaces",
    )

    view = build_learning_fact_view(
        repository=repo, subject_type="customer", subject_id=customer.customer_id,
    )
    check(
        view["confirmed_count"] == 1 and view["superseded_count"] == 1
        and all(item["status"] == "confirmed" for item in view["runtime_facts"]),
        "learning view preserves history while exposing only confirmed runtime facts",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_learning_fact_provenance_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nLearning fact & provenance regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
