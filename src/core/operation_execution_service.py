from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import MinaJobNotFoundError, MinaJobTransitionError
from src.core.operation_execution import OperationException, OperationExecutionSnapshot
from src.core.operation_execution_repository import OperationExecutionRepository
from src.core.sqlite_repositories import atomic_repository_transaction


OPERATION_ACTIVE_STAGES = {
    "operation_opened", "supplier_confirmation_pending", "vehicle_details_pending",
    "vehicle_assigned", "pre_loading_check", "ready_for_loading", "loaded", "in_transit",
    "delivery", "delivered", "pod_cmr_pending", "closing_review",
}
EXECUTION_UPDATE_FIELDS = {
    "supplier_confirmed_at", "vehicle_plate", "driver_name", "driver_phone",
    "vehicle_assigned_at", "loading_appointment_at", "loaded_at", "current_location",
    "current_eta", "delivery_appointment_at", "delivered_at", "pod_received_at",
    "cmr_received_at",
}
EXCEPTION_UPDATE_FIELDS = {
    "exception_type", "impact_level", "cause", "location", "old_eta", "new_eta",
    "customer_impact_summary", "next_action", "source_type", "source_reference", "reported_at",
}


def _aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Operation execution timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _operation_job(repository: MinaJobRepository, job_id: str, *, allow_closed: bool = False):
    job = repository.get(job_id)
    if job is None:
        raise MinaJobNotFoundError(f"MINA job not found: {job_id}")
    if job.lifecycle_version != 2:
        raise MinaJobTransitionError("Structured operation execution requires MINA lifecycle v2.")
    if job.is_closed and not allow_closed:
        raise MinaJobTransitionError("Closed MINA jobs cannot receive operation execution updates.")
    if not job.is_closed and job.stage not in OPERATION_ACTIVE_STAGES:
        raise MinaJobTransitionError(
            f"Operation execution is not open while MINA job is in stage {job.stage}."
        )
    return job


def _append_event(
    *, mina_repository: MinaJobRepository, job, event_type: str, occurred_at: datetime,
    actor: str, resource_type: str, resource_id: str, metadata: dict[str, Any],
) -> None:
    mina_repository.append_event(MinaJobEvent(
        job_id=job.job_id, mina_code=job.mina_code, event_type=event_type,
        occurred_at=occurred_at, actor=actor, resource_type=resource_type,
        resource_id=resource_id, metadata=metadata,
    ))


def update_operation_execution(
    *, execution_repository: OperationExecutionRepository,
    mina_repository: MinaJobRepository, job_id: str, updated_by: str,
    changes: dict[str, Any], occurred_at: datetime | None = None,
) -> OperationExecutionSnapshot:
    timestamp = _aware_utc(occurred_at)
    actor = _actor(updated_by)
    unsupported = set(changes) - EXECUTION_UPDATE_FIELDS
    if unsupported:
        raise ValueError(f"Unsupported operation execution fields: {sorted(unsupported)}")
    if not changes:
        raise ValueError("At least one operation execution field must be supplied.")
    with atomic_repository_transaction(execution_repository, mina_repository):
        job = _operation_job(mina_repository, job_id)
        current = execution_repository.get_snapshot(job.job_id)
        payload = (
            {"job_id": job.job_id, "mina_code": job.mina_code}
            if current is None else current.model_dump()
        )
        payload.update(changes)
        payload.update({"updated_at": timestamp, "updated_by": actor})
        snapshot = OperationExecutionSnapshot.model_validate(payload)
        saved = execution_repository.save_snapshot(snapshot)
        _append_event(
            mina_repository=mina_repository, job=job,
            event_type="operation_execution_updated", occurred_at=timestamp, actor=actor,
            resource_type="operation_execution_snapshot", resource_id=job.job_id,
            metadata={"changed_fields": sorted(changes), "stage": job.stage},
        )
        return saved


