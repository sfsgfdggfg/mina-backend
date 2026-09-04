from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.core.mina_job import MinaJob
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.models import Shipment
from src.core.operation_execution import OperationException, OperationExecutionSnapshot
from src.core.operation_execution_repository import InMemoryOperationExecutionRepository
from src.core.operations_dashboard import build_operations_dashboard
from src.core.pilot_access import route_allowed

UTC = timezone.utc
NOW = datetime(2026, 9, 4, 8, 0, tzinfo=UTC)
ROOT = Path(__file__).resolve().parents[2]


def _job(number: int, *, shipment: Shipment, stage: str = "pricing", closed: bool = False):
    return MinaJob(
        mina_code=f"MINA2026/{number}", sequence_year=2026, sequence_number=number,
        lifecycle_version=2, job_kind="price_request" if stage in {"pricing", "quote_sent"} else "approved_job",
        intake_channel="phone", manual_intake_id=f"dashboard-{number}", shipment=shipment,
        stage=stage, operations_owner="Ozan", sales_owner="Alice", opened_by="Pilot Operator",
        opened_at=NOW - timedelta(days=1), updated_at=NOW,
        closed_at=NOW if closed else None,
    )


def evaluate_operations_dashboard_regressions() -> dict:
    failures: list[str] = []

    def check(condition: bool, message: str):
        if condition:
            print(f"PASS {message}")
        else:
            print(f"FAIL {message}")
            failures.append(message)

    jobs = InMemoryMinaJobRepository()
    operations = InMemoryOperationExecutionRepository()

    quote_job = _job(1, shipment=Shipment(
        customer_name="Acme", pickup_city="Adana", delivery_city="Munich", transport_mode="road",
        customer_quote_deadline_at=datetime(2026, 9, 4, 12, 0, tzinfo=UTC),
        cargo_ready_date="2026-09-05", required_delivery_date="2026-09-08",
    ))
    transit_job = _job(2, shipment=Shipment(
        customer_name="Beta", pickup_city="Mersin", delivery_city="Vienna", transport_mode="road",
        customer_quote_deadline_at=datetime(2026, 9, 3, 9, 0, tzinfo=UTC),
    ), stage="in_transit")
    unscheduled_job = _job(3, shipment=Shipment(
        customer_name="Gamma", pickup_city="Bursa", delivery_city="Prague", transport_mode="road",
        cargo_ready_date="next Friday",
    ), stage="operation_opened")
    closed_job = _job(4, shipment=Shipment(
        customer_name="Closed", pickup_city="Izmir", delivery_city="Berlin", transport_mode="road",
        required_delivery_date="2026-09-05",
    ), stage="completed", closed=True)
    overdue_job = _job(5, shipment=Shipment(
        customer_name="Late Quote", pickup_city="Adana", delivery_city="Hamburg", transport_mode="road",
        customer_quote_deadline_at=datetime(2026, 9, 3, 12, 0, tzinfo=UTC),
    ))
    for job in (quote_job, transit_job, unscheduled_job, closed_job, overdue_job):
        jobs.save(job)

    operations.save_snapshot(OperationExecutionSnapshot(
        job_id=transit_job.job_id, mina_code=transit_job.mina_code,
        loading_appointment_at=datetime(2026, 9, 4, 6, 0, tzinfo=UTC),
        current_eta=datetime(2026, 9, 6, 10, 0, tzinfo=UTC),
        delivery_appointment_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        updated_at=NOW, updated_by="Ozan",
    ))
    operations.create_exception(OperationException(
        entry_id="dashboard-delay", job_id=transit_job.job_id, mina_code=transit_job.mina_code,
        stage_at_report="in_transit", exception_type="border_congestion", impact_level="actual_delay",
        cause="Border queue", source_type="operator", reported_at=NOW, created_at=NOW,
        created_by="Ozan", updated_at=NOW, updated_by="Ozan",
    ))

    result = build_operations_dashboard(
        mina_repository=jobs, operation_repository=operations, days=5, now=NOW,
    )
    check(result["anchor_date"] == "2026-09-04" and result["window_end_date"] == "2026-09-08",
          "dashboard uses a deterministic five-day Europe/Istanbul window")
    check(result["summary"]["active_jobs"] == 4,
          "closed MINA jobs are excluded from active dashboard workload")
    kinds_by_day = {
        day["date"]: {entry["kind"] for entry in day["entries"]}
        for day in result["days"]
    }
    check("quote_deadline" in kinds_by_day["2026-09-04"] and "cargo_ready" in kinds_by_day["2026-09-05"]
          and "required_delivery" in kinds_by_day["2026-09-08"],
          "quote deadline cargo-ready and required-delivery evidence map to calendar days")
    check({"current_eta", "delivery_appointment"}.issubset(kinds_by_day["2026-09-06"]),
          "operation ETA and delivery appointment evidence map to the correct Istanbul day")
    attention = {item["mina_code"]: item for item in result["attention"]}
    check(attention[transit_job.mina_code]["severity"] == "critical" and "Aktif gecikme" in attention[transit_job.mina_code]["reasons"],
          "actual-delay exception is surfaced as critical dashboard attention")
    check("Teklif deadline geçti" not in attention[transit_job.mina_code]["reasons"],
          "past quote deadlines do not create false alarms after the job has entered operations")
    check("Teklif deadline geçti" in attention[overdue_job.mina_code]["reasons"],
          "overdue customer quote deadline is surfaced outside the calendar window")
    check([item["mina_code"] for item in result["unscheduled"]] == [unscheduled_job.mina_code],
          "non-ISO vague dates do not fabricate calendar authority and remain unscheduled")

    try:
        build_operations_dashboard(mina_repository=jobs, operation_repository=operations, days=2, now=NOW)
    except ValueError:
        invalid_days_rejected = True
    else:
        invalid_days_rejected = False
    check(invalid_days_rejected, "dashboard rejects windows outside the supported three-to-five-day range")
    check(route_allowed("GET", "/operations-dashboard"),
          "controlled pilot allowlist admits the dashboard read surface")

    web_shell = (ROOT / "src" / "web_shell.py").read_text()
    web_js = (ROOT / "ui" / "web_shell" / "app.js").read_text()
    check('/app/dashboard' in web_shell and 'page="dashboard"' in web_shell,
          "authenticated shell routes login and root navigation to the operations dashboard")
    dashboard_block = web_js.split('function renderDashboard', 1)[1].split('function renderJobs', 1)[0]
    check('loadDashboard(5)' in web_js and '/operations-dashboard?days=${days}' in web_js
          and 'calendar-entry' in web_js and 'innerHTML' not in dashboard_block,
          "dashboard UI consumes backend authority and renders operational text without dynamic HTML")
    web_css = (ROOT / "ui" / "web_shell" / "app.css").read_text()
    check('formatDashboardDate' in web_js and 'Operasyon Merkezi' in web_shell
          and dashboard_block.index('dashboard-attention') < dashboard_block.index('dashboard-toolbar')
          and 'if (unscheduled.length)' in dashboard_block
          and 'grid-template-columns: repeat(4, minmax(0, 1fr))' in web_css,
          "dashboard first-view polish keeps attention above calendar and avoids empty vertical waste")

    return {"name": "Operations home dashboard and calendar", "passed": not failures, "failures": failures}


if __name__ == "__main__":
    result = evaluate_operations_dashboard_regressions()
    print("\nP2-10 operations dashboard regressions:", "PASS" if result["passed"] else "FAIL")
    raise SystemExit(0 if result["passed"] else 1)
