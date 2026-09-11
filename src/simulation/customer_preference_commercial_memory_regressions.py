from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.customer_memory import enrich_shipment_with_customer_memory
from src.core.customer_preference_learning import derive_customer_preference_learning
from src.core.customer_preference_policy import build_customer_preference_policy
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master, customer_to_legacy_memory
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.models import CustomerQuote, Shipment
from src.core.pilot_access import route_allowed
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository

NOW=datetime(2026,9,11,15,0,tzinfo=timezone.utc)


def _job(repo, cases, customer, index, *, city="Adana", currency="EUR", accepted=True):
    opened=NOW-timedelta(days=20-index)
    shipment=Shipment(
        customer_name=customer.customer_name, transport_mode="road",
        pickup_country="Türkiye", pickup_city=city,
        delivery_country="Germany", delivery_city="Munich",
        commodity="Textile", equipment_type="Tenteli", cargo_ready_date="2026-09-20",
    )
    job,_=repo.create_manual(
        manual_intake_id=f"pref-{index}", intake_channel="phone", job_kind="price_request",
        shipment=shipment, opened_by="Regression", opened_at=opened,
        sequence_year=2026, lifecycle_version=2,
    )
    if accepted:
        case=QuoteCase(
            shipment=shipment.model_copy(deep=True), mina_job_id=job.job_id, mina_code=job.mina_code,
            customer_quote=CustomerQuote(supplier_cost=2000,markup_type="percentage",markup_value=10,final_price=2200,currency=currency),
        )
        cases.save(case)
        job=job.model_copy(update={"stage":"accepted","quote_case_id":case.case_id,"updated_at":opened+timedelta(hours=2)})
        repo.save(job)
    return job


