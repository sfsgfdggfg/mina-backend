from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.customer_commercial_context import build_customer_commercial_context
from src.core.customer_preference_policy import COMMERCIAL_ACCEPTED_CURRENCY_KEY
from src.core.customer_quote_acceptance_policy import (
    ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
    ACCEPTED_MARKUP_MEDIAN_KEY,
    QUOTE_ACCEPTANCE_RATE_KEY,
    QUOTE_NEGOTIATION_RATE_KEY,
)
from src.core.customer_quote_context import customer_quote_context_key
from src.core.customer_quote_reason_policy import (
    CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
    PRICE_OBJECTION_RATE_KEY,
    TRANSIT_TIME_OBJECTION_RATE_KEY,
)
from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact, create_learning_fact
from src.core.master_data import normalize_master_text
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_customer_master
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_view import build_mina_job_detail
from src.core.models import CustomerQuote, Shipment
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 11, 18, 30, tzinfo=timezone.utc)
RAW_SENTINEL = "RAW SECRET TARGET SHOULD NOT LEAK"


def _shipment(customer_name: str = "ACME ALT", *, delivery: str = "Germany", equipment: str = "Tenteli") -> Shipment:
    return Shipment(
        customer_name=customer_name,
        transport_mode="road",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country=delivery,
        delivery_city="Munich" if delivery == "Germany" else "Paris",
        equipment_type=equipment,
        commodity="Textile",
        cargo_ready_date="2026-09-20",
    )


def _case(shipment: Shipment, *, currency: str = "EUR", markup_type: str = "percentage") -> QuoteCase:
    return QuoteCase(
        shipment=shipment.model_copy(deep=True),
        customer_quote=CustomerQuote(
            supplier_cost=1800,
            markup_type=markup_type,
            markup_value=10,
            final_price=1980,
            currency=currency,
        ),
    )


def _fact(
    *, facts, masters, customer, key: str, value, unit: str | None = None,
    context: str | None = None, confidence: float = 0.95,
    observed_at: datetime | None = None, confirm: bool = True, suffix: str,
):
    observed = observed_at or (NOW - timedelta(days=10))
    fact = create_learning_fact(
        repository=facts,
        entry_id=f"commercial-context-{suffix}",
        subject_type="customer",
        subject_id=customer.customer_id,
        subject_label=customer.customer_name,
        fact_key=key,
        context_key=context,
        value=value,
        value_unit=unit,
        confidence=confidence,
        source_type="manual",
        evidence=[LearningEvidence(
            source_type="manual",
            source_reference=f"commercial-context-evidence-{suffix}",
            observed_at=observed,
            summary=f"{RAW_SENTINEL} · regression-only evidence for {suffix}",
        )],
        created_by="Regression",
        occurred_at=NOW - timedelta(minutes=5),
        master_repository=masters,
    )
    if confirm:
        fact = confirm_learning_fact(
            repository=facts,
            fact_id=fact.fact_id,
            reviewed_by="Reviewer",
            review_note="Confirm advisory regression evidence only.",
            occurred_at=NOW - timedelta(minutes=4),
        )
    return fact


