from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.requests import Request

from src.core.automation_action_repository import InMemoryAutomationActionRepository
from src.core.mina_job_repository import InMemoryMinaJobRepository
from src.core.mina_job_service import (
    MinaJobTransitionError,
    create_manual_mina_job,
    transition_mina_job_stage,
)
from src.core.mina_job_view import build_mina_job_detail
from src.core.models import Shipment
from src.core.operation_execution_repository import (
    InMemoryOperationExecutionRepository,
    OperationExecutionConflictError,
    SQLiteOperationExecutionRepository,
)
from src.core.operation_execution_service import (
    build_operation_execution_view,
    create_operation_exception,
    resolve_operation_exception,
    update_operation_exception,
    update_operation_execution,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.quote_case_repository import InMemoryQuoteCaseRepository
from src.core.sqlite_repositories import SQLiteMinaJobRepository
from src.core.supplier_rfq_repository import InMemorySupplierRFQRepository

NOW = datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc)


def _shipment(customer_name: str = "Beta Enerji") -> Shipment:
    return Shipment(
        customer_name=customer_name,
        pickup_country="Türkiye",
        pickup_city="Bursa",
        delivery_country="Almanya",
        delivery_city="Stuttgart",
        transport_mode="road",
        equipment_type="Tenteli / Curtainsider",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
    )


def _operation_job(repository, *, intake_id: str = "op-case", opened_at=NOW - timedelta(days=1)):
    job = create_manual_mina_job(
        repository=repository, manual_intake_id=intake_id,
        intake_channel="phone", job_kind="approved_job", shipment=_shipment(),
        opened_by="Operator", opened_at=opened_at,
    )
    job = transition_mina_job_stage(
        repository=repository, mina_code=job.mina_code, target_stage="pricing",
        actor="Operator", occurred_at=opened_at + timedelta(minutes=1),
    )
    job = transition_mina_job_stage(
        repository=repository, mina_code=job.mina_code, target_stage="operation_opened",
        actor="Operator", occurred_at=opened_at + timedelta(minutes=2),
    )
    return job


