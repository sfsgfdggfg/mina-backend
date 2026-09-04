from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data import normalize_country, normalize_master_text
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.operation_execution_repository import OperationExecutionRepository
from src.core.operational_work_assignment_repository import OperationalWorkAssignmentRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_price_repository import SupplierPriceRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository

ISTANBUL = ZoneInfo("Europe/Istanbul")

_OPERATION_STAGES = {
    "operations", "operation_opened", "supplier_confirmation_pending",
    "vehicle_details_pending", "vehicle_assigned", "pre_loading_check",
    "ready_for_loading", "loaded", "in_transit", "delivery", "delivered",
    "pod_cmr_pending", "closing_review", "completed",
}
_ACCEPTED_STAGES = {"accepted", *_OPERATION_STAGES}
_QUOTE_SENT_STAGES = {"quote_sent", "negotiation", *_ACCEPTED_STAGES}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # Compatibility for pre-hardening records created with datetime.utcnow().
        return value.replace(tzinfo=timezone.utc)
    return value


def _istanbul_date(value: datetime) -> date:
    aware = _aware(value)
    assert aware is not None
    return aware.astimezone(ISTANBUL).date()


def _hours(start: datetime | None, end: datetime | None) -> float | None:
    a, b = _aware(start), _aware(end)
    if a is None or b is None or b < a:
        return None
    return round((b - a).total_seconds() / 3600, 2)


def _seconds(start: datetime | None, end: datetime | None) -> float | None:
    a, b = _aware(start), _aware(end)
    if a is None or b is None or b < a:
        return None
    return round((b - a).total_seconds(), 2)


def _avg(values: list[float]) -> float | None:
    return None if not values else round(sum(values) / len(values), 2)


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return round(ordered[middle], 2)
    return round((ordered[middle - 1] + ordered[middle]) / 2, 2)


def _operator_assignment_performance(
    repository: OperationalWorkAssignmentRepository | None,
    *,
    start_date: date | None,
    end_date: date | None,
) -> dict[str, Any]:
    if repository is None:
        return {
            "period_basis": "assignment_assigned_at_istanbul",
            "status": "assignment_repository_unavailable",
            "rows": [],
            "summary": {"assignment_generation_count": 0, "acknowledged_generation_count": 0},
            "first_look_sla_status": "threshold_not_configured",
            "completion_metric_status": "work_type_completion_mapping_not_configured",
        }

    generations: dict[tuple[str, int], dict[str, Any]] = {}
    for snapshot in repository.list_history():
        key = (snapshot.work_id, snapshot.generation)
        record = generations.setdefault(key, {
            "work_id": snapshot.work_id,
            "generation": snapshot.generation,
            "assigned_to": snapshot.assigned_to,
            "assigned_at": snapshot.assigned_at,
            "acknowledged_at": None,
            "released_at": None,
            "release_reason": None,
        })
        if snapshot.acknowledged_at is not None:
            record["acknowledged_at"] = snapshot.acknowledged_at
        if snapshot.released_at is not None:
            record["released_at"] = snapshot.released_at
            record["release_reason"] = snapshot.release_reason

    selected = [
        record for record in generations.values()
        if (start_date is None or _istanbul_date(record["assigned_at"]) >= start_date)
        and (end_date is None or _istanbul_date(record["assigned_at"]) <= end_date)
    ]
    by_operator: dict[str, dict[str, Any]] = {}

    def row_for(name: str) -> dict[str, Any]:
        return by_operator.setdefault(name, {
            "name": name,
            "assignment_generation_count": 0,
            "acknowledged_generation_count": 0,
            "released_assignment_count": 0,
            "operator_release_count": 0,
            "shift_handoff_count": 0,
            "reassignment_generation_count": 0,
            "_first_look_seconds": [],
        })

    for record in selected:
        row = row_for(record["assigned_to"])
        row["assignment_generation_count"] += 1
        row["reassignment_generation_count"] += int(record["generation"] > 1)
        if record["acknowledged_at"] is not None:
            seconds = _seconds(record["assigned_at"], record["acknowledged_at"])
            if seconds is not None:
                row["_first_look_seconds"].append(seconds)
                row["acknowledged_generation_count"] += 1
        if record["released_at"] is not None:
            row["released_assignment_count"] += 1
            row["operator_release_count"] += int(record["release_reason"] == "operator_release")
            row["shift_handoff_count"] += int(record["release_reason"] == "shift_handoff")

    rows = []
    for row in by_operator.values():
        first_look = row.pop("_first_look_seconds")
        row["first_look_coverage_percent"] = _ratio(
            row["acknowledged_generation_count"], row["assignment_generation_count"]
        )
        row["average_first_look_seconds"] = _avg(first_look)
        row["median_first_look_seconds"] = _median(first_look)
        row["first_look_sla_percent"] = None
        rows.append(row)
    rows.sort(key=lambda row: (-row["assignment_generation_count"], row["name"]))

    all_first_look = []
    for record in selected:
        if record["acknowledged_at"] is None:
            continue
        seconds = _seconds(record["assigned_at"], record["acknowledged_at"])
        if seconds is not None:
            all_first_look.append(seconds)
    assigned_count = len(selected)
    acknowledged_count = len(all_first_look)
    return {
        "period_basis": "assignment_assigned_at_istanbul",
        "status": "evidence_based",
        "summary": {
            "assignment_generation_count": assigned_count,
            "acknowledged_generation_count": acknowledged_count,
            "first_look_coverage_percent": _ratio(acknowledged_count, assigned_count),
            "average_first_look_seconds": _avg(all_first_look),
            "median_first_look_seconds": _median(all_first_look),
        },
        "rows": rows,
        "first_look_sla_status": "threshold_not_configured",
        "completion_metric_status": "work_type_completion_mapping_not_configured",
        "note": "Speed metrics are descriptive evidence only; assignment release/handoff are not workflow completion.",
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator <= 0 else round(100 * numerator / denominator, 2)


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value.strip())
    except (TypeError, ValueError):
        return None


