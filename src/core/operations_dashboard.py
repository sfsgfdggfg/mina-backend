from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.core.mina_job_repository import MinaJobRepository
from src.core.operation_execution_repository import OperationExecutionRepository

ISTANBUL = ZoneInfo("Europe/Istanbul")
_WEEKDAYS_TR = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


def _exact_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == value else None


def _local_datetime(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(ISTANBUL)


def _route_text(job) -> str:
    shipment = job.shipment
    origin = shipment.pickup_city or shipment.pickup_country or "?"
    destination = shipment.delivery_city or shipment.delivery_country or "?"
    return f"{origin} → {destination}"


def _job_summary(job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "mina_code": job.mina_code,
        "customer_name": job.shipment.customer_name,
        "route": _route_text(job),
        "stage": job.stage,
        "operations_owner": job.operations_owner,
        "sales_owner": job.sales_owner,
    }


def _milestone(job, *, kind: str, label: str, value: date | datetime) -> dict[str, Any]:
    item = {
        **_job_summary(job),
        "kind": kind,
        "label": label,
        "all_day": isinstance(value, date) and not isinstance(value, datetime),
    }
    if isinstance(value, datetime):
        local = _local_datetime(value)
        item["at"] = local.isoformat()
        item["date"] = local.date().isoformat()
        item["sort_at"] = local.isoformat()
    else:
        item["at"] = value.isoformat()
        item["date"] = value.isoformat()
        item["sort_at"] = f"{value.isoformat()}T00:00:00+03:00"
    return item


def build_operations_dashboard(
    *,
    mina_repository: MinaJobRepository,
    operation_repository: OperationExecutionRepository,
    anchor_date: date | None = None,
    days: int = 5,
    now: datetime | None = None,
) -> dict[str, Any]:
    if days < 3 or days > 5:
        raise ValueError("Operations dashboard days must be between 3 and 5.")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Operations dashboard now must be timezone-aware.")
    local_now = current.astimezone(ISTANBUL)
    anchor = anchor_date or local_now.date()
    end_date = anchor + timedelta(days=days - 1)

    open_exceptions: dict[str, list] = defaultdict(list)
    for incident in operation_repository.list_exceptions():
        if incident.status == "open":
            open_exceptions[incident.job_id].append(incident)

    calendar_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    attention: list[dict[str, Any]] = []
    unscheduled: list[dict[str, Any]] = []
    active_jobs = [job for job in mina_repository.list_all() if not job.is_closed]

    for job in active_jobs:
        snapshot = operation_repository.get_snapshot(job.job_id)
        shipment = job.shipment
        milestones: list[dict[str, Any]] = []
        deadline = _local_datetime(shipment.customer_quote_deadline_at)
        if deadline is not None:
            milestones.append(_milestone(job, kind="quote_deadline", label="Teklif deadline", value=deadline))
        ready = _exact_date(shipment.cargo_ready_date)
        if ready is not None:
            milestones.append(_milestone(job, kind="cargo_ready", label="Yük hazır", value=ready))
        required = _exact_date(shipment.required_delivery_date)
        if required is not None:
            milestones.append(_milestone(job, kind="required_delivery", label="Zorunlu teslim", value=required))
        if snapshot is not None:
            for kind, label, value in (
                ("loading_appointment", "Yükleme randevusu", snapshot.loading_appointment_at),
                ("current_eta", "Güncel ETA", snapshot.current_eta),
                ("delivery_appointment", "Teslim randevusu", snapshot.delivery_appointment_at),
            ):
                if value is not None:
                    milestones.append(_milestone(job, kind=kind, label=label, value=value))

        incidents = open_exceptions.get(job.job_id, [])
        reasons: list[str] = []
        severity = "normal"
        if any(item.impact_level == "actual_delay" for item in incidents):
            severity = "critical"
            reasons.append("Aktif gecikme")
        elif any(item.impact_level == "delivery_risk" for item in incidents):
            severity = "warning"
            reasons.append("Teslim riski")
        if deadline is not None and deadline < local_now and job.stage in {"inquiry_confirmed", "pricing", "quote_ready"}:
            severity = "critical"
            reasons.append("Teklif deadline geçti")
        if required is not None and required < anchor and job.stage not in {"delivered", "pod_cmr_pending", "closing_review", "completed"}:
            severity = "critical"
            reasons.append("Zorunlu teslim tarihi geçti")

        if reasons:
            attention.append({**_job_summary(job), "severity": severity, "reasons": reasons})
        has_attention = bool(reasons)
        for item in milestones:
            item["has_attention"] = has_attention
            item_date = date.fromisoformat(item["date"])
            if anchor <= item_date <= end_date:
                calendar_by_date[item["date"]].append(item)

        if not milestones:
            unscheduled.append({**_job_summary(job), "reason": "Yapılandırılmış operasyon tarihi yok"})

    day_rows = []
    calendar_entries = 0
    for offset in range(days):
        day = anchor + timedelta(days=offset)
        entries = calendar_by_date.get(day.isoformat(), [])
        entries.sort(key=lambda item: (item["sort_at"], item["mina_code"], item["kind"]))
        for item in entries:
            item.pop("sort_at", None)
        calendar_entries += len(entries)
        day_rows.append({
            "date": day.isoformat(),
            "weekday": _WEEKDAYS_TR[day.weekday()],
            "is_today": day == local_now.date(),
            "entries": entries,
        })

    severity_order = {"critical": 0, "warning": 1, "normal": 2}
    attention.sort(key=lambda item: (severity_order[item["severity"]], item["mina_code"]))
    unscheduled.sort(key=lambda item: item["mina_code"])
    return {
        "generated_at": current.isoformat(),
        "timezone": "Europe/Istanbul",
        "anchor_date": anchor.isoformat(),
        "window_end_date": end_date.isoformat(),
        "days": day_rows,
        "attention": attention,
        "unscheduled": unscheduled,
        "summary": {
            "active_jobs": len(active_jobs),
            "calendar_entries": calendar_entries,
            "attention_jobs": len(attention),
            "unscheduled_jobs": len(unscheduled),
        },
    }