def evaluate_operation_execution_exception_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    jobs = InMemoryMinaJobRepository()
    execution = InMemoryOperationExecutionRepository()
    pre_job = create_manual_mina_job(
        repository=jobs, manual_intake_id="pre-operation", intake_channel="phone",
        job_kind="approved_job", shipment=_shipment(), opened_by="Operator", opened_at=NOW,
    )
    try:
        update_operation_execution(
            execution_repository=execution, mina_repository=jobs,
            job_id=pre_job.job_id, updated_by="Operator",
            changes={"current_location": "Bursa"}, occurred_at=NOW,
        )
        pre_operation_blocked = False
    except MinaJobTransitionError:
        pre_operation_blocked = True
    check(pre_operation_blocked, "operation execution cannot start before the operation lifecycle opens")

    jobs = InMemoryMinaJobRepository()
    execution = InMemoryOperationExecutionRepository()
    job = _operation_job(jobs)
    snapshot = update_operation_execution(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        updated_by="Operator", changes={
            "supplier_confirmed_at": NOW - timedelta(hours=5),
            "current_location": "Bursa",
            "current_eta": NOW + timedelta(hours=24),
        }, occurred_at=NOW - timedelta(hours=5),
    )
    events = jobs.list_events(job.job_id)
    check(
        snapshot.current_location == "Bursa"
        and snapshot.current_eta == NOW + timedelta(hours=24)
        and any(
            event.event_type == "operation_execution_updated"
            and set(event.metadata.get("changed_fields") or [])
            == {"supplier_confirmed_at", "current_location", "current_eta"}
            for event in events
        ),
        "execution snapshot updates are durable timeline evidence without raw field values",
    )

    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code,
        target_stage="supplier_confirmation_pending", actor="Operator",
        occurred_at=NOW - timedelta(hours=4), operation_execution_repository=execution,
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code,
        target_stage="vehicle_details_pending", actor="Operator",
        occurred_at=NOW - timedelta(hours=3), operation_execution_repository=execution,
    )
    try:
        transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code, target_stage="vehicle_assigned",
            actor="Operator", occurred_at=NOW - timedelta(hours=2),
            operation_execution_repository=execution,
        )
        vehicle_gate_blocked = False
    except MinaJobTransitionError:
        vehicle_gate_blocked = True
    update_operation_execution(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        updated_by="Operator", changes={
            "vehicle_plate": "34 TEST 123", "driver_name": "Ali Test",
            "driver_phone": "+90 555 000 0000",
            "vehicle_assigned_at": NOW - timedelta(hours=2),
        }, occurred_at=NOW - timedelta(hours=2),
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="vehicle_assigned",
        actor="Operator", occurred_at=NOW - timedelta(hours=2),
        operation_execution_repository=execution,
    )
    check(
        vehicle_gate_blocked and job.stage == "vehicle_assigned",
        "vehicle-assigned stage requires plate driver and assignment-time evidence",
    )

    for target in ("pre_loading_check", "ready_for_loading"):
        job = transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code, target_stage=target,
            actor="Operator", occurred_at=NOW - timedelta(minutes=90),
            operation_execution_repository=execution,
        )
    try:
        transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code, target_stage="loaded",
            actor="Operator", occurred_at=NOW - timedelta(minutes=60),
            operation_execution_repository=execution,
        )
        loaded_gate_blocked = False
    except MinaJobTransitionError:
        loaded_gate_blocked = True
    update_operation_execution(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        updated_by="Operator", changes={"loaded_at": NOW - timedelta(minutes=60)},
        occurred_at=NOW - timedelta(minutes=60),
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="loaded",
        actor="Operator", occurred_at=NOW - timedelta(minutes=60),
        operation_execution_repository=execution,
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="in_transit",
        actor="Operator", occurred_at=NOW - timedelta(minutes=50),
        operation_execution_repository=execution,
    )
    check(loaded_gate_blocked and job.stage == "in_transit", "loaded stage requires loaded_at evidence")

    deviation = create_operation_exception(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        entry_id="incident-deviation", exception_type="route_deviation",
        impact_level="deviation", cause="Planned motorway closure detour",
        source_type="gps", created_by="Operator", location="Edirne",
        reported_at=NOW - timedelta(minutes=40), occurred_at=NOW - timedelta(minutes=40),
    )
    repeated = create_operation_exception(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        entry_id="incident-deviation", exception_type="route_deviation",
        impact_level="deviation", cause="Planned motorway closure detour",
        source_type="gps", created_by="Operator", location="Edirne",
        reported_at=NOW - timedelta(minutes=40), occurred_at=NOW - timedelta(minutes=39),
    )
    created_events = [
        event for event in jobs.list_events(job.job_id)
        if event.event_type == "operation_exception_created"
        and event.resource_id == deviation.exception_id
    ]
    check(
        repeated.exception_id == deviation.exception_id and len(created_events) == 1,
        "exception creation is idempotent and writes one timeline creation event",
    )

    risk = create_operation_exception(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        entry_id="incident-risk", exception_type="border_congestion",
        impact_level="delivery_risk", cause="Kapıkule congestion",
        source_type="supplier_phone", created_by="Operator", location="Kapıkule",
        old_eta=NOW + timedelta(hours=20), new_eta=NOW + timedelta(hours=25),
        customer_impact_summary="Delivery appointment may be missed.",
        next_action="Monitor border exit and contact customer if risk increases.",
        reported_at=NOW - timedelta(minutes=30), occurred_at=NOW - timedelta(minutes=30),
    )
    view = build_operation_execution_view(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
    )
    check(
        job.stage == "in_transit"
        and view["open_impact_counts"] == {"deviation": 1, "delivery_risk": 1, "actual_delay": 0}
        and not deviation.customer_attention_recommended
        and risk.customer_attention_recommended
        and view["customer_attention_recommended"],
        "exceptions overlay the lifecycle and distinguish deviation from delivery risk",
    )

    risk = update_operation_exception(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        exception_id=risk.exception_id, updated_by="Operator",
        changes={
            "impact_level": "actual_delay",
            "customer_impact_summary": "Delivery appointment will be missed.",
            "next_action": "Inform customer and request a new appointment.",
        }, occurred_at=NOW - timedelta(minutes=20),
    )
    check(
        risk.impact_level == "actual_delay" and risk.customer_attention_recommended,
        "open exception impact can escalate from delivery risk to actual delay",
    )

    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="delivery",
        actor="Operator", occurred_at=NOW + timedelta(hours=20),
        operation_execution_repository=execution,
    )
    retry_after_stage_change = create_operation_exception(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        entry_id="incident-deviation", exception_type="route_deviation",
        impact_level="deviation", cause="Planned motorway closure detour",
        source_type="gps", created_by="Second Operator", location="Edirne",
        reported_at=NOW - timedelta(minutes=40), occurred_at=NOW + timedelta(hours=20, minutes=1),
    )
    check(
        retry_after_stage_change.exception_id == deviation.exception_id
        and retry_after_stage_change.stage_at_report == "in_transit"
        and retry_after_stage_change.created_by == "Operator",
        "exception retry preserves original creation evidence across stage or operator changes",
    )
    try:
        transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code, target_stage="delivered",
            actor="Operator", occurred_at=NOW + timedelta(hours=21),
            operation_execution_repository=execution,
        )
        delivered_gate_blocked = False
    except MinaJobTransitionError:
        delivered_gate_blocked = True
    update_operation_execution(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        updated_by="Operator", changes={"delivered_at": NOW + timedelta(hours=21)},
        occurred_at=NOW + timedelta(hours=21),
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="delivered",
        actor="Operator", occurred_at=NOW + timedelta(hours=21),
        operation_execution_repository=execution,
    )
    check(delivered_gate_blocked and job.stage == "delivered", "delivered stage requires delivered_at evidence")

    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="pod_cmr_pending",
        actor="Operator", occurred_at=NOW + timedelta(hours=22),
        operation_execution_repository=execution,
    )
    try:
        transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code, target_stage="closing_review",
            actor="Operator", occurred_at=NOW + timedelta(hours=23),
            operation_execution_repository=execution,
        )
        document_gate_blocked = False
    except MinaJobTransitionError:
        document_gate_blocked = True
    update_operation_execution(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        updated_by="Operator", changes={"cmr_received_at": NOW + timedelta(hours=23)},
        occurred_at=NOW + timedelta(hours=23),
    )
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="closing_review",
        actor="Operator", occurred_at=NOW + timedelta(hours=23),
        operation_execution_repository=execution,
    )
    try:
        transition_mina_job_stage(
            repository=jobs, mina_code=job.mina_code, target_stage="completed",
            actor="Operator", occurred_at=NOW + timedelta(hours=24),
            operation_execution_repository=execution,
        )
        open_exception_blocked = False
    except MinaJobTransitionError:
        open_exception_blocked = True
    check(
        document_gate_blocked and open_exception_blocked and job.stage == "closing_review",
        "closing requires POD or CMR and completion is blocked by open exceptions",
    )

    deviation = resolve_operation_exception(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        exception_id=deviation.exception_id, resolved_by="Operator",
        resolution_note="Detour completed without customer impact.",
        occurred_at=NOW + timedelta(hours=23, minutes=10),
    )
    risk = resolve_operation_exception(
        execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
        exception_id=risk.exception_id, resolved_by="Operator",
        resolution_note="Customer informed and revised delivery appointment completed.",
        occurred_at=NOW + timedelta(hours=23, minutes=20),
    )
    try:
        update_operation_exception(
            execution_repository=execution, mina_repository=jobs, job_id=job.job_id,
            exception_id=risk.exception_id, updated_by="Operator",
            changes={"cause": "Should not mutate"}, occurred_at=NOW + timedelta(hours=23, minutes=30),
        )
        resolved_frozen = False
    except MinaJobTransitionError:
        resolved_frozen = True
    job = transition_mina_job_stage(
        repository=jobs, mina_code=job.mina_code, target_stage="completed",
        actor="Operator", occurred_at=NOW + timedelta(hours=24),
        operation_execution_repository=execution,
    )
    check(
        resolved_frozen and job.stage == "completed" and job.is_closed,
        "resolved exceptions are immutable and completion succeeds after all closure evidence is satisfied",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "operation.sqlite3", retention_days=30)
        sqlite_jobs = SQLiteMinaJobRepository(store)
        sqlite_execution = SQLiteOperationExecutionRepository(store)
        durable_job = _operation_job(
            sqlite_jobs, intake_id="durable-operation", opened_at=NOW - timedelta(days=10)
        )
        durable_snapshot = update_operation_execution(
            execution_repository=sqlite_execution, mina_repository=sqlite_jobs,
            job_id=durable_job.job_id, updated_by="Operator",
            changes={"current_location": "Kapıkule", "current_eta": NOW + timedelta(hours=10)},
            occurred_at=NOW - timedelta(days=9),
        )
        durable_exception = create_operation_exception(
            execution_repository=sqlite_execution, mina_repository=sqlite_jobs,
            job_id=durable_job.job_id, entry_id="durable-exception",
            exception_type="border_congestion", impact_level="delivery_risk",
            cause="Durable congestion evidence", source_type="operator",
            created_by="Operator", reported_at=NOW - timedelta(days=9),
            occurred_at=NOW - timedelta(days=9),
        )
        store.purge_expired(now=NOW + timedelta(days=60))
        reopened = SQLiteOperationExecutionRepository(store)
        repeated_durable = create_operation_exception(
            execution_repository=reopened, mina_repository=sqlite_jobs,
            job_id=durable_job.job_id, entry_id="durable-exception",
            exception_type="border_congestion", impact_level="delivery_risk",
            cause="Durable congestion evidence", source_type="operator",
            created_by="Operator", reported_at=NOW - timedelta(days=9),
            occurred_at=NOW + timedelta(days=60),
        )
        check(
            reopened.get_snapshot(durable_job.job_id).current_location == durable_snapshot.current_location
            and reopened.get_exception(durable_exception.exception_id) is not None
            and repeated_durable.exception_id == durable_exception.exception_id,
            "execution snapshots exception evidence and idempotency survive ordinary retention purge",
        )

    detail = build_mina_job_detail(
        repository=jobs, supplier_repository=InMemorySupplierRFQRepository(),
        quote_case_repository=InMemoryQuoteCaseRepository(),
        action_repository=InMemoryAutomationActionRepository(),
        operation_execution_repository=execution, job_id=job.job_id, now=NOW,
    )
    check(
        detail["operation"]["snapshot"]["delivered_at"] is not None
        and detail["operation"]["open_exception_count"] == 0
        and len(detail["operation"]["exceptions"]) == 2,
        "MINA job detail exposes structured operation execution and exception context",
    )

    import src.api as api
    original_jobs = api.mina_job_repository
    original_execution = api.operation_execution_repository
    api_jobs = InMemoryMinaJobRepository()
    api_execution = InMemoryOperationExecutionRepository()
    api.mina_job_repository = api_jobs
    api.operation_execution_repository = api_execution
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Operator"
    try:
        api_job = _operation_job(api_jobs, intake_id="api-operation", opened_at=NOW - timedelta(hours=2))
        api_snapshot = api.update_mina_job_operation(
            api_job.job_id,
            api.OperationExecutionUpdateRequest(current_location="Edirne", current_eta=NOW + timedelta(hours=8)),
            request,
        )
        api_incident = api.create_mina_job_exception(
            api_job.job_id,
            api.OperationExceptionCreateRequest(
                entry_id="api-exception", exception_type="border_congestion",
                impact_level="delivery_risk", cause="API congestion",
                source_type="operator", reported_at=NOW,
            ),
            request,
        )
        api_view = api.get_mina_job_operation(api_job.job_id)
        api_resolved = api.resolve_mina_job_exception(
            api_job.job_id, api_incident["exception_id"],
            api.OperationExceptionResolveRequest(resolution_note="API resolved."), request,
        )
    finally:
        api.mina_job_repository = original_jobs
        api.operation_execution_repository = original_execution
    check(
        api_snapshot["current_location"] == "Edirne"
        and api_view["open_exception_count"] == 1
        and api_resolved["status"] == "resolved",
        "operation execution and exception APIs use authenticated durable domain services",
    )

    from src.core.mina_job import MinaJob
    legacy_jobs = InMemoryMinaJobRepository()
    legacy = MinaJob(
        mina_code="MINA2026/99", sequence_year=2026, sequence_number=99,
        lifecycle_version=1, job_kind="price_request", intake_channel="email",
        source_proposal_id="legacy-proposal", shipment=_shipment("Legacy Customer"),
        stage="in_transit", opened_by="Legacy", opened_at=NOW - timedelta(days=2),
        updated_at=NOW - timedelta(hours=1),
    )
    legacy_jobs._store_new_job(legacy)
    legacy_delivered = transition_mina_job_stage(
        repository=legacy_jobs, mina_code=legacy.mina_code, target_stage="delivered",
        actor="Legacy", occurred_at=NOW, operation_execution_repository=InMemoryOperationExecutionRepository(),
    )
    check(
        legacy_delivered.stage == "delivered" and legacy_delivered.is_closed,
        "lifecycle v1 delivery remains backward compatible without v2 execution evidence",
    )

    check(
        route_allowed("GET", "/mina-jobs/job-1/operation")
        and route_allowed("POST", "/mina-jobs/job-1/operation")
        and route_allowed("GET", "/mina-jobs/job-1/exceptions")
        and route_allowed("POST", "/mina-jobs/job-1/exceptions")
        and route_allowed("POST", "/mina-jobs/job-1/exceptions/exception-1")
        and route_allowed("POST", "/mina-jobs/job-1/exceptions/exception-1/resolve"),
        "pilot access explicitly allows controlled operation execution and exception surfaces",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_operation_execution_exception_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nOperation execution & exception regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