def _route_identity(job) -> tuple[str, str]:
    pickup = job.shipment.pickup_country or job.shipment.pickup_city or "?"
    delivery = job.shipment.delivery_country or job.shipment.delivery_city or "?"
    pickup_key = (
        normalize_country(job.shipment.pickup_country)
        if job.shipment.pickup_country else normalize_master_text(pickup)
    )
    delivery_key = (
        normalize_country(job.shipment.delivery_country)
        if job.shipment.delivery_country else normalize_master_text(delivery)
    )
    return f"{pickup_key}->{delivery_key}", f"{pickup} → {delivery}"


def _event_time(events, *, event_type: str | None = None, target_stage: str | None = None):
    matches = []
    for event in events:
        if event_type is not None and event.event_type == event_type:
            matches.append(_aware(event.occurred_at))
        if (
            target_stage is not None
            and event.event_type == "stage_changed"
            and event.metadata.get("to_stage") == target_stage
        ):
            matches.append(_aware(event.occurred_at))
    matches = [item for item in matches if item is not None]
    return min(matches) if matches else None


def _reached(job, events, *, target: str) -> bool:
    if target == "quote_sent":
        return (
            job.stage in _QUOTE_SENT_STAGES
            or _event_time(events, event_type="customer_quote_sent") is not None
            or _event_time(events, target_stage="quote_sent") is not None
        )
    if target == "accepted":
        return job.stage in _ACCEPTED_STAGES or _event_time(events, target_stage="accepted") is not None
    if target == "operation":
        return job.stage in _OPERATION_STAGES or any(
            _event_time(events, target_stage=stage) is not None
            for stage in ("operations", "operation_opened")
        )
    if target == "completed":
        return job.stage == "completed" or (job.lifecycle_version == 1 and job.stage == "delivered")
    raise ValueError(f"Unsupported reporting milestone: {target}")


def _new_money_bucket() -> dict[str, float | int]:
    return {
        "quoted_value": 0.0,
        "quoted_gross_profit": 0.0,
        "accepted_value": 0.0,
        "accepted_gross_profit": 0.0,
        "completed_value": 0.0,
        "completed_gross_profit": 0.0,
        "covered_job_count": 0,
    }