def create_operation_exception(
    *, execution_repository: OperationExecutionRepository,
    mina_repository: MinaJobRepository, job_id: str, entry_id: str,
    exception_type: str, impact_level: str, cause: str, source_type: str,
    created_by: str, reported_at: datetime | None = None, occurred_at: datetime | None = None,
    location: str | None = None, old_eta: datetime | None = None,
    new_eta: datetime | None = None, customer_impact_summary: str | None = None,
    next_action: str | None = None, source_reference: str | None = None,
) -> OperationException:
    timestamp = _aware_utc(occurred_at)
    actor = _actor(created_by)
    normalized_entry_id = entry_id.strip()
    if not normalized_entry_id:
        raise ValueError("Operation exception entry_id is required.")
    with atomic_repository_transaction(execution_repository, mina_repository):
        job = _operation_job(mina_repository, job_id)
        existing = execution_repository.find_exception_by_entry_id(normalized_entry_id)
        report_time = _aware_utc(
            reported_at if reported_at is not None
            else (existing.reported_at if existing is not None else timestamp)
        )
        incident = OperationException(
            entry_id=normalized_entry_id, job_id=job.job_id, mina_code=job.mina_code,
            stage_at_report=(job.stage if existing is None else existing.stage_at_report),
            exception_type=exception_type, impact_level=impact_level,
            cause=cause, location=location, old_eta=old_eta, new_eta=new_eta,
            customer_impact_summary=customer_impact_summary, next_action=next_action,
            source_type=source_type, source_reference=source_reference,
            reported_at=report_time,
            created_at=(timestamp if existing is None else existing.created_at),
            created_by=(actor if existing is None else existing.created_by),
            updated_at=(timestamp if existing is None else existing.updated_at),
            updated_by=(actor if existing is None else existing.updated_by),
        )
        saved, created = execution_repository.create_exception(incident)
        if created:
            _append_event(
                mina_repository=mina_repository, job=job,
                event_type="operation_exception_created", occurred_at=timestamp, actor=actor,
                resource_type="operation_exception", resource_id=saved.exception_id,
                metadata={
                    "exception_type": saved.exception_type, "impact_level": saved.impact_level,
                    "stage_at_report": saved.stage_at_report,
                    "customer_attention_recommended": saved.customer_attention_recommended,
                },
            )
        return saved


def update_operation_exception(
    *, execution_repository: OperationExecutionRepository,
    mina_repository: MinaJobRepository, job_id: str, exception_id: str,
    updated_by: str, changes: dict[str, Any], occurred_at: datetime | None = None,
) -> OperationException:
    timestamp = _aware_utc(occurred_at)
    actor = _actor(updated_by)
    unsupported = set(changes) - EXCEPTION_UPDATE_FIELDS
    if unsupported:
        raise ValueError(f"Unsupported operation exception fields: {sorted(unsupported)}")
    if not changes:
        raise ValueError("At least one exception field must be supplied.")
    with atomic_repository_transaction(execution_repository, mina_repository):
        job = _operation_job(mina_repository, job_id)
        current = execution_repository.get_exception(exception_id)
        if current is None or current.job_id != job.job_id:
            raise KeyError(exception_id)
        if current.status != "open":
            raise MinaJobTransitionError("Resolved operation exceptions cannot be edited.")
        payload = current.model_dump(exclude_computed_fields=True)
        payload.update(changes)
        payload.update({"updated_at": timestamp, "updated_by": actor})
        updated = OperationException.model_validate(payload)
        saved = execution_repository.save_exception(updated)
        _append_event(
            mina_repository=mina_repository, job=job,
            event_type="operation_exception_updated", occurred_at=timestamp, actor=actor,
            resource_type="operation_exception", resource_id=saved.exception_id,
            metadata={"changed_fields": sorted(changes), "impact_level": saved.impact_level},
        )
        return saved


