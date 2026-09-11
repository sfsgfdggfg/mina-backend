from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import InMemoryLearningFactRepository
from src.core.learning_fact_service import confirm_learning_fact, create_learning_fact
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.master_data_service import create_supplier_master
from src.core.models import Shipment, SupplierQuote
from src.core.quote_case import QuoteCase, SupplierDecisionOutcomeFeedback
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.supplier_intelligence_policy import (
    build_supplier_operational_learning_policy,
    resolve_supplier_contextual_learning_overlay,
)
from src.core.supplier_outcome_learning import (
    OUTCOME_MIN_SAMPLE_COUNT,
    derive_supplier_outcome_learning,
)
from src.core.supplier_learning_service import derive_supplier_history_learning
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository
from src.core.supplier_quote_selection import SupplierQuoteSelectionDecision
from src.core.supplier_selection import select_suppliers_for_shipment

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _supplier(repo, name: str, *, role: str = "primary"):
    return create_supplier_master(
        repository=repo,
        entry_id=f"outcome-supplier:{name.casefold().replace(' ', '-')}",
        supplier_name=name,
        role=role,
        reliability_score=0.7,
        price_score=0.7,
        speed_score=0.7,
        updated_by="Outcome Learning Regression",
        created_at=NOW - timedelta(days=120),
    )


def _case(
    repo, *, index: int, selected: str, engine: str, country: str = "Germany",
    on_time: bool | None = True, problematic: bool = False, actual_delay_count: int = 0,
    damage_count: int = 0, choose_again: str = "yes",
):
    shipment = Shipment(
        customer_name=f"Synthetic {index}", transport_mode="road",
        pickup_country="Türkiye", delivery_country=country,
        service_type="FTL", equipment_type="Tenteli",
        required_delivery_date="2026-09-20" if on_time is not None else None,
    )
    override = selected != engine
    decision = SupplierQuoteSelectionDecision(
        selected_supplier=selected,
        engine_recommended_supplier=engine,
        override_applied=override,
        override_reason="Synthetic operator evidence." if override else None,
        override_reason_category="operational_experience" if override else None,
        overridden_by="Regression Operator" if override else None,
        selected_total_score=0.80 if override else 0.92,
        selection_reason="Synthetic selection evidence.",
        rejected_alternatives=[],
    )
    case = QuoteCase(
        shipment=shipment,
        mina_job_id=f"job-{index}",
        mina_code=f"MINA2026/{index}",
        supplier_quote_selection_decision=decision,
        supplier_quote=SupplierQuote(supplier_name=selected, cost=2200, currency="EUR"),
    )
    feedback = SupplierDecisionOutcomeFeedback(
        entry_id=f"outcome-{index}",
        job_id=f"job-{index}", case_id=case.case_id,
        supplier_name=selected, engine_recommended_supplier=engine,
        override_applied=override,
        override_reason_category="operational_experience" if override else None,
        overall_outcome="problematic" if problematic else "successful",
        communication_quality="good" if not problematic else "acceptable",
        would_choose_again=choose_again,
        delivered_at=NOW - timedelta(days=8-index),
        required_delivery_date=shipment.required_delivery_date,
        on_time_delivery=on_time,
        operation_exception_count=actual_delay_count + damage_count,
        actual_delay_count=actual_delay_count,
        damage_exception_count=damage_count,
        operation_exception_ids=[f"incident-{index}-{n}" for n in range(actual_delay_count + damage_count)],
        operation_snapshot_updated_at=NOW - timedelta(days=8-index, minutes=10),
        recorded_by="Regression Operator",
        recorded_at=NOW - timedelta(days=8-index),
    )
    repo.save(case.model_copy(update={"supplier_decision_outcome_feedback": feedback}))


def _capabilities(*suppliers):
    return [
        {
            "supplier_name": supplier.supplier_name,
            "role": supplier.role,
            "countries": ["Germany", "France"],
            "route_regions": ["international"],
            "service_types": ["FTL"],
            "equipment_types": ["Tenteli"],
            "reliability_score": supplier.reliability_score,
            "price_score": supplier.price_score,
            "speed_score": supplier.speed_score,
            "notes": "outcome-learning regression",
        }
        for supplier in suppliers
    ]