def evaluate_customer_preference_commercial_memory_regressions():
    passes=[];failures=[]
    def check(condition,label):(passes if condition else failures).append(label)
    masters=InMemoryMasterDataRepository();jobs=InMemoryMinaJobRepository();cases=InMemoryQuoteCaseRepository();facts=InMemoryLearningFactRepository()
    customer=create_customer_master(
        repository=masters,entry_id="customer-pref",customer_name="Acme Customer",
        aliases=["ACME"],trusted_sender_addresses=["ops@acme.invalid"],updated_by="Regression",created_at=NOW-timedelta(days=100),
    )
    for i in range(1,5):_job(jobs,cases,customer,i)
    thin=derive_customer_preference_learning(
        customer_id=customer.customer_id,master_repository=masters,mina_repository=jobs,
        learning_repository=facts,quote_case_repository=cases,created_by="Regression",occurred_at=NOW,
    )
    check(thin["matched_job_count"]==4 and thin["proposed_fact_count"]==0,"fewer than five repeated requests cannot create runtime-default preference proposals")
    _job(jobs,cases,customer,5)
    five=derive_customer_preference_learning(
        customer_id=customer.customer_id,master_repository=masters,mina_repository=jobs,
        learning_repository=facts,quote_case_repository=cases,created_by="Regression",occurred_at=NOW+timedelta(minutes=1),
    )
    proposed=[f for f in facts.list_all() if f.status=="proposed" and f.fact_key.startswith("preference.")]
    check(five["proposed_fact_count"]==6 and all(f.confidence==0.78 for f in proposed),"five highly consistent requests create human-reviewable but sub-threshold defaults")
    city5=next(f for f in proposed if f.fact_key=="preference.default_pickup_city")
    confirm_learning_fact(repository=facts,fact_id=city5.fact_id,reviewed_by="Reviewer",review_note="Review five-sample preference.",occurred_at=NOW+timedelta(minutes=2))
    low=build_customer_preference_policy(customer_id=customer.customer_id,learning_repository=facts,as_of=NOW+timedelta(minutes=3))
    check("default_pickup_city" not in low.learned_defaults,"human confirmation alone does not bypass the higher runtime confidence threshold")
    _job(jobs,cases,customer,6);_job(jobs,cases,customer,7)
    seven=derive_customer_preference_learning(
        customer_id=customer.customer_id,master_repository=masters,mina_repository=jobs,
        learning_repository=facts,quote_case_repository=cases,created_by="Regression",occurred_at=NOW+timedelta(minutes=4),
    )
    city7=next(f for f in facts.list_all() if f.status=="proposed" and f.fact_key=="preference.default_pickup_city" and f.supersedes_fact_id==city5.fact_id)
    check(city7.confidence==0.86,"seven recent consistent requests create an explicit higher-confidence replacement")
    confirm_learning_fact(repository=facts,fact_id=city7.fact_id,reviewed_by="Reviewer",review_note="Confirm mature preference.",occurred_at=NOW+timedelta(minutes=5))
    currency=next(f for f in facts.list_all() if f.status=="proposed" and f.fact_key=="commercial.accepted_quote_currency" and f.confidence>=0.8)
    confirm_learning_fact(repository=facts,fact_id=currency.fact_id,reviewed_by="Reviewer",review_note="Confirm accepted currency history.",occurred_at=NOW+timedelta(minutes=5))
    policy=build_customer_preference_policy(customer_id=customer.customer_id,learning_repository=facts,as_of=NOW+timedelta(minutes=6))
    check(policy.learned_defaults.get("default_pickup_city")=="Adana" and policy.accepted_quote_currency_advisory=="EUR","confirmed mature request default becomes runtime-eligible while accepted currency stays advisory")
    profile=customer_to_legacy_memory(customer)
    missing=Shipment(customer_name="ACME",transport_mode="road",pickup_country="Türkiye",delivery_country="Germany",delivery_city="Munich",commodity="Textile",equipment_type="Tenteli",cargo_ready_date="2026-09-20")
    enriched=enrich_shipment_with_customer_memory(shipment=missing,sender_address="ops@acme.invalid",customer_profiles=[profile],learning_repository=facts)
    check(enriched.matched and missing.pickup_city=="Adana" and city7.fact_id in enriched.preference_fact_ids_applied,"trusted customer identity may fill a missing field from a mature confirmed preference with provenance")
    explicit=Shipment(customer_name="ACME",transport_mode="road",pickup_country="Türkiye",pickup_city="Mersin",delivery_country="Germany",delivery_city="Munich",commodity="Textile",equipment_type="Tenteli",cargo_ready_date="2026-09-20")
    enrich_shipment_with_customer_memory(shipment=explicit,sender_address="ops@acme.invalid",customer_profiles=[profile],learning_repository=facts)
    check(explicit.pickup_city=="Mersin","explicit current-request value always outranks learned customer preference")
    master_profile=profile.model_copy(update={"default_pickup_city":"Istanbul"})
    master_wins=Shipment(customer_name="ACME",transport_mode="road",pickup_country="Türkiye",delivery_country="Germany",delivery_city="Munich",commodity="Textile",equipment_type="Tenteli",cargo_ready_date="2026-09-20")
    enrich_shipment_with_customer_memory(shipment=master_wins,sender_address="ops@acme.invalid",customer_profiles=[master_profile],learning_repository=facts)
    check(master_wins.pickup_city=="Istanbul","explicit Customer Master default outranks confirmed learned preference")
    keys={f.fact_key for f in facts.list_all()}
    check(not any(k in keys for k in {"preference.cargo_ready_date","preference.required_delivery_date","preference.adr_class","preference.gross_weight_kg"}),"safety-critical and shipment-specific facts are never derived as customer defaults")
    check(route_allowed("POST",f"/master-data/customers/{customer.customer_id}/derive-preferences") and route_allowed("GET",f"/master-data/customers/{customer.customer_id}/preference-policy"),"controlled pilot exposes reviewed customer preference derivation and read-only policy")
    ui=Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check("Öğrenilen Müşteri Tercihleri" in ui and "pricing authority değildir" in ui,"browser exposes customer preference review and commercial-advisory boundaries")
    result={"passes":passes,"failures":failures,"passed":not failures}
    for x in passes:print("PASS",x)
    for x in failures:print("FAIL",x)
    print("\nCustomer preference & commercial memory regressions:","PASS" if not failures else "FAIL")
    return result

if __name__=="__main__":
    result=evaluate_customer_preference_commercial_memory_regressions();raise SystemExit(0 if result["passed"] else 1)