def resolve_operation_exception(
    *, execution_repository: OperationExecutionRepository,
    mina_repository: MinaJobRepository, job_id: str, exception_id: str,
    resolved_by: str, resolution_note: str, occurred_at: datetime | None = None,
) -> OperationException:
    timestamp = _aware_utc(occurred_at)
    actor = _actor(resolved_by)
    note = resolution_note.strip()
    if not note:
        raise ValueError("Exception resolution note is required.")
    with atomic_repository_transaction(execution_repository, mina_repository):
        job = _operation_job(mina_repository, job_id, allow_closed=True)
        current = execution_repository.get_exception(exception_id)
        if current is None or current.job_id != job.job_id:
            raise KeyError(exception_id)
        if current.status == "resolved":
            return current
        updated = OperationException.model_validate(current.model_copy(update={
            "status": "resolved", "resolved_at": timestamp, "resolved_by": actor,
            "resolution_note": note, "updated_at": timestamp, "updated_by": actor,
        }).model_dump(exclude_computed_fields=True))
        saved = execution_repository.save_exception(updated)
        _append_event(
            mina_repository=mina_repository, job=job,
            event_type="operation_exception_resolved", occurred_at=timestamp, actor=actor,
            resource_type="operation_exception", resource_id=saved.exception_id,
            metadata={"impact_level": saved.impact_level, "exception_type": saved.exception_type},
        )
        return saved


def build_operation_execution_view(
    *, execution_repository: OperationExecutionRepository,
    mina_repository: MinaJobRepository, job_id: str,
) -> dict[str, Any]:
    job = mina_repository.get(job_id)
    if job is None:
        raise MinaJobNotFoundError(f"MINA job not found: {job_id}")
    snapshot = execution_repository.get_snapshot(job.job_id)
    exceptions = execution_repository.list_exceptions(job.job_id)
    open_items = [item for item in exceptions if item.status == "open"]
    impact_counts = {"deviation": 0, "delivery_risk": 0, "actual_delay": 0}
    for item in open_items:
        impact_counts[item.impact_level] += 1
    return {
        "job_id": job.job_id, "mina_code": job.mina_code, "stage": job.stage,
        "snapshot": None if snapshot is None else snapshot.model_dump(),
        "exceptions": [item.model_dump() for item in exceptions],
        "open_exception_count": len(open_items),
        "open_impact_counts": impact_counts,
        "customer_attention_recommended": any(
            item.customer_attention_recommended for item in open_items
        ),
    }


def validate_operation_transition_evidence(
    *, execution_repository: OperationExecutionRepository,
    job_id: str, target_stage: str,
) -> None:
    snapshot = execution_repository.get_snapshot(job_id)
    if target_stage == "vehicle_assigned":
        if snapshot is None or snapshot.vehicle_assigned_at is None or not snapshot.vehicle_plate or not snapshot.driver_name:
            raise MinaJobTransitionError(
                "Vehicle-assigned stage requires durable plate, driver and assignment-time evidence."
            )
    if target_stage == "loaded":
        if snapshot is None or snapshot.loaded_at is None:
            raise MinaJobTransitionError("Loaded stage requires durable loaded_at evidence.")
    if target_stage == "delivered":
        if snapshot is None or snapshot.delivered_at is None:
            raise MinaJobTransitionError("Delivered stage requires durable delivered_at evidence.")
    if target_stage in {"closing_review", "completed"}:
        if snapshot is None or snapshot.delivered_at is None:
            raise MinaJobTransitionError("Closing review requires durable delivery evidence.")
        if snapshot.pod_received_at is None and snapshot.cmr_received_at is None:
            raise MinaJobTransitionError("Closing review requires POD or CMR receipt evidence.")
    if target_stage == "completed":
        open_exceptions = [
            item for item in execution_repository.list_exceptions(job_id)
            if item.status == "open"
        ]
        if open_exceptions:
            raise MinaJobTransitionError("MINA job cannot complete while operation exceptions remain open.")