def _add_money(target: dict[str, dict], currency: str, *, customer_quote, accepted: bool, completed: bool) -> None:
    code = str(currency or "").strip().upper() or "UNKNOWN"
    bucket = target.setdefault(code, _new_money_bucket())
    revenue = float(customer_quote.final_price)
    cost = float(customer_quote.supplier_cost)
    profit = revenue - cost
    bucket["quoted_value"] = round(float(bucket["quoted_value"]) + revenue, 2)
    bucket["quoted_gross_profit"] = round(float(bucket["quoted_gross_profit"]) + profit, 2)
    bucket["covered_job_count"] = int(bucket["covered_job_count"]) + 1
    if accepted:
        bucket["accepted_value"] = round(float(bucket["accepted_value"]) + revenue, 2)
        bucket["accepted_gross_profit"] = round(float(bucket["accepted_gross_profit"]) + profit, 2)
    if completed:
        bucket["completed_value"] = round(float(bucket["completed_value"]) + revenue, 2)
        bucket["completed_gross_profit"] = round(float(bucket["completed_gross_profit"]) + profit, 2)


def _financial_row(customer_quote) -> dict[str, Any]:
    if customer_quote is None:
        return {"available": False}
    revenue = float(customer_quote.final_price)
    cost = float(customer_quote.supplier_cost)
    profit = revenue - cost
    return {
        "available": True,
        "currency": customer_quote.currency,
        "customer_value": revenue,
        "supplier_cost": cost,
        "gross_profit": round(profit, 2),
        "gross_margin_percent": None if revenue <= 0 else round(100 * profit / revenue, 2),
    }


def _sorted_rows(groups: dict[str, dict], *, count_key: str = "job_count") -> list[dict]:
    return sorted(groups.values(), key=lambda row: (-int(row.get(count_key, 0)), str(row.get("name", ""))))


