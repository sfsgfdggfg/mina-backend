from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "ui" / "app.py"
REPORTING = ROOT / "ui" / "reporting.py"


def evaluate_reporting_ui_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str):
        (passes if condition else failures).append(label)

    app_text = APP.read_text(encoding="utf-8")
    reporting_text = REPORTING.read_text(encoding="utf-8")
    try:
        ast.parse(app_text)
        ast.parse(reporting_text)
        syntax_ok = True
    except SyntaxError:
        syntax_ok = False
    check(syntax_ok, "reporting UI sources parse as Python")
    check(
        "from ui.reporting import render_reporting" in app_text
        and '["MINA İşleri", "Yeni Talep", "Raporlar", "Veri & Rehber"]' in app_text
        and 'elif page == "Raporlar"' in app_text,
        "Raporlar is a first-class Freight OS workspace",
    )
    check(
        'f"{api_base_url}/reports"' in reporting_text
        and 'params["start_date"]' in reporting_text
        and 'params["end_date"]' in reporting_text
        and "report_all_period" in reporting_text,
        "reporting UI reads one backend-authoritative report with explicit period filters",
    )
    check(
        all(label in reporting_text for label in (
            '"Genel"', '"Satış"', '"Operasyon"', '"Müşteriler"', '"Tedarikçiler"',
            '"Rotalar"', '"Finansal"', '"MINAI"', '"İstisnalar"', '"Veri Kalitesi"',
        )),
        "reporting UI exposes all agreed reporting modules",
    )
    check(
        "financial_coverage_percent" in reporting_text
        and "uncovered_job_count" in reporting_text
        and "by_currency" in reporting_text
        and "sıfır kabul edilmez" in reporting_text,
        "financial UI makes coverage and currency separation visible instead of inventing totals",
    )
    check(
        "quote_to_accept_conversion_percent" in reporting_text
        and "average_operation_cycle_hours" in reporting_text
        and "on_time_delivery_percent" in reporting_text
        and "tracked_external_send_automation_share_percent" in reporting_text,
        "reporting UI surfaces backend-derived commercial operational and MINAI KPIs",
    )
    check(
        "_render_operator_assignment_performance" in reporting_text
        and "first_look_coverage_percent" in reporting_text
        and "average_first_look_seconds" in reporting_text
        and "median_first_look_seconds" in reporting_text
        and "Release/handoff workflow completion değildir." in reporting_text,
        "reporting UI surfaces evidence-based operator first-look metrics without false completion semantics",
    )
    check(
        'ZoneInfo("Europe/Istanbul")' in reporting_text
        and "learning_period_basis" in reporting_text
        and "tracked_send_scope" in reporting_text,
        "reporting UI states Istanbul date and MINAI evidence-scope semantics explicitly",
    )
    prohibited = (
        "final_price -",
        "supplier_cost -",
        "sum(row[",
        "MINAI_PILOT_TOKEN",
        "Authorization",
    )
    check(
        not any(token in reporting_text for token in prohibited),
        "reporting UI does not recompute financial authority or embed pilot credentials",
    )
    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_reporting_ui_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nReporting UI regressions: " + ("PASS" if result["passed"] else "FAIL"))
