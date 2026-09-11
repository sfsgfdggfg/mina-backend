from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.customer_quote_acceptance_learning import derive_customer_quote_acceptance_learning
from src.core.customer_quote_acceptance_policy import (
    ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
    ACCEPTED_MARKUP_MEDIAN_KEY,
    QUOTE_ACCEPTANCE_RATE_KEY,
    QUOTE_NEGOTIATION_RATE_KEY,
    build_customer_quote_acceptance_policy,
)
from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact, create_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import (
    create_manual_mina_job,
    record_mina_job_customer_quote_sent,
    transition_mina_job_stage,
)
from src.core.models import CustomerQuote, QuoteDraft, Shipment
from src.core.pilot_access import route_allowed
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.quote_revision import QuoteRevision

NOW = datetime(2026, 9, 11, 16, 15, tzinfo=timezone.utc)


def _quote(price: float, currency: str, markup: float) -> CustomerQuote:
    return CustomerQuote(
        supplier_cost=max(1.0, price - markup),
        markup_type="fixed_profit",
        markup_value=markup,
        final_price=price,
        currency=currency,
    )


def _build_job(
    jobs, cases, customer, index: int, *, outcome: str | None,
    price: float, currency: str = "EUR", markup: float = 300,
    negotiated: bool = False, send: bool = True,
    delivery_country: str = "Germany", equipment: str = "Tenteli",
    unsent_revision_price: float | None = None,
):
    opened = NOW - timedelta(days=30 - index)
    shipment = Shipment(
        customer_name=customer.customer_name,
        transport_mode="road",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country=delivery_country,
        delivery_city="Munich" if delivery_country == "Germany" else "Paris",
        commodity="Textile",
        equipment_type=equipment,
        cargo_ready_date="2026-09-20",
    )
    job = create_manual_mina_job(
        repository=jobs,
        manual_intake_id=f"acceptance-{index}",
        intake_channel="phone",
        job_kind="price_request",
        shipment=shipment,
        opened_by="Regression",
        opened_at=opened,
    )
    original = _quote(price, currency, markup)
    case = QuoteCase(
        shipment=shipment.model_copy(deep=True),
        mina_job_id=job.job_id,
        mina_code=job.mina_code,
        customer_quote=original,
        quote_draft=QuoteDraft(subject="Offer", body=f"Offer {price} {currency}"),
    )
    cases.save(case)
    job = jobs.save(job.model_copy(update={"quote_case_id": case.case_id}))
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code,
        target_stage="pricing", actor="Regression", occurred_at=opened + timedelta(minutes=10),
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code,
        target_stage="quote_ready", actor="Regression", occurred_at=opened + timedelta(minutes=20),
    )
    if send:
        job = record_mina_job_customer_quote_sent(
            repository=jobs, job_id=job.job_id, actor="Regression",
            revision_number=0, send_mode="manual", occurred_at=opened + timedelta(minutes=30),
        )
    if unsent_revision_price is not None:
        revised = _quote(unsent_revision_price, currency, 999)
        revision = QuoteRevision(
            revision_number=1,
            previous_approval_id="approval-0",
            new_approval_id="approval-1",
            previous_quote_draft=case.quote_draft,
            revised_quote_draft=QuoteDraft(subject="Unsent revised", body=f"Unsent {unsent_revision_price}"),
            previous_customer_quote=original,
            revised_customer_quote=revised,
            changed_fields=["final_price"],
            edited_by="Regression",
            edited_at=opened + timedelta(minutes=35),
        )
        case = case.model_copy(update={
            "customer_quote": revised,
            "quote_draft": revision.revised_quote_draft,
            "quote_revisions": [revision],
            "updated_at": opened + timedelta(minutes=35),
        })
        cases.save(case)
    if negotiated and send:
        job = transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code,
            target_stage="negotiation", actor="Regression", occurred_at=opened + timedelta(minutes=40),
        )
    if outcome is not None:
        reason = "Synthetic lost reason" if outcome == "lost" else None
        job = transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code,
            target_stage=outcome, actor="Regression", reason=reason,
            occurred_at=opened + timedelta(minutes=60),
        )
    return job, case


