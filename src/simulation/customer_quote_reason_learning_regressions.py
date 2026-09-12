from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.customer_loss_feedback import record_loss_feedback
from src.core.customer_quote_reason_learning import derive_customer_quote_reason_learning
from src.core.customer_quote_reason_policy import (
    CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
    PRICE_OBJECTION_RATE_KEY,
    TRANSIT_TIME_OBJECTION_RATE_KEY,
    build_customer_quote_reason_policy,
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

NOW = datetime(2026, 9, 11, 18, 0, tzinfo=timezone.utc)


def _environment(name: str):
    masters = InMemoryMasterDataRepository()
    customer = create_customer_master(
        repository=masters, entry_id=f"reason-{name}", customer_name=name,
        aliases=[], trusted_sender_addresses=[f"ops@{name.casefold().replace(' ', '-')}.invalid"],
        updated_by="Regression", created_at=NOW - timedelta(days=200),
    )
    return masters, customer, InMemoryMinaJobRepository(), InMemoryQuoteCaseRepository(), InMemoryLearningFactRepository()


def _lost_quote(
    jobs, cases, customer, index: int, *, currency: str = "EUR", delivery_country: str = "Germany",
    send: bool = True, lost_at: datetime | None = None,
):
    opened = NOW - timedelta(days=40 - index)
    shipment = Shipment(
        customer_name=customer.customer_name, transport_mode="road",
        pickup_country="Türkiye", pickup_city="Adana",
        delivery_country=delivery_country,
        delivery_city="Munich" if delivery_country == "Germany" else "Paris",
        commodity="Textile", equipment_type="Tenteli", cargo_ready_date="2026-09-20",
    )
    job = create_manual_mina_job(
        repository=jobs, manual_intake_id=f"{customer.customer_id}-{index}", intake_channel="phone",
        job_kind="price_request", shipment=shipment, opened_by="Regression", opened_at=opened,
    )
    case = QuoteCase(
        shipment=shipment.model_copy(deep=True), mina_job_id=job.job_id, mina_code=job.mina_code,
        customer_quote=CustomerQuote(
            supplier_cost=1800, markup_type="fixed_profit", markup_value=200,
            final_price=2000, currency=currency,
        ),
        quote_draft=QuoteDraft(subject="Offer", body=f"Offer 2000 {currency}"),
    )
    cases.save(case)
    job = jobs.save(job.model_copy(update={"quote_case_id": case.case_id}))
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="pricing",
        actor="Regression", occurred_at=opened + timedelta(minutes=10),
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="quote_ready",
        actor="Regression", occurred_at=opened + timedelta(minutes=20),
    )
    if send:
        job = record_mina_job_customer_quote_sent(
            repository=jobs, job_id=job.job_id, actor="Regression", revision_number=0,
            send_mode="manual", occurred_at=opened + timedelta(minutes=30),
        )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="lost", actor="Regression",
        reason="Legacy free text says price regardless of structured evidence.",
        occurred_at=lost_at or opened + timedelta(minutes=60),
    )
    return job


def _feedback(
    jobs, job, index: int, *, category: str, basis: str = "customer_explicit",
    target: float | None = None, currency: str | None = None,
    supersedes: str | None = None, occurred_at: datetime | None = None,
):
    return record_loss_feedback(
        repository=jobs, job_id=job.job_id, entry_id=f"feedback-{job.job_id}-{index}",
        category=category, evidence_basis=basis,
        source_channel="email" if basis == "customer_explicit" else "internal",
        note="Bounded structured regression evidence from the selected evidence basis.",
        customer_stated_target_price=target, currency=currency,
        supersedes_feedback_id=supersedes, recorded_by="Regression",
        occurred_at=occurred_at or NOW - timedelta(minutes=20) + timedelta(seconds=index),
    )


def _derive(masters, customer, jobs, cases, facts):
    return derive_customer_quote_reason_learning(
        customer_id=customer.customer_id, master_repository=masters,
        mina_repository=jobs, quote_case_repository=cases,
        learning_repository=facts, created_by="Regression", occurred_at=NOW,
    )


