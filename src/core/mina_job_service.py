from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.core.mina_job import (
    MinaJob,
    MinaJobEvent,
    MinaJobIntakeChannel,
    MinaJobKind,
    MinaJobStage,
    V1_TERMINAL_MINA_JOB_STAGES,
    V2_TERMINAL_MINA_JOB_STAGES,
)
from src.core.mina_job_repository import MinaJobRepository
from src.core.models import Shipment
from src.core.sqlite_repositories import atomic_repository_transaction

ISTANBUL = ZoneInfo("Europe/Istanbul")


class MinaJobNotFoundError(ValueError):
    pass


class MinaJobTransitionError(ValueError):
    pass


_V1_ALLOWED_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "inquiry_confirmed": {"pricing", "lost", "cancelled"},
    "pricing": {"quote_ready", "lost", "cancelled"},
    "quote_ready": {"quote_sent", "lost", "cancelled"},
    "quote_sent": {"negotiation", "accepted", "lost", "cancelled"},
    "negotiation": {"quote_sent", "accepted", "lost", "cancelled"},
    "accepted": {"operations", "cancelled"},
    "operations": {"in_transit", "cancelled"},
    "in_transit": {"delivered", "cancelled"},
    "delivered": set(),
    "lost": set(),
    "cancelled": set(),
}

_V2_BASE_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "inquiry_confirmed": {"pricing", "lost", "cancelled"},
    "pricing": set(),
    "quote_ready": {"quote_sent", "lost", "cancelled"},
    "quote_sent": {"negotiation", "accepted", "lost", "cancelled"},
    "negotiation": {"quote_sent", "accepted", "lost", "cancelled"},
    "accepted": {"operation_opened", "cancelled"},
    "operation_opened": {"supplier_confirmation_pending", "cancelled"},
    "supplier_confirmation_pending": {"vehicle_details_pending", "cancelled"},
    "vehicle_details_pending": {"vehicle_assigned", "cancelled"},
    "vehicle_assigned": {"pre_loading_check", "cancelled"},
    "pre_loading_check": {"ready_for_loading", "cancelled"},
    "ready_for_loading": {"loaded", "cancelled"},
    "loaded": {"in_transit", "cancelled"},
    "in_transit": {"delivery", "cancelled"},
    "delivery": {"delivered", "cancelled"},
    "delivered": {"pod_cmr_pending"},
    "pod_cmr_pending": {"closing_review"},
    "closing_review": {"completed"},
    "completed": set(),
    "lost": set(),
    "cancelled": set(),
}

_STAGE_ORDER = [
    "inquiry_confirmed", "pricing", "quote_ready", "quote_sent", "negotiation",
    "accepted", "operations", "operation_opened", "supplier_confirmation_pending",
    "vehicle_details_pending", "vehicle_assigned", "pre_loading_check",
    "ready_for_loading", "loaded", "in_transit", "delivery", "delivered",
    "pod_cmr_pending", "closing_review", "completed", "lost", "cancelled",
]
_STAGE_ORDER_INDEX = {stage: index for index, stage in enumerate(_STAGE_ORDER)}


def aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _normalized_actor(actor: str) -> str:
    normalized = actor.strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _sorted_stages(stages: set[str]) -> list[MinaJobStage]:
    return [
        stage  # type: ignore[list-item]
        for stage in sorted(stages, key=lambda item: _STAGE_ORDER_INDEX.get(item, 999))
    ]


def allowed_next_stages(job: MinaJob) -> list[MinaJobStage]:
    if job.lifecycle_version == 1:
        return _sorted_stages(_V1_ALLOWED_STAGE_TRANSITIONS.get(job.stage, set()))

    stages = set(_V2_BASE_STAGE_TRANSITIONS.get(job.stage, set()))
    if job.stage == "pricing":
        if job.job_kind == "approved_job":
            stages.update({"operation_opened", "lost", "cancelled"})
        else:
            stages.update({"quote_ready", "lost", "cancelled"})
    return _sorted_stages(stages)


def _terminal_stages(job: MinaJob) -> set[str]:
    return (
        V1_TERMINAL_MINA_JOB_STAGES
        if job.lifecycle_version == 1
        else V2_TERMINAL_MINA_JOB_STAGES
    )


