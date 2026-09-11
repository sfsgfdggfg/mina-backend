from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import create_manual_mina_job, link_mina_job_workflow, transition_mina_job_stage
from src.core.models import Shipment
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.sqlite_repositories import SQLiteMinaJobRepository
from src.core.supplier_intelligence_policy import build_supplier_operational_learning_policy
from src.core.supplier_learning_service import derive_supplier_history_learning
from src.core.supplier_price import offer_from_rfq_response
from src.core.supplier_price_repository import InMemorySupplierPriceRepository, SQLiteSupplierPriceRepository
from src.core.supplier_price_service import build_job_supplier_price_view, create_direct_supplier_price_offer, record_supplier_negotiation_result
from src.core.supplier_rfq import SupplierRFQDraft, SupplierRFQResponse, SupplierRFQWorkflow
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 10, 10, 0, tzinfo=timezone.utc)

def _shipment() -> Shipment:
    return Shipment(
        customer_name="Negotiation Customer", pickup_country="Türkiye", pickup_city="Bursa",
        delivery_country="Germany", delivery_city="Stuttgart", transport_mode="road",
        service_type="FTL", equipment_type="Tenteli", quote_mode="indicative",
    )


def _pricing_job(jobs, suffix: str, when: datetime):
    job = create_manual_mina_job(
        repository=jobs, manual_intake_id=f"neg-{suffix}", intake_channel="phone",
        job_kind="price_request", shipment=_shipment(), opened_by="Regression Operator", opened_at=when,
    )
    return transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="pricing",
        actor="Regression Operator", occurred_at=when + timedelta(minutes=1),
    )


def _direct(prices, jobs, job, entry: str, cost: float, when: datetime, *, supplier="Negotiable Trans", currency="EUR"):
    return create_direct_supplier_price_offer(
        price_repository=prices, mina_repository=jobs, job_id=job.job_id, entry_id=entry,
        supplier_name=supplier, source_type="phone", cost=cost, currency=currency,
        recorded_by="Regression Operator", recorded_at=when,
    )