def evaluate_customer_quote_acceptance_learning_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    jobs = InMemoryMinaJobRepository()
    cases = InMemoryQuoteCaseRepository()
    facts = InMemoryLearningFactRepository()
    customer = create_customer_master(
        repository=masters,
        entry_id="quote-acceptance-customer",
        customer_name="Acceptance Customer",
        aliases=["ACCEPTANCE"],
        trusted_sender_addresses=["ops@acceptance.invalid"],
        updated_by="Regression",
        created_at=NOW - timedelta(days=200),
    )

    # Five EUR/Germany resolved quotes: 3 accepted, 2 lost; two entered negotiation.
    _build_job(jobs, cases, customer, 1, outcome="accepted", price=2000, markup=200, unsent_revision_price=9000)
    _build_job(jobs, cases, customer, 2, outcome="accepted", price=2200, markup=300, negotiated=True)
    _build_job(jobs, cases, customer, 3, outcome="accepted", price=2400, markup=400)
    _build_job(jobs, cases, customer, 4, outcome="lost", price=2500, markup=450, negotiated=True)
    _build_job(jobs, cases, customer, 5, outcome="lost", price=2600, markup=500)
    # Three USD accepted quotes prove currency-separated price/markup observations.
    _build_job(jobs, cases, customer, 6, outcome="accepted", price=3000, currency="USD", markup=300)
    _build_job(jobs, cases, customer, 7, outcome="accepted", price=3300, currency="USD", markup=330)
    _build_job(jobs, cases, customer, 8, outcome="accepted", price=3600, currency="USD", markup=360)
    # Lost without send evidence and unresolved sent quote must stay out of resolved denominator.
    _build_job(jobs, cases, customer, 9, outcome="lost", price=9999, send=False)
    _build_job(jobs, cases, customer, 10, outcome=None, price=7777, send=True)

    derived = derive_customer_quote_acceptance_learning(
        customer_id=customer.customer_id,
        master_repository=masters,
        mina_repository=jobs,
        quote_case_repository=cases,
        learning_repository=facts,
        created_by="Regression",
        occurred_at=NOW,
    )
    check(
        derived["resolved_sent_quote_count"] == 8
        and derived["accepted_count"] == 6
        and derived["lost_count"] == 2
        and derived["excluded_without_send_evidence_count"] == 1
        and derived["excluded_unresolved_sent_quote_count"] == 1,
        "acceptance denominator uses only durably sent quotes with observed accepted/lost outcomes",
    )
    global_acceptance = next(
        f for f in facts.list_all()
        if f.fact_key == QUOTE_ACCEPTANCE_RATE_KEY and f.context_key is None
    )
    global_negotiation = next(
        f for f in facts.list_all()
        if f.fact_key == QUOTE_NEGOTIATION_RATE_KEY and f.context_key is None
    )
    check(
        global_acceptance.value == 75.0 and global_negotiation.value == 25.0,
        "global quote outcome and negotiation rates remain descriptive observations",
    )

    price_facts = [f for f in facts.list_all() if f.fact_key == ACCEPTED_FINAL_PRICE_MEDIAN_KEY]
    eur_price = next(f for f in price_facts if f.value_unit == "EUR")
    usd_price = next(f for f in price_facts if f.value_unit == "USD")
    check(
        eur_price.value == 2200.0 and usd_price.value == 3300.0
        and eur_price.context_key != usd_price.context_key,
        "accepted price medians remain separated by shipment context and currency",
    )
    check(
        eur_price.value != 9000.0 and "9000" not in eur_price.evidence[0].summary,
        "an unsent later revision cannot become the accepted-price observation",
    )
    markup_facts = [f for f in facts.list_all() if f.fact_key == ACCEPTED_MARKUP_MEDIAN_KEY]
    eur_markup = next(f for f in markup_facts if "currency=eur" in (f.context_key or ""))
    usd_markup = next(f for f in markup_facts if "currency=usd" in (f.context_key or ""))
    check(
        eur_markup.value == 300.0 and usd_markup.value == 330.0,
        "accepted markup observations stay bound to currency, shipment context and markup method",
    )
    check(
        all("target price" in (f.evidence[0].summary.lower()) or "descriptive" in f.evidence[0].summary.lower() or "observational" in f.evidence[0].summary.lower() for f in facts.list_all()),
        "derived commercial evidence explicitly avoids causal or prescriptive claims",
    )

    for fact in list(facts.list_all()):
        confirm_learning_fact(
            repository=facts,
            fact_id=fact.fact_id,
            reviewed_by="Reviewer",
            review_note="Confirm observational quote acceptance evidence only.",
            occurred_at=NOW + timedelta(minutes=2),
        )
    policy = build_customer_quote_acceptance_policy(
        customer_id=customer.customer_id,
        learning_repository=facts,
        as_of=NOW + timedelta(minutes=3),
    )
    check(
        policy.overall_acceptance_rate_percent == 75.0
        and policy.negotiation_rate_percent == 25.0
        and any(x.fact_key == ACCEPTED_FINAL_PRICE_MEDIAN_KEY for x in policy.contextual_advisories)
        and policy.pricing_authority_created is False
        and policy.causal_claim_created is False,
        "reviewed quote acceptance memory is advisory-only and creates no pricing or causal authority",
    )
    check(
        build_customer_quote_acceptance_policy(
            customer_id=customer.customer_id,
            learning_repository=facts,
            as_of=NOW + timedelta(days=800),
        ).overall_acceptance_rate_percent is None,
        "stale quote outcome evidence decays out of even advisory policy",
    )

    # Customer quote context is allowed only for canonical quote-observation keys.
    try:
        create_learning_fact(
            repository=facts,
            entry_id="invalid-customer-context",
            subject_type="customer",
            subject_id=customer.customer_id,
            subject_label=customer.customer_name,
            fact_key="preference.default_pickup_city",
            context_key="quote|mode=road|lane=turkiye>germany|currency=eur",
            value="Adana",
            value_unit="text",
            confidence=0.9,
            source_type="manual",
            evidence=[LearningEvidence(
                source_type="manual",
                source_reference="invalid-context",
                observed_at=NOW,
                summary="Invalid context scope regression.",
            )],
            created_by="Regression",
            occurred_at=NOW,
            master_repository=masters,
        )
        invalid_context_blocked = False
    except ValueError:
        invalid_context_blocked = True
    check(
        invalid_context_blocked,
        "customer context authority stays restricted to canonical quote-observation metrics",
    )
    check(
        route_allowed("POST", f"/master-data/customers/{customer.customer_id}/derive-quote-acceptance")
        and route_allowed("GET", f"/master-data/customers/{customer.customer_id}/quote-acceptance-policy"),
        "controlled pilot exposes quote acceptance derivation and read-only advisory policy",
    )
    ui = Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        "Quote Acceptance Learning" in ui
        and "gözlemseldir, nedensel değildir" in ui
        and "pricing authority oluşturmaz" in ui,
        "browser makes the non-causal advisory-only commercial boundary visible",
    )
    check(
        not any(f.fact_key in {"price_sensitivity", "pricing_policy", "customer.target_price"} for f in facts.list_all()),
        "quote outcomes do not fabricate customer price sensitivity, target price or pricing policy",
    )

    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print("PASS", label)
    for label in failures: print("FAIL", label)
    print("\nCustomer quote acceptance learning regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    result = evaluate_customer_quote_acceptance_learning_regressions()
    raise SystemExit(0 if result["passed"] else 1)
