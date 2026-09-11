from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from src.core.mina_job import MinaJob
from src.core.quote_case import SupplierDecisionOutcomeFeedback
from src.core.reporting_read_model import build_reporting_read_model, reporting_section
from src.core.supplier_quote_selection import SupplierQuoteSelectionDecision
from src.simulation.reporting_read_model_regressions import NOW, _build_fixture


def _decision(*, selected: str, engine: str, override: bool, category=None, actor=None, score=0.9, score_delta=None, price_delta=None):
    return SupplierQuoteSelectionDecision(
        selected_supplier=selected,
        engine_recommended_supplier=engine,
        override_applied=override,
        override_reason=("Operational experience favored selected supplier." if override else None),
        override_reason_category=category,
        overridden_by=actor,
        selected_total_score=score,
        selection_reason="Regression decision evidence.",
        price_difference=price_delta,
        score_difference=score_delta,
        rejected_alternatives=[],
    )


def _feedback(*, job, case, supplier: str, engine: str, override: bool, category, outcome: str, on_time: bool, choose_again: str, delay_count: int, damage_count: int, recorded_by: str):
    return SupplierDecisionOutcomeFeedback(
        entry_id=f"outcome-{job.mina_code}",
        job_id=job.job_id,
        case_id=case.case_id,
        supplier_name=supplier,
        engine_recommended_supplier=engine,
        override_applied=override,
        override_reason_category=category,
        overall_outcome=outcome,
        communication_quality=("good" if outcome == "successful" else "poor"),
        would_choose_again=choose_again,
        delivered_at=NOW + timedelta(hours=32),
        required_delivery_date=job.shipment.required_delivery_date,
        on_time_delivery=on_time,
        operation_exception_count=max(delay_count, damage_count),
        actual_delay_count=delay_count,
        damage_exception_count=damage_count,
        operation_exception_ids=[],
        operation_snapshot_updated_at=NOW + timedelta(hours=35),
        recorded_by=recorded_by,
        recorded_at=NOW + timedelta(hours=41),
    )


