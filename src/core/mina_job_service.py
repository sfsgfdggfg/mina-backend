from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.core.mina_job import MinaJob, MinaJobEvent, MinaJobStage
from src.core.mina_job_repository import MinaJobRepository
from src.core.models import Shipment
from src.core.sqlite_repositories import atomic_repository_transaction

ISTANBUL = ZoneInfo("Europe/Istanbul")


class MinaJobNotFoundError(ValueError):
    pass


class MinaJobTransitionError(ValueError):
    pass


_ALLOWED_STAGE_TRANSITIONS: dict[str, set[str]] = {
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


def aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


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
) -> MinaJob:
    timestamp = aware_utc(opened_at)
    sequence_year = timestamp.astimezone(ISTANBUL).year
    with atomic_repository_transaction(repository):
        job, created = repository.create_for_proposal(
            proposal_id=proposal_id,
            shipment=shipment,
            opened_by=opened_by.strip(),
            opened_at=timestamp,
            sequence_year=sequence_year,
        )
        if created:
            _append_event(
                repository,
                job,
                event_type="job_created",
                occurred_at=timestamp,
                actor=opened_by.strip(),
                resource_type="extraction_proposal",
                resource_id=proposal_id,
                metadata={"stage": job.stage},
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
        stage = "quote_ready" if job.stage in {"inquiry_confirmed", "pricing"} else job.stage
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
    occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("Operator identity is required.")
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, mina_code=mina_code)
        if job.is_closed:
            raise MinaJobTransitionError(
                "Closed MINA job automation overrides cannot be changed."
            )
        overrides = job.automation_overrides.model_copy(update={
            "disable_supplier_reminders": disable_supplier_reminders,
            "disable_customer_deadline_updates": disable_customer_deadline_updates,
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
            },
        )
        return updated


def transition_mina_job_stage(
    *, repository: MinaJobRepository, mina_code: str,
    target_stage: MinaJobStage, actor: str, reason: str | None = None,
    occurred_at: datetime | None = None,
) -> MinaJob:
    timestamp = aware_utc(occurred_at)
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("Operator identity is required.")
    normalized_reason = (reason or "").strip() or None
    if target_stage in {"lost", "cancelled"} and normalized_reason is None:
        raise ValueError("Lost/cancelled MINA jobs require a reason.")
    with atomic_repository_transaction(repository):
        job = get_mina_job_or_raise(repository, mina_code=mina_code)
        if target_stage == job.stage:
            return job
        if target_stage not in _ALLOWED_STAGE_TRANSITIONS[job.stage]:
            raise MinaJobTransitionError(
                f"MINA job cannot transition from {job.stage} to {target_stage}."
            )
        closed_at = timestamp if target_stage in {"delivered", "lost", "cancelled"} else None
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
