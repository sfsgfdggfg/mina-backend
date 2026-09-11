from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.ai.supplier_rfq_generator import _selection_explanation
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact
from src.core.master_data import CustomerMasterProfile
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.models import Shipment, SupplierQuote
from src.core.quote_case import QuoteCase, SupplierDecisionOutcomeFeedback
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_customer_context import (
    resolve_customer_master_profile, supplier_customer_context_keys,
)
from src.core.supplier_intelligence_policy import (
    MAX_CUSTOMER_CONTEXT_RANKING_ADJUSTMENT,
    resolve_supplier_customer_context_learning_overlay,
)
from src.core.supplier_outcome_learning import derive_supplier_outcome_learning
from src.core.supplier_quote_selection import SupplierQuoteSelectionDecision
from src.core.supplier_selection import select_suppliers_for_shipment

NOW = datetime(2026, 9, 11, 15, 10, tzinfo=timezone.utc)


def _supplier(repo, name: str, *, role: str = "primary"):
    return create_supplier_master(
        repository=repo, entry_id=f"customer-context-supplier:{name.casefold().replace(' ', '-')}",
        supplier_name=name, role=role, reliability_score=0.7, price_score=0.7, speed_score=0.7,
        updated_by="Customer Context Regression", created_at=NOW - timedelta(days=180),
    )


def _customer(repo, entry: str, name: str, aliases=()):
    profile = CustomerMasterProfile(
        entry_id=entry, customer_name=name, aliases=list(aliases),
        created_at=NOW - timedelta(days=180), updated_at=NOW - timedelta(days=1),
        updated_by="Customer Context Regression",
    )
    return repo.create_customer(profile)[0]


def _case(repo, *, index: int, customer_name: str, selected: str, good: bool, country: str = "Germany"):
    shipment = Shipment(
        customer_name=customer_name, transport_mode="road", pickup_country="Türkiye",
        delivery_country=country, service_type="FTL", equipment_type="Tenteli",
        required_delivery_date="2026-09-20",
    )
    decision = SupplierQuoteSelectionDecision(
        selected_supplier=selected, engine_recommended_supplier=selected,
        selected_total_score=0.80, selection_reason="Customer-context regression selection.",
        rejected_alternatives=[],
    )
    case = QuoteCase(
        shipment=shipment, mina_job_id=f"customer-job-{index}", mina_code=f"MINA2026/{500+index}",
        supplier_quote_selection_decision=decision,
        supplier_quote=SupplierQuote(supplier_name=selected, cost=2200, currency="EUR"),
    )
    age_days = max(1, 20 - index)
    feedback = SupplierDecisionOutcomeFeedback(
        entry_id=f"customer-outcome-{index}", job_id=case.mina_job_id, case_id=case.case_id,
        supplier_name=selected, engine_recommended_supplier=selected,
        overall_outcome="successful" if good else "problematic",
        communication_quality="good" if good else "poor",
        would_choose_again="yes" if good else "no",
        delivered_at=NOW - timedelta(days=age_days), required_delivery_date="2026-09-20",
        on_time_delivery=good, operation_exception_count=0 if good else 2,
        actual_delay_count=0 if good else 1, damage_exception_count=0 if good else 1,
        operation_exception_ids=[] if good else [f"delay-{index}", f"damage-{index}"],
        operation_snapshot_updated_at=NOW - timedelta(days=age_days, minutes=5),
        recorded_by="Customer Context Regression", recorded_at=NOW - timedelta(days=age_days),
    )
    repo.save(case.model_copy(update={"supplier_decision_outcome_feedback": feedback}))


def _capabilities(*suppliers):
    return [{
        "supplier_name": s.supplier_name, "role": s.role,
        "countries": ["Germany", "France"], "route_regions": ["international"],
        "service_types": ["FTL"], "equipment_types": ["Tenteli"],
        "reliability_score": s.reliability_score, "price_score": s.price_score,
        "speed_score": s.speed_score, "notes": "customer-context regression",
    } for s in suppliers]