def build_reporting_read_model(
    *,
    mina_repository: MinaJobRepository,
    quote_case_repository: QuoteCaseRepository,
    supplier_rfq_repository: SupplierRFQRepository,
    supplier_price_repository: SupplierPriceRepository,
    operation_execution_repository: OperationExecutionRepository,
    master_data_repository: MasterDataRepository,
    learning_fact_repository: LearningFactRepository,
    operational_work_assignment_repository: OperationalWorkAssignmentRepository | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    if start_date is not None and end_date is not None and end_date < start_date:
        raise ValueError("Reporting end_date cannot precede start_date.")
    now = _aware(as_of or datetime.now(timezone.utc))
    assert now is not None

    jobs = [
        job for job in mina_repository.list_all()
        if (start_date is None or _istanbul_date(job.opened_at) >= start_date)
        and (end_date is None or _istanbul_date(job.opened_at) <= end_date)
    ]
    jobs.sort(key=lambda item: (_aware(item.opened_at), item.mina_code))
    job_ids = {job.job_id for job in jobs}
    events_by_job = {job.job_id: mina_repository.list_events(job.job_id) for job in jobs}

    quote_cases = quote_case_repository.list_all()
    quote_by_job: dict[str, Any] = {}
    quote_by_code: dict[str, Any] = {}
    for case in quote_cases:
        if case.mina_job_id:
            quote_by_job[case.mina_job_id] = case
        if case.mina_code:
            quote_by_code[case.mina_code] = case

    exceptions = [
        item for item in operation_execution_repository.list_exceptions()
        if item.job_id in job_ids
    ]
    exceptions_by_job: dict[str, list] = defaultdict(list)
    for incident in exceptions:
        exceptions_by_job[incident.job_id].append(incident)

    facts = learning_fact_repository.list_all()
    operation_facts = [item for item in facts if item.subject_type == "operation" and item.subject_id in job_ids]

    customer_groups: dict[str, dict] = {}
    sales_groups: dict[str, dict] = {}
    operations_groups: dict[str, dict] = {}
    route_groups: dict[str, dict] = {}
    customer_identity: dict[str, str] = {}
    for profile in master_data_repository.list_customers():
        for term in [profile.customer_name, *profile.aliases]:
            normalized = normalize_master_text(term)
            if normalized:
                customer_identity[normalized] = profile.customer_name
    job_rows: list[dict[str, Any]] = []
    overall_money: dict[str, dict] = {}
    quote_turnaround_hours: list[float] = []
    operation_cycle_hours: list[float] = []
    customer_master_matched_jobs = 0
    delivery_known = delivery_on_time = 0
    deadline_known = deadline_met = 0

    def group_base(name: str) -> dict:
        return {
            "name": name, "job_count": 0, "open_job_count": 0,
            "price_request_count": 0, "approved_job_count": 0,
            "quote_sent_count": 0, "accepted_price_request_count": 0,
            "awarded_job_count": 0, "completed_count": 0,
            "lost_count": 0, "cancelled_count": 0,
            "exception_count": 0, "open_exception_count": 0, "actual_delay_count": 0,
            "quote_deadline_measurable_count": 0, "quote_deadline_met_count": 0,
            "delivery_sla_measurable_count": 0, "on_time_delivery_count": 0,
            "financial_by_currency": {},
            "_quote_turnaround_hours": [], "_operation_cycle_hours": [],
        }

    for job in jobs:
        events = events_by_job[job.job_id]
        quote_case = (
            quote_case_repository.get(job.quote_case_id) if job.quote_case_id else None
        ) or quote_by_job.get(job.job_id) or quote_by_code.get(job.mina_code)
        customer_quote = None if quote_case is None else quote_case.customer_quote

        quote_sent = _reached(job, events, target="quote_sent") if job.job_kind == "price_request" else False
        customer_quote_accepted = (
            _reached(job, events, target="accepted") if job.job_kind == "price_request" else False
        )
        commercially_awarded = job.job_kind == "approved_job" or customer_quote_accepted
        completed = _reached(job, events, target="completed")
        operation_started = _reached(job, events, target="operation")

        quote_sent_at = _event_time(events, event_type="customer_quote_sent") or _event_time(events, target_stage="quote_sent")
        accepted_at = _event_time(events, target_stage="accepted")
        operation_opened_at = _event_time(events, target_stage="operation_opened") or _event_time(events, target_stage="operations")
        completed_at = _event_time(events, target_stage="completed") or (job.closed_at if completed else None)
        snapshot = operation_execution_repository.get_snapshot(job.job_id)
        delivered_at = None if snapshot is None else snapshot.delivered_at
        if delivered_at is None and job.lifecycle_version == 1 and job.stage == "delivered":
            delivered_at = job.closed_at

        quote_hours = _hours(job.opened_at, quote_sent_at)
        if quote_hours is not None:
            quote_turnaround_hours.append(quote_hours)
        cycle_hours = _hours(operation_opened_at, completed_at)
        if cycle_hours is not None:
            operation_cycle_hours.append(cycle_hours)

        deadline_at = _aware(job.shipment.customer_quote_deadline_at)
        quote_deadline_met = None
        if deadline_at is not None and quote_sent_at is not None:
            deadline_known += 1
            quote_deadline_met = quote_sent_at <= deadline_at
            deadline_met += int(quote_deadline_met)

        required_delivery = _parse_iso_date(job.shipment.required_delivery_date)
        on_time_delivery = None
        if required_delivery is not None and delivered_at is not None:
            delivery_known += 1
            on_time_delivery = _istanbul_date(delivered_at) <= required_delivery
            delivery_on_time += int(on_time_delivery)

        job_incidents = exceptions_by_job.get(job.job_id, [])
        actual_delays = sum(item.impact_level == "actual_delay" for item in job_incidents)
        open_incidents = sum(item.status == "open" for item in job_incidents)
        financial = _financial_row(customer_quote)
        if customer_quote is not None:
            _add_money(
                overall_money, customer_quote.currency,
                customer_quote=customer_quote, accepted=commercially_awarded, completed=completed,
            )

        raw_customer_name = str(job.shipment.customer_name or "Unassigned Customer").strip() or "Unassigned Customer"
        customer_identity_key = normalize_master_text(raw_customer_name)
        customer_master_matched = customer_identity_key in customer_identity
        customer_master_matched_jobs += int(customer_master_matched)
        customer_name = customer_identity.get(customer_identity_key, raw_customer_name)
        sales_owner = job.sales_owner or "Unassigned"
        operations_owner = job.operations_owner or "Unassigned"
        route_id, route = _route_identity(job)
        grouping = (
            (customer_groups, normalize_master_text(customer_name), customer_name),
            (sales_groups, normalize_master_text(sales_owner), sales_owner),
            (operations_groups, normalize_master_text(operations_owner), operations_owner),
            (route_groups, route_id, route),
        )
        for groups, group_key, name in grouping:
            row = groups.setdefault(group_key, group_base(name))
            if groups is route_groups:
                row["route_key"] = route_id
            row["job_count"] += 1
            row["open_job_count"] += int(not job.is_closed)
            row["price_request_count"] += int(job.job_kind == "price_request")
            row["approved_job_count"] += int(job.job_kind == "approved_job")
            row["quote_sent_count"] += int(quote_sent)
            row["accepted_price_request_count"] += int(customer_quote_accepted)
            row["awarded_job_count"] += int(commercially_awarded)
            row["completed_count"] += int(completed)
            row["lost_count"] += int(job.stage == "lost")
            row["cancelled_count"] += int(job.stage == "cancelled")
            row["exception_count"] += len(job_incidents)
            row["open_exception_count"] += open_incidents
            row["actual_delay_count"] += actual_delays
            if quote_hours is not None:
                row["_quote_turnaround_hours"].append(quote_hours)
            if cycle_hours is not None:
                row["_operation_cycle_hours"].append(cycle_hours)
            if quote_deadline_met is not None:
                row["quote_deadline_measurable_count"] += 1
                row["quote_deadline_met_count"] += int(quote_deadline_met)
            if on_time_delivery is not None:
                row["delivery_sla_measurable_count"] += 1
                row["on_time_delivery_count"] += int(on_time_delivery)
            if customer_quote is not None:
                _add_money(
                    row["financial_by_currency"], customer_quote.currency,
                    customer_quote=customer_quote, accepted=commercially_awarded, completed=completed,
                )

        job_rows.append({
            "job_id": job.job_id, "mina_code": job.mina_code, "job_kind": job.job_kind,
            "stage": job.stage, "is_closed": job.is_closed, "customer_name": customer_name,
            "customer_master_matched": customer_master_matched,
            "sales_owner": job.sales_owner, "operations_owner": job.operations_owner,
            "route": route, "transport_mode": job.shipment.transport_mode,
            "opened_at": job.opened_at, "quote_sent_at": quote_sent_at,
            "accepted_at": accepted_at, "operation_opened_at": operation_opened_at,
            "delivered_at": delivered_at, "completed_at": completed_at,
            "quote_sent": quote_sent, "customer_quote_accepted": customer_quote_accepted,
            "commercially_awarded": commercially_awarded,
            "operation_started": operation_started, "completed": completed,
            "quote_turnaround_hours": quote_hours, "operation_cycle_hours": cycle_hours,
            "quote_deadline_met": quote_deadline_met, "on_time_delivery": on_time_delivery,
            "exception_count": len(job_incidents), "open_exception_count": open_incidents,
            "actual_delay_count": actual_delays, "financial": financial,
        })

    for groups in (customer_groups, sales_groups, operations_groups, route_groups):
        for row in groups.values():
            row["quote_to_accept_conversion_percent"] = _ratio(
                row["accepted_price_request_count"], row["quote_sent_count"]
            )
            row["completion_rate_percent"] = _ratio(
                row["completed_count"], row["job_count"]
            )
            row["average_quote_turnaround_hours"] = _avg(row.pop("_quote_turnaround_hours"))
            row["average_operation_cycle_hours"] = _avg(row.pop("_operation_cycle_hours"))
            row["quote_deadline_sla_percent"] = _ratio(
                row["quote_deadline_met_count"], row["quote_deadline_measurable_count"]
            )
            row["on_time_delivery_percent"] = _ratio(
                row["on_time_delivery_count"], row["delivery_sla_measurable_count"]
            )

    # Supplier reporting combines RFQ responsiveness, price participation and selection outcomes.
    workflow_to_job = {
        workflow.workflow_id: workflow.mina_job_id
        for workflow in supplier_rfq_repository.list_workflows()
        if workflow.mina_job_id in job_ids
    }
    responses_by_rfq: dict[str, list] = defaultdict(list)
    for response in supplier_rfq_repository.list_responses():
        responses_by_rfq[response.rfq_id].append(response)
    supplier_groups: dict[str, dict] = {}
    response_minutes_by_supplier: dict[str, list[float]] = defaultdict(list)
    for draft in supplier_rfq_repository.list_drafts():
        if workflow_to_job.get(draft.workflow_id) not in job_ids:
            continue
        name = draft.supplier_name
        row = supplier_groups.setdefault(name, {
            "name": name, "rfq_count": 0, "rfq_sent_count": 0,
            "responded_count": 0, "quoted_count": 0, "no_capacity_count": 0,
            "declined_count": 0, "price_offer_count": 0, "selected_count": 0,
            "selected_completed_job_count": 0, "selected_actual_delay_count": 0,
            "master_reliability_score": None, "master_price_score": None,
            "master_speed_score": None,
        })
        row["rfq_count"] += 1
        row["rfq_sent_count"] += int(draft.sent_at is not None)
        replies = sorted(
            responses_by_rfq.get(draft.rfq_id, []),
            key=lambda item: _aware(item.received_at),
        )
        if replies:
            row["responded_count"] += 1
            quoted_here = int(any(item.status == "quoted" for item in replies))
            row["quoted_count"] += quoted_here
            row["price_offer_count"] += quoted_here
            row["no_capacity_count"] += int(any(item.status == "no_capacity" for item in replies))
            row["declined_count"] += int(any(item.status == "declined" for item in replies))
            if draft.sent_at is not None:
                duration = _hours(draft.sent_at, replies[0].received_at)
                if duration is not None:
                    response_minutes_by_supplier[name].append(duration * 60)

    for offer in supplier_price_repository.list_offers():
        if offer.mina_job_id not in job_ids:
            continue
        row = supplier_groups.setdefault(offer.supplier_name, {
            "name": offer.supplier_name, "rfq_count": 0, "rfq_sent_count": 0,
            "responded_count": 0, "quoted_count": 0, "no_capacity_count": 0,
            "declined_count": 0, "price_offer_count": 0, "selected_count": 0,
            "selected_completed_job_count": 0, "selected_actual_delay_count": 0,
            "master_reliability_score": None, "master_price_score": None,
            "master_speed_score": None,
        })
        row["price_offer_count"] += 1

    job_by_id = {job.job_id: job for job in jobs}
    for job in jobs:
        case = (
            quote_case_repository.get(job.quote_case_id) if job.quote_case_id else None
        ) or quote_by_job.get(job.job_id) or quote_by_code.get(job.mina_code)
        if case is None:
            continue
        selected = (
            case.supplier_quote_selection_decision.selected_supplier
            if case.supplier_quote_selection_decision is not None
            else (case.supplier_quote.supplier_name if case.supplier_quote is not None else None)
        )
        if not selected:
            continue
        row = supplier_groups.setdefault(selected, {
            "name": selected, "rfq_count": 0, "rfq_sent_count": 0,
            "responded_count": 0, "quoted_count": 0, "no_capacity_count": 0,
            "declined_count": 0, "price_offer_count": 0, "selected_count": 0,
            "selected_completed_job_count": 0, "selected_actual_delay_count": 0,
            "master_reliability_score": None, "master_price_score": None,
            "master_speed_score": None,
        })
        row["selected_count"] += 1
        row["selected_completed_job_count"] += int(_reached(job, events_by_job[job.job_id], target="completed"))
        row["selected_actual_delay_count"] += sum(
            item.impact_level == "actual_delay" for item in exceptions_by_job.get(job.job_id, [])
        )

    for profile in master_data_repository.list_suppliers():
        row = supplier_groups.get(profile.supplier_name)
        if row is None:
            continue
        row["master_reliability_score"] = profile.reliability_score
        row["master_price_score"] = profile.price_score
        row["master_speed_score"] = profile.speed_score
    for name, row in supplier_groups.items():
        row["response_rate_percent"] = _ratio(row["responded_count"], row["rfq_sent_count"])
        row["quote_rate_percent"] = _ratio(row["quoted_count"], row["rfq_sent_count"])
        row["selection_provenance_gap_count"] = max(0, row["selected_count"] - row["price_offer_count"])
        row["selection_rate_percent"] = (
            None if row["selection_provenance_gap_count"] else _ratio(row["selected_count"], row["price_offer_count"])
        )
        row["average_response_minutes"] = _avg(response_minutes_by_supplier.get(name, []))

    # Exception read model preserves operational impact instead of converting it into stages.
    impact_counts = {"deviation": 0, "delivery_risk": 0, "actual_delay": 0}
    status_counts = {"open": 0, "resolved": 0}
    type_counts: dict[str, int] = defaultdict(int)
    resolution_hours: list[float] = []
    affected_jobs = set()
    for incident in exceptions:
        impact_counts[incident.impact_level] += 1
        status_counts[incident.status] += 1
        type_counts[incident.exception_type] += 1
        affected_jobs.add(incident.job_id)
        resolved_hours = _hours(incident.created_at, incident.resolved_at)
        if resolved_hours is not None:
            resolution_hours.append(resolved_hours)

    # MINAI performance is evidence-based: review outcomes and actual sent evidence.
    relevant_facts = [
        item for item in facts
        if (start_date is None or _istanbul_date(item.created_at) >= start_date)
        and (end_date is None or _istanbul_date(item.created_at) <= end_date)
    ]
    fact_status = {status: 0 for status in ("proposed", "confirmed", "rejected", "superseded")}
    for item in relevant_facts:
        fact_status[item.status] += 1
    inference = [item for item in relevant_facts if item.source_type == "minai_inference"]
    inference_reviewed = [item for item in inference if item.status in {"confirmed", "rejected", "superseded"}]
    inference_confirmed = [item for item in inference if item.status in {"confirmed", "superseded"}]

    selected_rfq_ids = {
        draft.rfq_id for draft in supplier_rfq_repository.list_drafts()
        if workflow_to_job.get(draft.workflow_id) in job_ids
    }
    supplier_auto_sent = sum(
        item.rfq_id in selected_rfq_ids for item in supplier_rfq_repository.list_automated_sent_evidence()
    )
    supplier_manual_sent = sum(
        item.rfq_id in selected_rfq_ids for item in supplier_rfq_repository.list_manual_sent_evidence()
    )
    selected_follow_up_ids = {
        item.follow_up_id for item in supplier_rfq_repository.list_follow_up_drafts()
        if item.rfq_id in selected_rfq_ids
    }
    supplier_followup_auto_sent = sum(
        item.follow_up_id in selected_follow_up_ids
        for item in supplier_rfq_repository.list_follow_up_automated_sent_evidence()
    )
    supplier_followup_manual_sent = sum(
        item.follow_up_id in selected_follow_up_ids
        for item in supplier_rfq_repository.list_follow_up_manual_sent_evidence()
    )
    customer_auto_sent = 0
    customer_manual_sent = 0
    for job in jobs:
        case = (
            quote_case_repository.get(job.quote_case_id) if job.quote_case_id else None
        ) or quote_by_job.get(job.job_id) or quote_by_code.get(job.mina_code)
        if case is not None:
            customer_auto_sent += len(case.automated_sent_evidence)
            customer_manual_sent += len(case.manual_sent_evidence)

    price_requests = sum(job.job_kind == "price_request" for job in jobs)
    quotes_sent = sum(row["quote_sent"] for row in job_rows)
    accepted_price_requests = sum(
        row["customer_quote_accepted"] and job_by_id[row["job_id"]].job_kind == "price_request"
        for row in job_rows
    )
    awarded_jobs = sum(row["commercially_awarded"] for row in job_rows)
    completed_jobs = sum(row["completed"] for row in job_rows)
    open_jobs = sum(not job.is_closed for job in jobs)
    financial_covered = sum(row["financial"].get("available", False) for row in job_rows)
    supplier_selection_provenance_gap = sum(
        int(row.get("selection_provenance_gap_count", 0)) for row in supplier_groups.values()
    )
    missing_sales_owner = sum(not job.sales_owner for job in jobs)
    missing_operations_owner = sum(not job.operations_owner for job in jobs)
    parseable_delivery = sum(_parse_iso_date(job.shipment.required_delivery_date) is not None for job in jobs)
    assignment_performance = _operator_assignment_performance(
        operational_work_assignment_repository, start_date=start_date, end_date=end_date
    )

    return {
        "period": {
            "basis": "mina_job_opened_at_istanbul",
            "start_date": start_date, "end_date": end_date,
            "as_of": now, "timezone": "Europe/Istanbul",
            "job_count": len(jobs),
        },
        "overview": {
            "job_count": len(jobs), "open_job_count": open_jobs,
            "closed_job_count": len(jobs) - open_jobs,
            "price_request_count": price_requests,
            "approved_job_count": len(jobs) - price_requests,
            "quotes_sent_count": quotes_sent,
            "accepted_price_request_count": accepted_price_requests,
            "awarded_job_count": awarded_jobs,
            "quote_to_accept_conversion_percent": _ratio(accepted_price_requests, quotes_sent),
            "completed_job_count": completed_jobs,
            "average_quote_turnaround_hours": _avg(quote_turnaround_hours),
            "average_operation_cycle_hours": _avg(operation_cycle_hours),
            "quote_deadline_sla_percent": _ratio(deadline_met, deadline_known),
            "on_time_delivery_percent": _ratio(delivery_on_time, delivery_known),
            "open_exception_count": status_counts["open"],
            "actual_delay_count": impact_counts["actual_delay"],
        },
        "sales": {
            "rows": _sorted_rows(sales_groups),
            "unassigned_job_count": missing_sales_owner,
        },
        "operations": {
            "rows": _sorted_rows(operations_groups),
            "unassigned_job_count": missing_operations_owner,
            "work_assignment_performance": assignment_performance,
        },
        "customers": {"rows": _sorted_rows(customer_groups)},
        "suppliers": {
            "rows": sorted(supplier_groups.values(), key=lambda row: (-row["selected_count"], -row["rfq_count"], row["name"])),
        },
        "routes": {"rows": _sorted_rows(route_groups)},
        "financial": {
            "by_currency": overall_money,
            "financially_covered_job_count": financial_covered,
            "financial_coverage_percent": _ratio(financial_covered, len(jobs)),
            "uncovered_job_count": len(jobs) - financial_covered,
            "note": "Values are never summed across currencies; missing customer-price evidence remains uncovered, not zero.",
        },
        "minai": {
            "learning_period_basis": "learning_fact_created_at_istanbul",
            "learning_fact_status_counts": fact_status,
            "minai_inference_count": len(inference),
            "minai_inference_reviewed_count": len(inference_reviewed),
            "minai_inference_confirmed_or_historically_confirmed_count": len(inference_confirmed),
            "minai_inference_confirmation_percent": _ratio(len(inference_confirmed), len(inference_reviewed)),
            "supplier_automated_send_count": supplier_auto_sent,
            "supplier_manual_send_count": supplier_manual_sent,
            "supplier_followup_automated_send_count": supplier_followup_auto_sent,
            "supplier_followup_manual_send_count": supplier_followup_manual_sent,
            "customer_quote_automated_send_count": customer_auto_sent,
            "customer_quote_manual_send_count": customer_manual_sent,
            "tracked_send_scope": "supplier_rfq_initial_and_followup_plus_customer_quote",
            "tracked_external_send_automation_share_percent": _ratio(
                supplier_auto_sent + supplier_followup_auto_sent + customer_auto_sent,
                supplier_auto_sent + supplier_manual_sent + supplier_followup_auto_sent
                + supplier_followup_manual_sent + customer_auto_sent + customer_manual_sent,
            ),
        },
        "exceptions": {
            "total_count": len(exceptions), "affected_job_count": len(affected_jobs),
            "status_counts": status_counts, "impact_counts": impact_counts,
            "type_counts": dict(sorted(type_counts.items())),
            "average_resolution_hours": _avg(resolution_hours),
            "customer_attention_recommended_open_count": sum(
                item.status == "open" and item.customer_attention_recommended for item in exceptions
            ),
        },
        "data_quality": {
            "financially_uncovered_job_count": len(jobs) - financial_covered,
            "customer_master_matched_job_count": customer_master_matched_jobs,
            "customer_master_coverage_percent": _ratio(customer_master_matched_jobs, len(jobs)),
            "supplier_selection_provenance_gap_count": supplier_selection_provenance_gap,
            "missing_sales_owner_count": missing_sales_owner,
            "missing_operations_owner_count": missing_operations_owner,
            "parseable_required_delivery_date_count": parseable_delivery,
            "delivery_date_coverage_percent": _ratio(parseable_delivery, len(jobs)),
            "quote_deadline_measurable_count": deadline_known,
            "delivery_sla_measurable_count": delivery_known,
        },
        "jobs": job_rows,
    }


REPORTING_SECTIONS = {
    "overview", "sales", "operations", "customers", "suppliers", "routes",
    "financial", "minai", "exceptions", "data_quality", "jobs",
}


def reporting_section(report: dict[str, Any], section: str) -> dict[str, Any]:
    if section not in REPORTING_SECTIONS:
        raise ValueError(f"Unsupported reporting section: {section}")
    return {"period": report["period"], section: report[section]}