def _append_event(
    repository: MinaJobRepository,
    job: MinaJob,
    *,
    event_type: str,
    occurred_at: datetime,
    actor: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> MinaJobEvent:
    return repository.append_event(
        MinaJobEvent(
            job_id=job.job_id,
            mina_code=job.mina_code,
            event_type=event_type,
            occurred_at=aware_utc(occurred_at),
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            metadata=metadata or {},
        )
    )


def create_mina_job_for_confirmed_proposal(
    *, repository: MinaJobRepository, proposal_id: str,
    shipment: Shipment, opened_by: str, opened_at: datetime,
    job_kind: MinaJobKind = "price_request",
    sales_owner: str | None = None,
    operations_owner: str | None = None,
) -> MinaJob:
    timestamp = aware_utc(opened_at)
    sequence_year = timestamp.astimezone(ISTANBUL).year
    actor = _normalized_actor(opened_by)
    with atomic_repository_transaction(repository):
        job, created = repository.create_for_proposal(
            proposal_id=proposal_id,
            shipment=shipment,
            opened_by=actor,
            opened_at=timestamp,
            sequence_year=sequence_year,
            lifecycle_version=2,
            job_kind=job_kind,
            sales_owner=sales_owner,
            operations_owner=operations_owner,
        )
        if created:
            _append_event(
                repository,
                job,
                event_type="job_created",
                occurred_at=timestamp,
                actor=actor,
                resource_type="extraction_proposal",
                resource_id=proposal_id,
                metadata={
                    "stage": job.stage,
                    "lifecycle_version": job.lifecycle_version,
                    "job_kind": job.job_kind,
                    "intake_channel": job.intake_channel,
                },
            )
        return job


def create_manual_mina_job(
    *, repository: MinaJobRepository, manual_intake_id: str,
    intake_channel: MinaJobIntakeChannel, job_kind: MinaJobKind,
    shipment: Shipment, opened_by: str, opened_at: datetime | None = None,
    sales_owner: str | None = None,
    operations_owner: str | None = None,
) -> MinaJob:
    timestamp = aware_utc(opened_at)
    sequence_year = timestamp.astimezone(ISTANBUL).year
    actor = _normalized_actor(opened_by)
    normalized_intake_id = manual_intake_id.strip()
    if not normalized_intake_id:
        raise ValueError("manual_intake_id is required.")
    with atomic_repository_transaction(repository):
        job, created = repository.create_manual(
            manual_intake_id=normalized_intake_id,
            intake_channel=intake_channel,
            job_kind=job_kind,
            shipment=shipment,
            opened_by=actor,
            opened_at=timestamp,
            sequence_year=sequence_year,
            lifecycle_version=2,
            sales_owner=sales_owner,
            operations_owner=operations_owner,
        )
        if created:
            _append_event(
                repository,
                job,
                event_type="job_created",
                occurred_at=timestamp,
                actor=actor,
                resource_type="manual_intake",
                resource_id=normalized_intake_id,
                metadata={
                    "stage": job.stage,
                    "lifecycle_version": job.lifecycle_version,
                    "job_kind": job.job_kind,
                    "intake_channel": job.intake_channel,
                },
            )
        return job


def get_mina_job_or_raise(
    repository: MinaJobRepository,
    *,
    job_id: str | None = None,
    mina_code: str | None = None,
) -> MinaJob:
    job = repository.get(job_id) if job_id else None
    if job is None and mina_code:
        job = repository.get_by_code(mina_code)
    if job is None:
        reference = mina_code or job_id or "unknown"
        raise MinaJobNotFoundError(f"MINA job not found: {reference}")
    return job


def link_mina_job_workflow(
    *, repository: MinaJobRepository, job_id: str,
    workflow_id: str, result_type: str, occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, job_id=job_id)
        target_stage = "pricing" if job.stage == "inquiry_confirmed" else job.stage
        updated = MinaJob.model_validate(job.model_copy(update={
            "supplier_rfq_workflow_id": workflow_id,
            "stage": target_stage,
            "updated_at": timestamp,
        }).model_dump())
        updated = repository.save(updated)
        _append_event(
            repository,
            updated,
            event_type="supplier_workflow_linked",
            occurred_at=timestamp,
            resource_type="supplier_rfq_workflow",
            resource_id=workflow_id,
            metadata={"result_type": result_type, "stage": updated.stage},
        )
        return updated


def record_mina_job_resume_result(
    *, repository: MinaJobRepository, job_id: str,
    result_type: str, occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, job_id=job_id)
        updated = MinaJob.model_validate(
            job.model_copy(update={"updated_at": timestamp}).model_dump()
        )
        updated = repository.save(updated)
        _append_event(
            repository,
            updated,
            event_type="workflow_result_recorded",
            occurred_at=timestamp,
            metadata={"result_type": result_type, "stage": updated.stage},
        )
        return updated


def link_mina_job_quote_case(
    *, repository: MinaJobRepository, job_id: str, quote_case_id: str,
    occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, job_id=job_id)
        stage = job.stage
        if job.job_kind == "price_request" and job.stage in {"inquiry_confirmed", "pricing"}:
            stage = "quote_ready"
        updated = MinaJob.model_validate(job.model_copy(update={
            "quote_case_id": quote_case_id,
            "stage": stage,
            "updated_at": timestamp,
        }).model_dump())
        updated = repository.save(updated)
        _append_event(
            repository,
            updated,
            event_type="quote_case_linked",
            occurred_at=timestamp,
            resource_type="quote_case",
            resource_id=quote_case_id,
            metadata={"stage": updated.stage},
        )
        return updated


def set_mina_job_automation_overrides(
    *, repository: MinaJobRepository, mina_code: str, actor: str,
    disable_supplier_reminders: bool,
    disable_customer_deadline_updates: bool,
    supplier_reminder_mode=None,
    customer_deadline_update_mode=None,
    occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    normalized_actor = _normalized_actor(actor)
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, mina_code=mina_code)
        if job.is_closed:
            raise MinaJobTransitionError(
                "Closed MINA job automation overrides cannot be changed."
            )
        overrides = job.automation_overrides.model_copy(update={
            "disable_supplier_reminders": disable_supplier_reminders,
            "disable_customer_deadline_updates": disable_customer_deadline_updates,
            "supplier_reminder_mode": supplier_reminder_mode,
            "customer_deadline_update_mode": customer_deadline_update_mode,
        })
        updated = MinaJob.model_validate(job.model_copy(update={
            "automation_overrides": overrides,
            "updated_at": timestamp,
        }).model_dump())
        updated = repository.save(updated)
        _append_event(
            repository,
            updated,
            event_type="automation_override_changed",
            occurred_at=timestamp,
            actor=normalized_actor,
            metadata={
                "disable_supplier_reminders": disable_supplier_reminders,
                "disable_customer_deadline_updates": disable_customer_deadline_updates,
                "supplier_reminder_mode": supplier_reminder_mode,
                "customer_deadline_update_mode": customer_deadline_update_mode,
            },
        )
        return updated


def set_mina_job_owners(
    *, repository: MinaJobRepository, mina_code: str, actor: str,
    sales_owner: str | None, operations_owner: str | None,
    occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    normalized_actor = _normalized_actor(actor)
    normalized_sales = sales_owner.strip() if sales_owner else None
    normalized_operations = operations_owner.strip() if operations_owner else None
    normalized_sales = normalized_sales or None
    normalized_operations = normalized_operations or None
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, mina_code=mina_code)
        if job.is_closed:
            raise MinaJobTransitionError("Closed MINA job ownership cannot be changed.")
        changes = []
        if job.sales_owner != normalized_sales:
            changes.append(("sales", job.sales_owner, normalized_sales))
        if job.operations_owner != normalized_operations:
            changes.append(("operations", job.operations_owner, normalized_operations))
        if not changes:
            return job
        updated = MinaJob.model_validate(job.model_copy(update={
            "sales_owner": normalized_sales,
            "operations_owner": normalized_operations,
            "updated_at": timestamp,
        }).model_dump())
        updated = repository.save(updated)
        for owner_type, old_value, new_value in changes:
            _append_event(
                repository,
                updated,
                event_type=f"job_{owner_type}_owner_changed",
                occurred_at=timestamp,
                actor=normalized_actor,
                resource_type="mina_job",
                resource_id=updated.job_id,
                metadata={"old_value": old_value, "new_value": new_value},
            )
        return updated


def transition_mina_job_stage(
    *, repository: MinaJobRepository, mina_code: str,
    target_stage: MinaJobStage, actor: str, reason: str | None = None,
    occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    normalized_actor = _normalized_actor(actor)
    normalized_reason = (reason or "").strip() or None
    if target_stage in {"lost", "cancelled"} and normalized_reason is None:
        raise ValueError("Lost/cancelled MINA jobs require a reason.")
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, mina_code=mina_code)
        if target_stage == job.stage:
            return job
        allowed = allowed_next_stages(job)
        if target_stage not in allowed:
            raise MinaJobTransitionError(
                f"MINA job cannot transition from {job.stage} to {target_stage}."
            )
        closed_at = timestamp if target_stage in _terminal_stages(job) else None
        updated = MinaJob.model_validate(job.model_copy(update={
            "stage": target_stage,
            "updated_at": timestamp,
            "closed_at": closed_at,
        }).model_dump())
        updated = repository.save(updated)
        _append_event(
            repository,
            updated,
            event_type="stage_changed",
            occurred_at=timestamp,
            actor=normalized_actor,
            metadata={
                "from_stage": job.stage,
                "to_stage": target_stage,
                "reason": normalized_reason,
                "lifecycle_version": job.lifecycle_version,
            },
        )
        return updated


def supplier_reminders_enabled_for_job(
    *, repository: MinaJobRepository | None,
    job_id: str | None,
    global_enabled: bool,
) -> bool:
    if not global_enabled:
        return False
    if repository is None or not job_id:
        return True
    job = repository.get(job_id)
    if job is None:
        return True
    return not job.automation_overrides.disable_supplier_reminders


def customer_deadline_updates_enabled_for_job(
    *, repository: MinaJobRepository | None,
    job_id: str | None,
    global_enabled: bool,
) -> bool:
    if not global_enabled:
        return False
    if repository is None or not job_id:
        return True
    job = repository.get(job_id)
    if job is None:
        return True
    return not job.automation_overrides.disable_customer_deadline_updates


def record_mina_job_customer_quote_sent(
    *, repository: MinaJobRepository, job_id: str, actor: str,
    revision_number: int, send_mode: str, occurred_at: datetime,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, job_id=job_id)
        if job.stage in {"quote_ready", "negotiation"}:
            job = transition_mina_job_stage(
                repository=repository,
                mina_code=job.mina_code,
                target_stage="quote_sent",
                actor=actor,
                occurred_at=timestamp,
            )
        elif job.stage != "quote_sent":
            raise MinaJobTransitionError(
                f"Customer quote cannot be recorded as sent while job is {job.stage}."
            )
        _append_event(
            repository,
            job,
            event_type="customer_quote_sent",
            occurred_at=timestamp,
            actor=actor,
            resource_type="quote_case",
            resource_id=job.quote_case_id,
            metadata={"revision_number": revision_number, "send_mode": send_mode},
        )
        return repository.save(job.model_copy(update={"updated_at": timestamp}))


def record_mina_job_quote_revision(
    *, repository: MinaJobRepository, job_id: str, actor: str,
    revision_number: int, changed_fields: list[str], occurred_at: datetime,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, job_id=job_id)
        if job.stage == "quote_sent":
            job = transition_mina_job_stage(
                repository=repository,
                mina_code=job.mina_code,
                target_stage="negotiation",
                actor=actor,
                occurred_at=timestamp,
            )
        if job.is_closed:
            raise MinaJobTransitionError("Closed MINA job cannot receive quote revisions.")
        _append_event(
            repository,
            job,
            event_type="quote_revised",
            occurred_at=timestamp,
            actor=actor,
            resource_type="quote_case",
            resource_id=job.quote_case_id,
            metadata={
                "revision_number": revision_number,
                "changed_fields": list(changed_fields),
            },
        )
        return repository.save(job.model_copy(update={"updated_at": timestamp}))