def evaluate_operator_vs_minai_decision_analytics_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    jobs, quotes, rfqs, prices, operations, masters, learning, fixture_jobs = _build_fixture()
    job1, _, job3, _ = fixture_jobs
    job1 = jobs.get(job1.job_id)
    job3 = jobs.get(job3.job_id)
    assert job1 is not None and job3 is not None
    case1 = quotes.get(job1.quote_case_id)
    case3 = quotes.get(job3.quote_case_id)
    assert case1 is not None and case3 is not None

    case1 = case1.model_copy(update={
        "supplier_quote_selection_decision": _decision(
            selected="Carrier A", engine="Carrier A", override=False,
        ),
    })
    case1 = case1.model_copy(update={
        "supplier_decision_outcome_feedback": _feedback(
            job=job1, case=case1, supplier="Carrier A", engine="Carrier A",
            override=False, category=None, outcome="successful", on_time=True,
            choose_again="yes", delay_count=0, damage_count=0, recorded_by="Ozan",
        ),
    })
    quotes.save(case1)

    completed_job3 = MinaJob.model_validate(job3.model_copy(update={
        "stage": "completed",
        "closed_at": NOW + timedelta(hours=30),
        "updated_at": NOW + timedelta(hours=30),
    }).model_dump())
    jobs.save(completed_job3)
    case3 = case3.model_copy(update={
        "supplier_quote_selection_decision": _decision(
            selected="Carrier A", engine="Carrier B", override=True,
            category="operational_experience", actor="Ozan",
            score=0.82, score_delta=-0.08, price_delta=-100.0,
        ),
    })
    case3 = case3.model_copy(update={
        "supplier_decision_outcome_feedback": _feedback(
            job=completed_job3, case=case3, supplier="Carrier A", engine="Carrier B",
            override=True, category="operational_experience", outcome="problematic",
            on_time=False, choose_again="no", delay_count=1, damage_count=1,
            recorded_by="Ozan",
        ),
    })
    quotes.save(case3)

    report = build_reporting_read_model(
        mina_repository=jobs, quote_case_repository=quotes,
        supplier_rfq_repository=rfqs, supplier_price_repository=prices,
        operation_execution_repository=operations, master_data_repository=masters,
        learning_fact_repository=learning,
        start_date=date(2026, 9, 4), end_date=date(2026, 9, 4),
        as_of=NOW + timedelta(days=1),
    )
    analytics = report["decision_analytics"]
    summary = analytics["summary"]
    check(
        summary["analyzable_decision_count"] == 2
        and summary["recommendation_followed_count"] == 1
        and summary["override_count"] == 1
        and summary["override_rate_percent"] == 50.0
        and summary["outcome_feedback_coverage_percent"] == 100.0,
        "decision analytics separates followed and override cohorts with evidence coverage",
    )
    followed = analytics["cohorts"]["recommendation_followed"]
    overridden = analytics["cohorts"]["operator_override"]
    check(
        followed["successful_outcome_percent"] == 100.0
        and followed["problematic_outcome_percent"] == 0.0
        and overridden["successful_outcome_percent"] == 0.0
        and overridden["problematic_outcome_percent"] == 100.0,
        "cohort outcomes describe only the supplier decision actually observed",
    )
    check(
        overridden["selected_minus_engine_score_delta"]["average"] == -0.08
        and overridden["selected_minus_engine_price_delta_by_currency"]["EUR"]["average"] == -100.0,
        "override deltas preserve selected-minus-engine score and same-currency price evidence",
    )
    category = next(row for row in analytics["override_categories"] if row["category"] == "operational_experience")
    check(
        category["decision_count"] == 1 and category["problematic_outcome_percent"] == 100.0,
        "override reason categories retain observed decision outcomes without becoming learning",
    )
    austria = next(row for row in analytics["contexts"] if "Austria" in row["route"])
    germany = next(row for row in analytics["contexts"] if "Germany" in row["route"])
    check(
        austria["override_rate_percent"] == 100.0
        and germany["override_rate_percent"] == 0.0,
        "decision analytics exposes lane and equipment context without leaking across contexts",
    )
    carrier_b = next(row for row in analytics["recommended_suppliers"] if row["name"] == "Carrier B")
    check(
        carrier_b["overridden_away_count"] == 1
        and carrier_b["override_away_rate_percent"] == 100.0
        and carrier_b["followed_observed_outcomes"]["outcome_feedback_count"] == 0,
        "override outcome is never attributed counterfactually to the MINAI supplier that was not selected",
    )
    operator = next(row for row in analytics["override_operators"] if row["name"] == "Ozan")
    check(
        operator["decision_count"] == 1
        and operator["override_rate_percent"] is None
        and operator["rate_denominator_status"] == "normal_selection_operator_identity_not_persisted",
        "operator analytics refuses to invent an override-rate denominator or personnel score",
    )
    check(
        analytics["counterfactual_outcomes_inferred"] is False
        and analytics["learning_authority_created"] is False
        and analytics["operator_performance_score_created"] is False,
        "decision analytics remains descriptive and creates no learning or personnel authority",
    )
    check(
        reporting_section(report, "decision_analytics")["decision_analytics"] == analytics,
        "decision analytics is exposed through the canonical reporting section API",
    )
    ui = Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check(
        "MINAI vs Operatör Supplier Kararları" in ui
        and "seçilmeyen alternatif için varsayımsal sonuç üretilmez" in ui,
        "browser reports make the non-counterfactual analytics boundary visible",
    )

    result={"passes":passes,"failures":failures,"passed":not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nOperator vs MINAI decision analytics regressions:","PASS" if not failures else "FAIL")
    return result


if __name__ == "__main__":
    outcome=evaluate_operator_vs_minai_decision_analytics_regressions()
    raise SystemExit(0 if outcome["passed"] else 1)
