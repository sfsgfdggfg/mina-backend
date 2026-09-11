from __future__ import annotations

from pathlib import Path
from src.core.supplier_quote_comparison import SupplierQuoteComparison
from src.core.supplier_quote_selection import build_supplier_quote_selection_decision
from src.core.pilot_access import route_allowed


def _cmp(name: str, score: float, cost: float, *, eligible: bool = True):
    return SupplierQuoteComparison(
        rfq_id=f"rfq-{name}", supplier_name=name, priority=1,
        cost=cost, currency="EUR", transit_time="5-7 days", transit_days=7,
        commercial_eligible=eligible, commercial_rejection_reasons=[] if eligible else ["blocked"],
        supplier_score=0.8, commercial_score=0.8, operational_score=0.8,
        actual_price_score=0.8, transit_score=0.8, total_score=score,
    )


def evaluate_supplier_selection_override_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)
    comparisons=[_cmp("Alpha",0.91,2500),_cmp("Beta",0.83,2350),_cmp("Blocked",0.95,2200,eligible=False)]
    normal=build_supplier_quote_selection_decision(comparisons)
    check(normal.selected_supplier=="Alpha" and normal.engine_recommended_supplier=="Alpha" and not normal.override_applied, "normal supplier quote selection preserves engine recommendation without override evidence")
    overridden=build_supplier_quote_selection_decision(comparisons,override_supplier_name="Beta",override_reason="Customer relationship requires Beta.",override_reason_category="relationship_loyalty",overridden_by="Ops User")
    check(overridden.selected_supplier=="Beta" and overridden.engine_recommended_supplier=="Alpha" and overridden.override_applied and overridden.override_reason=="Customer relationship requires Beta." and overridden.override_reason_category=="relationship_loyalty" and overridden.overridden_by=="Ops User" and "MINAI Alpha" in overridden.selection_reason, "human override selects an eligible alternative while preserving engine recommendation and reason evidence")
    try:
        build_supplier_quote_selection_decision(comparisons,override_supplier_name="Beta",overridden_by="Ops User")
        missing_reason=False
    except ValueError: missing_reason=True
    check(missing_reason,"supplier selection override fails closed without a human reason")
    try:
        build_supplier_quote_selection_decision(comparisons,override_supplier_name="Beta",override_reason="Relationship",overridden_by="Ops User")
        missing_category=False
    except ValueError: missing_category=True
    check(missing_category,"supplier selection override fails closed without a structured reason category")
    try:
        build_supplier_quote_selection_decision(comparisons,override_supplier_name="Blocked",override_reason="Try blocked",override_reason_category="other",overridden_by="Ops User")
        blocked=False
    except ValueError: blocked=True
    check(blocked,"supplier selection override cannot target a commercially ineligible quote")
    check(route_allowed("POST","/mina-jobs/job-1/supplier-prices/progress"),"controlled pilot keeps supplier quote progression as the only override mutation surface")
    ui=Path("ui/web_shell/app.js").read_text(encoding="utf-8")
    check("supplier_selection_override_name" in ui and "Supplier seçimi operatör tarafından değiştirildi" in ui,"browser exposes explicit supplier override input and resulting audit evidence")
    result={"passes":passes,"failures":failures,"passed":not failures}
    for label in passes: print(f"PASS {label}")
    for label in failures: print(f"FAIL {label}")
    print("\nSupplier selection override evidence regressions:","PASS" if not failures else "FAIL")
    return result

if __name__=="__main__":
    outcome=evaluate_supplier_selection_override_regressions(); raise SystemExit(0 if outcome["passed"] else 1)