def evaluate_customer_quote_reason_learning_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []
    def check(condition, label): (passes if condition else failures).append(label)

    # Four covered losses cannot pass the five-record sample gate even with three price observations.
    masters, customer, jobs, cases, facts = _environment("Reason Small")
    for index in range(1, 5):
        job = _lost_quote(jobs, cases, customer, index)
        _feedback(jobs, job, index, category="price" if index <= 3 else "other")
    small = _derive(masters, customer, jobs, cases, facts)
    check(
        small["current_structured_feedback_count"] == 4 and small["proposed_fact_count"] == 0,
        "insufficient structured sent-and-lost sample creates no reason proposal",
    )

    # Five feedback records among seven sent-and-lost jobs is below 80%; missing stays missing.
    masters, customer, jobs, cases, facts = _environment("Reason Coverage")
    for index in range(1, 8):
        job = _lost_quote(jobs, cases, customer, index)
        if index <= 5:
            _feedback(jobs, job, index, category="price")
    low_coverage = _derive(masters, customer, jobs, cases, facts)
    check(
        low_coverage["sent_and_lost_job_count"] == 7
        and low_coverage["current_structured_feedback_count"] == 5
        and low_coverage["structured_feedback_coverage_percent"] == 71.43
        and not low_coverage["reason_rate_coverage_gate_met"]
        and low_coverage["proposed_fact_count"] == 0,
        "low structured-feedback coverage blocks learning without coercing missing to unknown",
    )

    masters, customer, jobs, cases, facts = _environment("Reason Explicit")
    reason_jobs = [_lost_quote(jobs, cases, customer, index) for index in range(1, 9)]
    for index in range(3):
        _feedback(jobs, reason_jobs[index], index + 1, category="price")
    for index in range(3, 5):
        _feedback(jobs, reason_jobs[index], index + 1, category="transit_time")
    old = _feedback(jobs, reason_jobs[5], 6, category="price")
    _feedback(jobs, reason_jobs[5], 106, category="transit_time", supersedes=old.feedback_id)
    _feedback(jobs, reason_jobs[6], 7, category="price", basis="operator_assessment")
    _feedback(jobs, reason_jobs[7], 8, category="transit_time", basis="unknown")
    no_send = _lost_quote(jobs, cases, customer, 20, send=False)
    _feedback(jobs, no_send, 20, category="price")
    future_feedback_job = _lost_quote(jobs, cases, customer, 21)
    _feedback(
        jobs, future_feedback_job, 21, category="price",
        occurred_at=NOW + timedelta(days=1),
    )
    future_loss = _lost_quote(jobs, cases, customer, 22, lost_at=NOW + timedelta(days=2))
    _feedback(jobs, future_loss, 22, category="price", occurred_at=NOW + timedelta(days=2, minutes=1))
    derived = _derive(masters, customer, jobs, cases, facts)
    reason_facts = {fact.fact_key: fact for fact in facts.list_all()}
    check(
        set(reason_facts) == {PRICE_OBJECTION_RATE_KEY, TRANSIT_TIME_OBJECTION_RATE_KEY}
        and reason_facts[PRICE_OBJECTION_RATE_KEY].value == 50.0
        and reason_facts[TRANSIT_TIME_OBJECTION_RATE_KEY].value == 50.0,
        "explicit price and transit facts use only current customer-stated observations",
    )
    check(
        derived["customer_explicit_feedback_count"] == 6
        and derived["current_structured_feedback_count"] == 8,
        "operator assessment and unknown evidence are wholly excluded from behavioral values",
    )
    check(
        reason_facts[PRICE_OBJECTION_RATE_KEY].value == 50.0,
        "superseded feedback does not double-count its former price category",
    )
    check(
        derived["excluded_without_send_evidence_count"] == 1
        and derived["sent_and_lost_job_count"] == 9
        and derived["excluded_future_evidence_count"] >= 1,
        "no-send and future-dated outcome evidence cannot support reason learning",
    )
    check(
        all("Legacy free text" not in fact.evidence[0].summary for fact in facts.list_all()),
        "legacy free-text loss reasons are never classified or copied into learning evidence",
    )
    check(
        all(fact.status == "proposed" for fact in facts.list_all()),
        "reason derivation creates proposals and never bypasses human confirmation",
    )
    proposed_policy = build_customer_quote_reason_policy(
        customer_id=customer.customer_id, learning_repository=facts, as_of=NOW,
    )
    check(
        proposed_policy.price_objection_rate_percent is None
        and proposed_policy.transit_time_objection_rate_percent is None,
        "unconfirmed reason proposals have no advisory effect",
    )
    for fact in list(facts.list_all()):
        confirm_learning_fact(
            repository=facts, fact_id=fact.fact_id, reviewed_by="Reviewer",
            review_note="Confirm customer-stated historical advisory only.",
            occurred_at=NOW + timedelta(minutes=1),
        )
    policy = build_customer_quote_reason_policy(
        customer_id=customer.customer_id, learning_repository=facts, as_of=NOW + timedelta(minutes=2),
    )
    stale = build_customer_quote_reason_policy(
        customer_id=customer.customer_id, learning_repository=facts, as_of=NOW + timedelta(days=800),
    )
    check(
        policy.price_objection_rate_percent == 50.0
        and policy.transit_time_objection_rate_percent == 50.0
        and stale.price_objection_rate_percent is None,
        "confirmed reason facts are advisory with recency decay",
    )
    check(
        not any([
            policy.pricing_authority_created, policy.margin_mutation_authority_created,
            policy.supplier_ranking_authority_created, policy.supplier_eligibility_authority_created,
            policy.automation_authority_created, policy.quote_send_authority_created,
            policy.causal_claim_created, policy.win_probability_created,
            policy.price_sensitivity_created, policy.willingness_to_pay_created,
        ]),
        "advisory policy creates no pricing, causal, supplier, automation, or quote-send authority",
    )

    masters, customer, jobs, cases, facts = _environment("Reason Targets")
    target_specs = [
        ("EUR", "Germany", [2000, 2200, 2400]),
        ("USD", "Germany", [3000, 3300, 3600]),
        ("EUR", "France", [4000, 4400, 4800]),
    ]
    index = 1
    for currency, country, values in target_specs:
        for value in values:
            job = _lost_quote(
                jobs, cases, customer, index, currency=currency, delivery_country=country,
            )
            _feedback(jobs, job, index, category="other", target=value, currency=currency)
            index += 1
    target_derived = _derive(masters, customer, jobs, cases, facts)
    target_facts = [fact for fact in facts.list_all() if fact.fact_key == CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY]
    check(
        len(target_facts) == 3
        and sorted((fact.value_unit, fact.value) for fact in target_facts)
        == [("EUR", 2200.0), ("EUR", 4400.0), ("USD", 3300.0)],
        "target-price medians require three explicit observations in each canonical context and currency",
    )
    check(
        len({fact.context_key for fact in target_facts}) == 3
        and target_derived["reason_proposed_facts"] == [],
        "target prices stay separated across currency and shipment context without becoming objection facts",
    )

    future_facts = InMemoryLearningFactRepository()
    future = create_learning_fact(
        repository=future_facts, entry_id="future-reason-policy", subject_type="customer",
        subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key=PRICE_OBJECTION_RATE_KEY, value=80, value_unit="percent", confidence=0.95,
        source_type="manual", evidence=[LearningEvidence(
            source_type="manual", source_reference="future-feedback", observed_at=NOW + timedelta(days=1),
            summary="Future-dated evidence must have no advisory effect.",
        )], created_by="Regression", occurred_at=NOW, master_repository=masters,
    )
    confirm_learning_fact(
        repository=future_facts, fact_id=future.fact_id, reviewed_by="Reviewer",
        review_note="Policy future-date regression.", occurred_at=NOW + timedelta(minutes=1),
    )
    future_policy = build_customer_quote_reason_policy(
        customer_id=customer.customer_id, learning_repository=future_facts, as_of=NOW,
    )
    check(
        future_policy.price_objection_rate_percent is None
        and future_policy.evaluations[0].reason == "future_customer_feedback_evidence_not_authoritative",
        "future-dated confirmed evidence has no advisory effect",
    )
    check(
        route_allowed("POST", f"/master-data/customers/{customer.customer_id}/derive-quote-reason-learning")
        and route_allowed("GET", f"/master-data/customers/{customer.customer_id}/quote-reason-policy"),
        "controlled pilot exposes reason derivation and its read-only advisory policy",
    )
    check(
        not any(
            fact.fact_key in {"price_sensitivity", "willingness_to_pay", "win_probability", "pricing_policy"}
            for fact in facts.list_all()
        ),
        "reason learning does not manufacture pricing or causal facts",
    )

    root = Path(__file__).resolve().parents[2]
    browser_source = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    panel_start = browser_source.index("function renderCustomerQuoteReasonLearning")
    panel_end = browser_source.index("function renderMasterDataSettings", panel_start)
    panel_source = browser_source[panel_start:panel_end]
    check(
        "Neden Bazlı Müşteri Ticari Öğrenimi" in panel_source
        and "derive-quote-reason-learning" in panel_source
        and "quote-reason-policy" in panel_source,
        "customer Master Data UI exposes reason-specific learning derivation and consumes advisory policy",
    )
    check(
        "appendExplicitLearningReview(card, f, load)" in panel_source
        and "appendExplicitLearningReview" in browser_source
        and "/learning-facts/${encodeURIComponent(fact.fact_id)}/${decision}" in browser_source
        and "LearningFact kararı için inceleme notu gerekli." in browser_source,
        "reason-specific UI preserves explicit human confirm and reject review lifecycle with an operator-authored note",
    )
    safety_terms = [
        "nedensel açıklama", "fiyat hassasiyeti", "ödeme isteği", "win probability",
        "otomatik fiyat hedefi", "marj komutu", "tedarikçi pazarlık hedefi", "pricing authority",
        "Geçmiş müşteri-beyanlı hedef fiyat · yalnız advisory kanıt",
    ]
    check(
        all(term in panel_source for term in safety_terms),
        "reason-specific UI makes non-causal advisory and no-pricing-authority boundaries visible",
    )
    check(
        "en az 5" in panel_source and "%80" in panel_source
        and panel_source.count("en az 3") >= 2
        and "Kanonik bağlam" in panel_source,
        "reason-specific UI explains evidence gates and contextual target-price advisory scope",
    )
    check(
        "renderCustomerQuoteReasonLearning(reasons,c)" in browser_source,
        "existing customer Master Data editor attaches the reason-specific learning panel",
    )

    supplier_facing_paths = [
        root / "src" / "ai" / "supplier_rfq_generator.py",
        root / "src" / "ai" / "supplier_follow_up_generator.py",
        root / "src" / "workflow" / "mail_delivery.py",
        root / "src" / "core" / "supplier_rfq_lifecycle.py",
        root / "src" / "core" / "supplier_dispatch_control.py",
        root / "src" / "core" / "supplier_price_service.py",
    ]
    prohibited_supplier_tokens = [
        "derive-quote-reason-learning", "quote-reason-policy",
        "commercial.customer_stated_target_price_median",
        "customer_stated_target_price",
    ]
    supplier_sources = {path: path.read_text(encoding="utf-8") for path in supplier_facing_paths}
    check(
        all(token not in source for source in supplier_sources.values() for token in prohibited_supplier_tokens),
        "supplier RFQ, dispatch, negotiation, follow-up, and outbound mail sources receive no reason API or raw target-price propagation",
    )

    result = {"passed": not failures, "passes": passes, "failures": failures}
    for label in passes:
        print("PASS", label)
    for label in failures:
        print("FAIL", label)
    print("\nCustomer quote reason learning regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    result = evaluate_customer_quote_reason_learning_regressions()
    raise SystemExit(0 if result["passed"] else 1)