def evaluate_customer_commercial_context_regressions():
    passes: list[str] = []
    failures: list[str] = []

    def check(condition, label):
        (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    facts = InMemoryLearningFactRepository()
    customer = create_customer_master(
        repository=masters,
        entry_id="commercial-context-customer",
        customer_name="Acme Customer",
        aliases=["ACME ALT"],
        price_sensitivity="high",
        time_sensitivity="low",
        updated_by="Regression",
        created_at=NOW - timedelta(days=100),
    )
    shipment = _shipment()
    quote_case = _case(shipment)
    base_context = customer_quote_context_key(shipment, currency="EUR")
    markup_context = customer_quote_context_key(shipment, currency="EUR", markup_type="percentage")
    usd_context = customer_quote_context_key(shipment, currency="USD")
    other_lane = _shipment(delivery="France")
    other_lane_context = customer_quote_context_key(other_lane, currency="EUR")
    other_equipment = _shipment(equipment="Mega")
    other_equipment_context = customer_quote_context_key(other_equipment, currency="EUR")
    fixed_markup_context = customer_quote_context_key(shipment, currency="EUR", markup_type="fixed_profit")

    _fact(facts=facts, masters=masters, customer=customer, key=COMMERCIAL_ACCEPTED_CURRENCY_KEY,
          value="EUR", unit="currency", suffix="currency")
    _fact(facts=facts, masters=masters, customer=customer, key=QUOTE_ACCEPTANCE_RATE_KEY,
          value=60, unit="percent", suffix="acceptance")
    _fact(facts=facts, masters=masters, customer=customer, key=QUOTE_NEGOTIATION_RATE_KEY,
          value=40, unit="percent", suffix="negotiation")
    _fact(facts=facts, masters=masters, customer=customer, key=PRICE_OBJECTION_RATE_KEY,
          value=70, unit="percent", suffix="price-objection")
    _fact(facts=facts, masters=masters, customer=customer, key=TRANSIT_TIME_OBJECTION_RATE_KEY,
          value=30, unit="percent", suffix="transit-objection")
    exact_price = _fact(
        facts=facts, masters=masters, customer=customer, key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
        value=2200, unit="EUR", context=base_context, suffix="accepted-price-eur",
    )
    exact_markup = _fact(
        facts=facts, masters=masters, customer=customer, key=ACCEPTED_MARKUP_MEDIAN_KEY,
        value=11.5, unit="pricing_formula_value", context=markup_context, suffix="markup-percentage",
    )
    exact_target = _fact(
        facts=facts, masters=masters, customer=customer, key=CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
        value=2100, unit="EUR", context=base_context, suffix="target-eur",
    )
    _fact(facts=facts, masters=masters, customer=customer, key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
          value=9999, unit="USD", context=usd_context, suffix="accepted-price-usd")
    _fact(facts=facts, masters=masters, customer=customer, key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
          value=8888, unit="EUR", context=other_lane_context, suffix="accepted-price-france")
    _fact(facts=facts, masters=masters, customer=customer, key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY,
          value=7777, unit="EUR", context=other_equipment_context, suffix="accepted-price-mega")
    _fact(facts=facts, masters=masters, customer=customer, key=ACCEPTED_MARKUP_MEDIAN_KEY,
          value=500, unit="pricing_formula_value", context=fixed_markup_context, suffix="markup-fixed")
    _fact(facts=facts, masters=masters, customer=customer, key=CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
          value=6666, unit="USD", context=usd_context, suffix="target-usd")
    _fact(facts=facts, masters=masters, customer=customer, key=QUOTE_ACCEPTANCE_RATE_KEY,
          value=99, unit="percent", context=base_context, suffix="proposed-context-rate", confirm=False)

    context = build_customer_commercial_context(
        quote_case=quote_case,
        master_data_repository=masters,
        learning_fact_repository=facts,
        as_of=NOW,
    )
    check(
        context is not None and context.accepted_quote_currency_advisory.value == "EUR"
        and context.observed_acceptance_rate.value == 60
        and context.observed_negotiation_rate.value == 40
        and context.customer_stated_price_objection_rate.value == 70
        and context.customer_stated_transit_time_objection_rate.value == 30,
        "confirmed current global customer commercial metrics appear as advisory context",
    )
    check(
        context.accepted_final_price_median.value == 2200
        and context.accepted_final_price_median.fact_id == exact_price.fact_id
        and context.customer_stated_target_price_median.value == 2100
        and context.customer_stated_target_price_median.fact_id == exact_target.fact_id,
        "quote context exposes only exact shipment and currency price observations",
    )
    check(
        context.accepted_markup_median.value == 11.5
        and context.accepted_markup_median.fact_id == exact_markup.fact_id
        and context.accepted_markup_median.markup_type == "percentage",
        "accepted markup advisory requires the exact current markup context",
    )
    serialized = context.model_dump(mode="json", exclude_none=True)
    serialized_text = str(serialized)
    emitted_values = {
        metric.get("value")
        for metric in serialized.values()
        if isinstance(metric, dict) and "value" in metric
    }
    check(
        emitted_values.isdisjoint({9999, 8888, 7777, 6666, 500}),
        "different currency lane equipment and markup contexts never fall back into quote advisory",
    )
    check(
        "price_sensitivity" not in serialized and "time_sensitivity" not in serialized
        and "evidence" not in serialized_text.casefold() and RAW_SENTINEL not in serialized_text,
        "commercial context excludes manual sensitivity fields and raw learning evidence",
    )
    check(
        context.advisory_only
        and not any([
            context.pricing_authority, context.margin_authority, context.supplier_selection_authority,
            context.supplier_negotiation_authority, context.automation_authority,
            context.quote_send_authority, context.dispatch_authority,
            context.causal_explanation_created, context.win_probability_created,
            context.willingness_to_pay_created, context.current_customer_target_created,
        ]),
        "quote commercial context creates advisory-only evidence with zero commercial execution authority",
    )

    alias_case = _case(_shipment(customer_name="ACME ALT"))
    alias_context = build_customer_commercial_context(
        quote_case=alias_case, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW,
    )
    missing_context = build_customer_commercial_context(
        quote_case=_case(_shipment(customer_name="Missing Customer")),
        master_data_repository=masters, learning_fact_repository=facts, as_of=NOW,
    )
    no_quote_context = build_customer_commercial_context(
        quote_case=None, master_data_repository=masters,
        learning_fact_repository=facts, as_of=NOW,
    )
    check(alias_context is not None and missing_context is None and no_quote_context is None,
          "stable Customer Master identity is required while aliases resolve and missing quote or identity fails closed")

    ambiguous_masters = InMemoryMasterDataRepository()
    first = create_customer_master(
        repository=ambiguous_masters, entry_id="ambiguous-first", customer_name="First Customer",
        aliases=["SHARED"], updated_by="Regression", created_at=NOW - timedelta(days=5),
    )
    second = first.model_copy(update={
        "customer_id": "ambiguous-second-id", "entry_id": "ambiguous-second",
        "customer_name": "Second Customer", "aliases": ["SHARED"],
    })
    ambiguous_masters.customers[second.customer_id] = second
    ambiguous_masters.customer_by_entry[second.entry_id] = second.customer_id
    ambiguous_masters.customer_by_name[normalize_master_text(second.customer_name)] = second.customer_id
    ambiguous = build_customer_commercial_context(
        quote_case=_case(_shipment(customer_name="SHARED")),
        master_data_repository=ambiguous_masters,
        learning_fact_repository=facts, as_of=NOW,
    )
    check(ambiguous is None, "ambiguous Customer Master identity fails closed without borrowing another customer's history")

    stale_masters = InMemoryMasterDataRepository()
    stale_facts = InMemoryLearningFactRepository()
    stale_customer = create_customer_master(
        repository=stale_masters, entry_id="stale-customer", customer_name="Stale Customer",
        updated_by="Regression", created_at=NOW - timedelta(days=1000),
    )
    _fact(
        facts=stale_facts, masters=stale_masters, customer=stale_customer,
        key=PRICE_OBJECTION_RATE_KEY, value=80, unit="percent", suffix="stale-reason",
        observed_at=NOW - timedelta(days=800),
    )
    _fact(
        facts=stale_facts, masters=stale_masters, customer=stale_customer,
        key=QUOTE_ACCEPTANCE_RATE_KEY, value=90, unit="percent", suffix="unconfirmed-rate",
        observed_at=NOW - timedelta(days=2), confirm=False,
    )
    stale_context = build_customer_commercial_context(
        quote_case=_case(_shipment(customer_name="Stale Customer")),
        master_data_repository=stale_masters, learning_fact_repository=stale_facts, as_of=NOW,
    )
    check(
        stale_context is not None
        and stale_context.customer_stated_price_objection_rate is None
        and stale_context.observed_acceptance_rate is None,
        "stale confirmed and current unconfirmed facts remain outside quote commercial context",
    )

    jobs = InMemoryMinaJobRepository()
    cases = InMemoryQuoteCaseRepository()
    job, _ = jobs.create_manual(
        manual_intake_id="commercial-context-job", intake_channel="phone", job_kind="price_request",
        shipment=shipment, opened_by="Regression", opened_at=NOW - timedelta(hours=1),
        sequence_year=2026, lifecycle_version=2,
    )
    quote_case = quote_case.model_copy(update={"mina_job_id": job.job_id, "mina_code": job.mina_code})
    cases.save(quote_case)
    jobs.save(job.model_copy(update={"quote_case_id": quote_case.case_id, "updated_at": NOW - timedelta(minutes=30)}))
    detail = build_mina_job_detail(
        repository=jobs,
        supplier_repository=InMemorySupplierRFQRepository(),
        quote_case_repository=cases,
        action_repository=InMemoryAutomationActionRepository(),
        master_data_repository=masters,
        learning_fact_repository=facts,
        job_id=job.job_id,
        now=NOW,
    )
    check(
        detail["customer_commercial_context"]["accepted_final_price_median"]["value"] == 2200
        and detail["customer_commercial_context"]["advisory_only"] is True,
        "MINA job detail exposes the privacy-minimal read-only customer commercial context",
    )

    root = Path(__file__).resolve().parents[2]
    ui = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "Müşteri Ticari Bağlamı" in ui
        and "data.customer_commercial_context" in ui
        and "bu işin hedef fiyatı değildir" in ui
        and "pricing authority değildir" in ui
        and "tedarikçi pazarlık hedefi değildir" in ui,
        "quote review UI consumes commercial context while making no-pricing no-current-target boundaries visible",
    )
    supplier_and_pricing_paths = [
        root / "src" / "ai" / "supplier_rfq_generator.py",
        root / "src" / "ai" / "supplier_follow_up_generator.py",
        root / "src" / "workflow" / "mail_delivery.py",
        root / "src" / "core" / "supplier_rfq_lifecycle.py",
        root / "src" / "core" / "supplier_dispatch_control.py",
        root / "src" / "core" / "supplier_price_service.py",
        root / "src" / "core" / "pricing_policy.py",
    ]
    prohibited = ["customer_commercial_context", "customer_stated_target_price_median"]
    sources = [path.read_text(encoding="utf-8") for path in supplier_and_pricing_paths]
    check(
        all(token not in source for source in sources for token in prohibited),
        "pricing supplier RFQ dispatch negotiation and outbound generators do not consume quote commercial advisory payload",
    )

    result = {"passed": not failures, "passes": passes, "failures": failures}
    for label in passes:
        print("PASS", label)
    for label in failures:
        print("FAIL", label)
    print("\nCustomer commercial context regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    result = evaluate_customer_commercial_context_regressions()
    raise SystemExit(0 if result["passed"] else 1)