def evaluate_supplier_outcome_learning_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    masters = InMemoryMasterDataRepository()
    primary = _supplier(masters, "Outcome Primary")
    unselected = _supplier(masters, "Unselected Recommendation")
    backup = _supplier(masters, "Outcome Backup", role="backup")
    facts = InMemoryLearningFactRepository()
    cases = InMemoryQuoteCaseRepository()

    for index in range(1, OUTCOME_MIN_SAMPLE_COUNT):
        _case(cases, index=index, selected=primary.supplier_name, engine=unselected.supplier_name)
    thin = derive_supplier_outcome_learning(
        supplier_id=primary.supplier_id, master_repository=masters,
        quote_case_repository=cases, learning_repository=facts,
        created_by="Outcome Learning Regression", occurred_at=NOW,
    )
    check(
        thin["outcome_feedback_count"] == 4 and thin["proposed_fact_count"] == 0
        and thin["contextual_proposed_fact_count"] == 0,
        "fewer than five completed supplier outcomes cannot create learning proposals",
    )

    _case(
        cases, index=5, selected=primary.supplier_name, engine=unselected.supplier_name,
        problematic=True, actual_delay_count=3, damage_count=2, choose_again="no",
    )
    five = derive_supplier_outcome_learning(
        supplier_id=primary.supplier_id, master_repository=masters,
        quote_case_repository=cases, learning_repository=facts,
        created_by="Outcome Learning Regression", occurred_at=NOW + timedelta(minutes=1),
    )
    global_facts = [item for item in facts.list_all() if item.context_key is None]
    by_key = {item.fact_key: item for item in global_facts}
    check(
        five["outcome_feedback_count"] == 5 and five["proposed_fact_count"] == 5
        and by_key["operation.actual_delay_rate_percent"].value == 20.0
        and by_key["operation.damage_incident_rate_percent"].value == 20.0
        and by_key["operation.problematic_outcome_rate_percent"].value == 20.0
        and by_key["operation.choose_again_rate_percent"].value == 80.0
        and by_key["operation.on_time_delivery_rate_percent"].value == 100.0,
        "five final outcomes derive job-level rates with real denominators instead of incident-count inflation",
    )
    check(
        all(item.confidence == 0.78 for item in global_facts)
        and all(item.status == "proposed" for item in global_facts),
        "minimum-sample outcome facts remain low-confidence proposed observations",
    )

    global_on_time = by_key["operation.on_time_delivery_rate_percent"]
    exact_context = "mode=road|lane=turkiye>germany|equipment=tenteli"
    context_on_time = next(
        item for item in facts.list_all()
        if item.context_key == exact_context
        and item.fact_key == "operation.on_time_delivery_rate_percent"
    )
    confirm_learning_fact(
        repository=facts, fact_id=global_on_time.fact_id,
        reviewed_by="Reviewer", review_note="Review five-sample outcome fact.",
        occurred_at=NOW + timedelta(minutes=2),
    )
    confirm_learning_fact(
        repository=facts, fact_id=context_on_time.fact_id,
        reviewed_by="Reviewer", review_note="Review five-sample contextual outcome fact.",
        occurred_at=NOW + timedelta(minutes=2),
    )
    low_policy = build_supplier_operational_learning_policy(
        supplier=primary, learning_repository=facts,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120,
        as_of=NOW + timedelta(minutes=3),
    )
    low_overlay = resolve_supplier_contextual_learning_overlay(
        supplier_name=primary.supplier_name, context_key=exact_context,
        master_data_repository=masters, learning_repository=facts,
        as_of=NOW + timedelta(minutes=3),
    )
    check(
        low_policy.ranking_adjustment == 0
        and low_policy.effective_first_reminder_minutes == 30
        and low_policy.effective_acknowledged_wait_minutes == 120
        and low_overlay is not None and low_overlay.ranking_adjustment == 0,
        "human confirmation at five samples still cannot cross the higher outcome runtime-confidence threshold",
    )

    _case(cases, index=6, selected=primary.supplier_name, engine=primary.supplier_name)
    _case(cases, index=7, selected=primary.supplier_name, engine=primary.supplier_name)
    seven = derive_supplier_outcome_learning(
        supplier_id=primary.supplier_id, master_repository=masters,
        quote_case_repository=cases, learning_repository=facts,
        created_by="Outcome Learning Regression", occurred_at=NOW + timedelta(minutes=4),
    )
    global_replacement = next(
        item for item in facts.list_all()
        if item.status == "proposed" and item.context_key is None
        and item.fact_key == "operation.on_time_delivery_rate_percent"
        and item.supersedes_fact_id == global_on_time.fact_id
    )
    context_replacement = next(
        item for item in facts.list_all()
        if item.status == "proposed" and item.context_key == exact_context
        and item.fact_key == "operation.on_time_delivery_rate_percent"
        and item.supersedes_fact_id == context_on_time.fact_id
    )
    check(
        seven["outcome_feedback_count"] == 7
        and global_replacement.confidence == 0.86 and context_replacement.confidence == 0.86,
        "seven recent outcomes create explicit higher-confidence replacements instead of overwriting reviewed history",
    )
    confirm_learning_fact(
        repository=facts, fact_id=global_replacement.fact_id,
        reviewed_by="Reviewer", review_note="Confirm higher-sample global outcome replacement.",
        occurred_at=NOW + timedelta(minutes=5),
    )
    confirm_learning_fact(
        repository=facts, fact_id=context_replacement.fact_id,
        reviewed_by="Reviewer", review_note="Confirm higher-sample contextual outcome replacement.",
        occurred_at=NOW + timedelta(minutes=5),
    )
    high_policy = build_supplier_operational_learning_policy(
        supplier=primary, learning_repository=facts,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120,
        as_of=NOW + timedelta(minutes=6),
    )
    high_overlay = resolve_supplier_contextual_learning_overlay(
        supplier_name=primary.supplier_name, context_key=exact_context,
        master_data_repository=masters, learning_repository=facts,
        as_of=NOW + timedelta(minutes=6),
    )
    check(
        0 < high_policy.ranking_adjustment <= 0.06
        and high_policy.effective_first_reminder_minutes == 30
        and high_policy.effective_acknowledged_wait_minutes == 120
        and high_overlay is not None and 0 < high_overlay.ranking_adjustment <= 0.04,
        "reviewed sufficiently confident outcome history affects only bounded ranking and never supplier timing",
    )

    france_overlay = resolve_supplier_contextual_learning_overlay(
        supplier_name=primary.supplier_name,
        context_key="mode=road|lane=turkiye>france|equipment=tenteli",
        master_data_repository=masters, learning_repository=facts,
        as_of=NOW + timedelta(minutes=6),
    )
    check(
        france_overlay is not None and france_overlay.ranking_adjustment == 0,
        "outcome learning remains lane-and-equipment bound and does not leak into unrelated context",
    )

    unselected_result = derive_supplier_outcome_learning(
        supplier_id=unselected.supplier_id, master_repository=masters,
        quote_case_repository=cases, learning_repository=facts,
        created_by="Outcome Learning Regression", occurred_at=NOW + timedelta(minutes=7),
    )
    check(
        unselected_result["outcome_feedback_count"] == 0
        and unselected_result["proposed_fact_count"] == 0,
        "an overridden-away MINAI recommendation receives no counterfactual supplier outcome learning",
    )

    selection = select_suppliers_for_shipment(
        Shipment(
            customer_name="Synthetic", transport_mode="road", pickup_country="Türkiye",
            delivery_country="Germany", service_type="FTL", equipment_type="Tenteli",
        ),
        equipment_decision={"selected_equipment": "Tenteli"},
        risk_assessment={"risk_level": "green"},
        supplier_capabilities=_capabilities(primary, backup),
        master_data_repository=masters, learning_fact_repository=facts,
        policy_as_of=NOW + timedelta(minutes=6),
    )["selected_suppliers"]
    check(
        selection[0]["supplier_name"] == primary.supplier_name
        and selection[-1]["supplier_name"] == backup.supplier_name
        and selection[-1]["dispatch_tier"] == "secondary",
        "outcome-informed ranking cannot promote a backup supplier across the primary-secondary dispatch boundary",
    )

    stale_supplier = _supplier(masters, "Stale Outcome")
    stale_fact = create_learning_fact(
        repository=facts, entry_id="stale-outcome-learning",
        subject_type="supplier", subject_id=stale_supplier.supplier_id,
        subject_label=stale_supplier.supplier_name,
        fact_key="operation.on_time_delivery_rate_percent", value=100,
        value_unit="percent", confidence=0.99, source_type="operation_history",
        evidence=[LearningEvidence(
            source_type="operation_history", source_reference="stale-outcome-evidence",
            observed_at=NOW - timedelta(days=800),
            summary="Stale selected-supplier outcome evidence.",
        )], created_by="Outcome Learning Regression",
        occurred_at=NOW - timedelta(days=800), master_repository=masters,
    )
    confirm_learning_fact(
        repository=facts, fact_id=stale_fact.fact_id,
        reviewed_by="Reviewer", review_note="Review stale outcome metric.",
        occurred_at=NOW - timedelta(days=799),
    )
    stale_policy = build_supplier_operational_learning_policy(
        supplier=stale_supplier, learning_repository=facts,
        base_first_reminder_minutes=30, base_acknowledged_wait_minutes=120, as_of=NOW,
    )
    check(
        stale_policy.ranking_adjustment == 0
        and stale_policy.evaluations[0].reason == "evidence_too_old_for_runtime_effect",
        "stale outcome evidence decays out of runtime ranking authority",
    )

    ui = Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        "outcome öğrenmesi en az 5 kayıt ister" in ui
        and not any(item.fact_key.startswith("operation.") and item.status == "confirmed" for item in facts.list_all() if item.subject_id == unselected.supplier_id),
        "browser explains the outcome sample gate while unselected suppliers receive no hidden authority",
    )

    integrated_supplier = _supplier(masters, "Integrated Outcome")
    integrated_cases = InMemoryQuoteCaseRepository()
    integrated_facts = InMemoryLearningFactRepository()
    for index in range(20, 25):
        _case(
            integrated_cases, index=index, selected=integrated_supplier.supplier_name,
            engine=integrated_supplier.supplier_name,
        )
    integrated = derive_supplier_history_learning(
        supplier_id=integrated_supplier.supplier_id, master_repository=masters,
        supplier_repository=InMemorySupplierRFQRepository(),
        learning_repository=integrated_facts, quote_case_repository=integrated_cases,
        created_by="Outcome Learning Regression", occurred_at=NOW + timedelta(minutes=8),
    )
    check(
        integrated["outcome_learning"]["outcome_feedback_count"] == 5
        and integrated["outcome_learning"]["proposed_fact_count"] == 5
        and all(item.status == "proposed" for item in integrated_facts.list_all()),
        "canonical supplier history derivation includes outcome learning without bypassing human review",
    )

    result = {"passes": passes, "failures": failures, "passed": not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier outcome-informed learning regressions:", "PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome = evaluate_supplier_outcome_learning_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