def evaluate_customer_specific_supplier_learning_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    acme = _customer(masters, "customer-acme", "Acme", aliases=["ACME Logistics"])
    beta = _customer(masters, "customer-beta", "Beta")
    supplier = _supplier(masters, "Customer Context Primary")
    plain = _supplier(masters, "Plain Primary")
    backup = _supplier(masters, "Customer Context Backup", role="backup")
    facts = InMemoryLearningFactRepository(); cases = InMemoryQuoteCaseRepository()

    alias_match = resolve_customer_master_profile(
        customer_name="ACME Logistics", master_repository=masters,
    )
    check(alias_match is not None and alias_match.customer_id == acme.customer_id,
          "customer aliases resolve to one stable Customer Master identity")
    ambiguous_repo = InMemoryMasterDataRepository()
    _customer(ambiguous_repo, "ambiguous-a", "Ambiguous A", aliases=["Shared Alias"])
    _customer(ambiguous_repo, "ambiguous-b", "Ambiguous B", aliases=["Shared Alias"])
    check(
        resolve_customer_master_profile(
            customer_name="Shared Alias", master_repository=ambiguous_repo,
        ) is None,
        "ambiguous customer aliases fail closed instead of choosing an arbitrary customer scope",
    )

    for i in range(1, 8):
        _case(cases, index=i, customer_name="ACME Logistics", selected=supplier.supplier_name, good=True)
    for i in range(11, 18):
        _case(cases, index=i, customer_name="Beta", selected=supplier.supplier_name, good=False)

    derived = derive_supplier_outcome_learning(
        supplier_id=supplier.supplier_id, master_repository=masters,
        quote_case_repository=cases, learning_repository=facts,
        created_by="Customer Context Regression", occurred_at=NOW,
    )
    acme_context = supplier_customer_context_keys(
        Shipment(customer_name="Acme", transport_mode="road", pickup_country="Türkiye",
                 delivery_country="Germany", equipment_type="Tenteli"),
        customer_id=acme.customer_id,
    )[0]
    beta_context = supplier_customer_context_keys(
        Shipment(customer_name="Beta", transport_mode="road", pickup_country="Türkiye",
                 delivery_country="Germany", equipment_type="Tenteli"),
        customer_id=beta.customer_id,
    )[0]
    acme_facts = [f for f in facts.list_all() if f.context_key == acme_context]
    beta_facts = [f for f in facts.list_all() if f.context_key == beta_context]
    check(
        derived["customer_contextual_proposed_fact_count"] == 20
        and len(acme_facts) == 5 and len(beta_facts) == 5
        and all(f.status == "proposed" and f.confidence == 0.86 for f in acme_facts + beta_facts),
        "seven selected-supplier outcomes per customer create separate reviewed customer-context proposals",
    )
    check(
        next(f for f in acme_facts if f.fact_key == "operation.on_time_delivery_rate_percent").value == 100.0
        and next(f for f in beta_facts if f.fact_key == "operation.on_time_delivery_rate_percent").value == 0.0
        and next(f for f in acme_facts if f.fact_key == "operation.choose_again_rate_percent").value == 100.0
        and next(f for f in beta_facts if f.fact_key == "operation.choose_again_rate_percent").value == 0.0,
        "the same supplier may carry opposite observed outcome evidence for different customers",
    )

    for fact in acme_facts + beta_facts:
        confirm_learning_fact(
            repository=facts, fact_id=fact.fact_id, reviewed_by="Customer Context Reviewer",
            review_note="Confirm customer-specific supplier outcome evidence.",
            occurred_at=NOW + timedelta(minutes=1),
        )
    acme_overlay = resolve_supplier_customer_context_learning_overlay(
        supplier_name=supplier.supplier_name, context_key=acme_context,
        master_data_repository=masters, learning_repository=facts, as_of=NOW + timedelta(minutes=2),
    )
    beta_overlay = resolve_supplier_customer_context_learning_overlay(
        supplier_name=supplier.supplier_name, context_key=beta_context,
        master_data_repository=masters, learning_repository=facts, as_of=NOW + timedelta(minutes=2),
    )
    check(
        acme_overlay is not None and 0 < acme_overlay.ranking_adjustment <= MAX_CUSTOMER_CONTEXT_RANKING_ADJUSTMENT
        and beta_overlay is not None and -MAX_CUSTOMER_CONTEXT_RANKING_ADJUSTMENT <= beta_overlay.ranking_adjustment < 0,
        "confirmed customer-context outcomes have a smaller independently capped ranking overlay",
    )

    capabilities = _capabilities(supplier, plain, backup)
    acme_selection = select_suppliers_for_shipment(
        Shipment(customer_name="ACME Logistics", transport_mode="road", pickup_country="Türkiye",
                 delivery_country="Germany", service_type="FTL", equipment_type="Tenteli"),
        equipment_decision={"selected_equipment":"Tenteli"}, risk_assessment={"risk_level":"green"},
        supplier_capabilities=capabilities, master_data_repository=masters,
        learning_fact_repository=facts, policy_as_of=NOW + timedelta(minutes=2),
    )["selected_suppliers"]
    beta_selection = select_suppliers_for_shipment(
        Shipment(customer_name="Beta", transport_mode="road", pickup_country="Türkiye",
                 delivery_country="Germany", service_type="FTL", equipment_type="Tenteli"),
        equipment_decision={"selected_equipment":"Tenteli"}, risk_assessment={"risk_level":"green"},
        supplier_capabilities=capabilities, master_data_repository=masters,
        learning_fact_repository=facts, policy_as_of=NOW + timedelta(minutes=2),
    )["selected_suppliers"]
    acme_supplier = next(x for x in acme_selection if x["supplier_name"] == supplier.supplier_name)
    beta_supplier = next(x for x in beta_selection if x["supplier_name"] == supplier.supplier_name)
    check(
        acme_supplier["customer_context_learning_adjustment"] > 0
        and acme_supplier["customer_learning_context_key"] == acme_context
        and beta_supplier["customer_context_learning_adjustment"] < 0
        and beta_supplier["customer_learning_context_key"] == beta_context,
        "selection applies only the matched customer's reviewed context and keeps customer scopes isolated",
    )
    check(
        acme_selection[-1]["supplier_name"] == backup.supplier_name
        and acme_selection[-1]["dispatch_tier"] == "secondary"
        and beta_selection[-1]["supplier_name"] == backup.supplier_name
        and beta_selection[-1]["dispatch_tier"] == "secondary",
        "customer-specific learning cannot cross the primary-secondary dispatch boundary",
    )

    unmatched = select_suppliers_for_shipment(
        Shipment(customer_name="Unknown Customer", transport_mode="road", pickup_country="Türkiye",
                 delivery_country="Germany", service_type="FTL", equipment_type="Tenteli"),
        equipment_decision={"selected_equipment":"Tenteli"}, risk_assessment={"risk_level":"green"},
        supplier_capabilities=capabilities, master_data_repository=masters,
        learning_fact_repository=facts, policy_as_of=NOW + timedelta(minutes=2),
    )["selected_suppliers"]
    unmatched_supplier = next(x for x in unmatched if x["supplier_name"] == supplier.supplier_name)
    check(
        unmatched_supplier["customer_context_learning_adjustment"] == 0
        and unmatched_supplier["customer_learning_context_key"] is None,
        "unmatched customer identity fails closed instead of borrowing another customer's supplier history",
    )

    snap = _selection_explanation(
        acme_supplier, {"selection_strategy":"regression", "data_source":"synthetic"}
    )
    check(
        snap is not None and snap.customer_context_learning_adjustment > 0
        and snap.customer_learning_context_key == acme_context
        and len(snap.customer_context_learning_fact_ids) > 0,
        "durable supplier-selection snapshot preserves customer-context ranking provenance",
    )

    ui = Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        "müşteri bağlamı" in ui and "customer_context_learning_fact_ids" in ui,
        "browser selection explanation exposes customer-specific learning separately",
    )

    result={"passes":passes,"failures":failures,"passed":not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nCustomer-specific supplier learning regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    result=evaluate_customer_specific_supplier_learning_regressions()
    raise SystemExit(0 if result["passed"] else 1)