def evaluate_supplier_negotiation_intelligence_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []
    def check(condition, label): (passes if condition else failures).append(label)

    jobs = InMemoryMinaJobRepository()
    prices = InMemorySupplierPriceRepository()
    rfqs = InMemorySupplierRFQRepository()
    masters = InMemoryMasterDataRepository()
    facts = InMemoryLearningFactRepository()
    supplier = create_supplier_master(
        repository=masters, entry_id="supplier:negotiable-trans", supplier_name="Negotiable Trans",
        role="primary", updated_by="Regression Operator", created_at=NOW - timedelta(days=30),
    )

    job = _pricing_job(jobs, "direct", NOW)
    before = _direct(prices, jobs, job, "direct-before", 2600, NOW + timedelta(minutes=10))
    after = _direct(prices, jobs, job, "direct-after", 2450, NOW + timedelta(minutes=20))
    check(
        prices.list_negotiations(job.job_id) == [],
        "two supplier prices alone never become negotiation evidence",
    )

    evidence = record_supplier_negotiation_result(
        price_repository=prices, mina_repository=jobs, supplier_repository=rfqs,
        job_id=job.job_id, entry_id="neg-direct", before_offer_id=before.offer_id,
        after_offer_id=after.offer_id, channel="phone", recorded_by="Regression Operator",
        recorded_at=NOW + timedelta(minutes=21),
    )
    repeated = record_supplier_negotiation_result(
        price_repository=prices, mina_repository=jobs, supplier_repository=rfqs,
        job_id=job.job_id, entry_id="neg-direct", before_offer_id=before.offer_id,
        after_offer_id=after.offer_id, channel="phone", recorded_by="Regression Operator",
        recorded_at=NOW + timedelta(minutes=22),
    )
    view = build_job_supplier_price_view(
        price_repository=prices, mina_repository=jobs, supplier_repository=rfqs, job_id=job.job_id,
    )
    check(
        evidence.reduction_amount == 150 and evidence.reduction_percent == 5.7692
        and repeated.negotiation_id == evidence.negotiation_id
        and len(view["negotiations"]) == 1
        and any(item.event_type == "supplier_negotiation_recorded" for item in jobs.list_events(job.job_id)),
        "explicit same-supplier price reduction creates idempotent auditable negotiation evidence",
    )

    invalid_cases = []
    other_supplier = _direct(prices, jobs, job, "other-supplier", 2300, NOW + timedelta(minutes=25), supplier="Other Trans")
    usd_offer = _direct(prices, jobs, job, "usd-after", 2400, NOW + timedelta(minutes=26), currency="USD")
    higher_offer = _direct(prices, jobs, job, "higher-after", 2700, NOW + timedelta(minutes=27))
    for name, candidate in [("different_supplier", other_supplier), ("different_currency", usd_offer), ("not_a_reduction", higher_offer)]:
        try:
            record_supplier_negotiation_result(
                price_repository=prices, mina_repository=jobs, supplier_repository=rfqs,
                job_id=job.job_id, entry_id=f"invalid-{name}", before_offer_id=before.offer_id,
                after_offer_id=candidate.offer_id, channel="phone", recorded_by="Regression Operator",
                recorded_at=NOW + timedelta(minutes=28),
            )
        except ValueError:
            invalid_cases.append(name)
    check(
        set(invalid_cases) == {"different_supplier", "different_currency", "not_a_reduction"},
        "negotiation evidence rejects cross-supplier cross-currency and non-reduction price pairs",
    )

    rfq_job = _pricing_job(jobs, "rfq", NOW + timedelta(hours=1))
    workflow = SupplierRFQWorkflow(
        workflow_id="neg-rfq-workflow", shipment=rfq_job.shipment,
        mina_job_id=rfq_job.job_id, mina_code=rfq_job.mina_code,
    )
    draft = SupplierRFQDraft(
        rfq_id="neg-rfq-1", workflow_id=workflow.workflow_id, supplier_name="Negotiable Trans",
        priority=1, recipient_email="pricing@negotiable.invalid", supplier_role="primary",
        dispatch_tier="primary", subject="RFQ", body="RFQ", status="responded",
        sent_at=NOW + timedelta(hours=1, minutes=5), responded_at=NOW + timedelta(hours=1, minutes=15),
    )
    response = SupplierRFQResponse(
        rfq_id=draft.rfq_id, supplier_name=draft.supplier_name, rfq_priority=1,
        status="quoted", cost=2500, currency="EUR", source="email",
        received_at=NOW + timedelta(hours=1, minutes=15),
    )
    workflow = workflow.model_copy(update={"rfq_ids": [draft.rfq_id]})
    rfqs.save_workflow(workflow); rfqs.save_drafts([draft]); rfqs.save_responses([response])
    link_mina_job_workflow(
        repository=jobs, job_id=rfq_job.job_id, workflow_id=workflow.workflow_id,
        result_type="supplier_rfq_draft", occurred_at=NOW + timedelta(hours=1, minutes=2),
    )
    rfq_after = _direct(prices, jobs, rfq_job, "rfq-neg-after", 2380, NOW + timedelta(hours=1, minutes=25))
    rfq_offer = offer_from_rfq_response(response=response, job_id=rfq_job.job_id, mina_code=rfq_job.mina_code)
    rfq_evidence = record_supplier_negotiation_result(
        price_repository=prices, mina_repository=jobs, supplier_repository=rfqs,
        job_id=rfq_job.job_id, entry_id="neg-rfq-result", before_offer_id=rfq_offer.offer_id,
        after_offer_id=rfq_after.offer_id, channel="whatsapp", recorded_by="Regression Operator",
        recorded_at=NOW + timedelta(hours=1, minutes=26),
    )
    check(
        rfq_evidence.before_cost == 2500 and rfq_evidence.after_cost == 2380
        and rfq_evidence.reduction_percent == 4.8,
        "RFQ email price can be explicitly linked to a later direct negotiated price",
    )

    sample_specs = [
        ("sample-3", 2500, 2350, "phone", 2),
        ("sample-4", 2400, 2232, "whatsapp", 3),
        ("sample-5", 2000, 1840, "phone", 4),
    ]
    for suffix, initial, final, channel, hour in sample_specs:
        sample_job = _pricing_job(jobs, suffix, NOW + timedelta(hours=hour))
        first = _direct(prices, jobs, sample_job, f"{suffix}-before", initial, NOW + timedelta(hours=hour, minutes=10))
        last = _direct(prices, jobs, sample_job, f"{suffix}-after", final, NOW + timedelta(hours=hour, minutes=20))
        record_supplier_negotiation_result(
            price_repository=prices, mina_repository=jobs, job_id=sample_job.job_id,
            entry_id=f"{suffix}-neg", before_offer_id=first.offer_id, after_offer_id=last.offer_id,
            channel=channel, recorded_by="Regression Operator", recorded_at=NOW + timedelta(hours=hour, minutes=21),
        )

    derived = derive_supplier_history_learning(
        supplier_id=supplier.supplier_id, master_repository=masters, supplier_repository=rfqs,
        learning_repository=facts, price_repository=prices, created_by="Regression Operator",
        occurred_at=NOW + timedelta(hours=6),
    )
    negotiation_fact = next(
        item for item in facts.list_all()
        if item.subject_id == supplier.supplier_id and item.fact_key == "commercial.negotiated_reduction_percent"
    )
    before_confirm = build_supplier_operational_learning_policy(
        supplier=supplier, learning_repository=facts, base_first_reminder_minutes=30,
        base_acknowledged_wait_minutes=120, as_of=NOW + timedelta(hours=6),
    )
    check(
        derived["negotiation_evidence_count"] == 5
        and negotiation_fact.status == "proposed"
        and negotiation_fact.value == 6.0
        and negotiation_fact.confidence == 0.8
        and before_confirm.negotiation_advisory_percent is None,
        "explicit negotiation history derives a proposed median reduction fact without automatic authority",
    )
    confirmed = confirm_learning_fact(
        repository=facts, fact_id=negotiation_fact.fact_id, reviewed_by="Regression Operator",
        review_note="Reviewed explicit supplier negotiation evidence.", occurred_at=NOW + timedelta(hours=6, minutes=5),
    )
    after_confirm = build_supplier_operational_learning_policy(
        supplier=supplier, learning_repository=facts, base_first_reminder_minutes=30,
        base_acknowledged_wait_minutes=120, as_of=NOW + timedelta(hours=6, minutes=5),
    )
    check(
        confirmed.status == "confirmed" and after_confirm.negotiation_advisory_percent == 6.0
        and after_confirm.contact_escalation_learning_applied is False,
        "human-confirmed negotiation history becomes advisory only and does not authorize contact or commercial action",
    )

    with TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "negotiation.sqlite3", retention_days=365)
        durable_jobs = SQLiteMinaJobRepository(store)
        durable_prices = SQLiteSupplierPriceRepository(store)
        durable_job = _pricing_job(durable_jobs, "durable", NOW + timedelta(hours=7))
        durable_before = _direct(
            durable_prices, durable_jobs, durable_job, "durable-before", 3000,
            NOW + timedelta(hours=7, minutes=10),
        )
        durable_after = _direct(
            durable_prices, durable_jobs, durable_job, "durable-after", 2820,
            NOW + timedelta(hours=7, minutes=20),
        )
        durable_evidence = record_supplier_negotiation_result(
            price_repository=durable_prices, mina_repository=durable_jobs,
            job_id=durable_job.job_id, entry_id="durable-negotiation",
            before_offer_id=durable_before.offer_id, after_offer_id=durable_after.offer_id,
            channel="phone", recorded_by="Regression Operator",
            recorded_at=NOW + timedelta(hours=7, minutes=21),
        )
        rebuilt = SQLiteSupplierPriceRepository(store)
        persisted = rebuilt.list_negotiations(durable_job.job_id)
        check(
            len(persisted) == 1 and persisted[0].negotiation_id == durable_evidence.negotiation_id
            and persisted[0].reduction_percent == 6.0,
            "supplier negotiation evidence is durable in SQLite and survives repository reconstruction",
        )

    root = Path(__file__).resolve().parents[2]
    app_js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        route_allowed("POST", f"/mina-jobs/{job.job_id}/supplier-prices/negotiations")
        and "Pazarlık Sonucu Kaydet" in app_js
        and "Pazarlık Kanıtını Kaydet" in app_js
        and "/supplier-prices/negotiations" in app_js
        and "İki fiyat arasındaki düşüş ancak operatör ilişkilendirirse pazarlık kanıtı sayılır." in app_js,
        "controlled pilot and browser expose explicit negotiation evidence without implicit price-pair inference",
    )

    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier negotiation intelligence regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome = evaluate_supplier_negotiation_intelligence_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
