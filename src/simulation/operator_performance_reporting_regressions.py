from __future__ import annotations

from pathlib import Path


def evaluate_operator_performance_reporting_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    root = Path(__file__).resolve().parents[2]
    model = (root / "src/core/reporting_read_model.py").read_text(encoding="utf-8")
    browser = (root / "ui/web_shell/app.js").read_text(encoding="utf-8")
    dev_ui = (root / "ui/reporting.py").read_text(encoding="utf-8")

    check(
        "assignment_assigned_at_istanbul" in model
        and "first_look_coverage_percent" in model
        and "average_first_look_seconds" in model
        and "median_first_look_seconds" in model,
        "operator performance is a backend-authoritative assignment-evidence read model",
    )
    check(
        "threshold_not_configured" in model
        and "work_type_completion_mapping_not_configured" in model
        and '"first_look_sla_percent"] = None' in model,
        "reporting refuses to invent SLA or completion authority",
    )
    check(
        "renderOperatorPerformance" in browser
        and "first_look_sla_status" in browser
        and "completion_metric_status" in browser
        and "durationLabel(summary.average_first_look_seconds)" in browser,
        "pilot browser renders backend operator-performance metrics without recomputing KPI authority",
    )
    check(
        "_render_operator_assignment_performance" in dev_ui
        and "average_first_look_seconds" in dev_ui
        and "median_first_look_seconds" in dev_ui
        and "Release/handoff workflow completion değildir." in dev_ui,
        "development reporting UI shares the same operator-performance semantics",
    )
    check(
        "first_look_sla_percent =" not in browser
        and "acknowledged_generation_count /" not in browser,
        "browser does not calculate first-look SLA or coverage independently",
    )
    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_operator_performance_reporting_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nP2-12 operator performance reporting regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
