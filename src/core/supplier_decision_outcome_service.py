from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.mina_job_service import MinaJobNotFoundError, MinaJobTransitionError
from src.core.operation_execution_repository import OperationExecutionRepository
from src.core.quote_case import SupplierDecisionOutcomeFeedback
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.sqlite_repositories import atomic_repository_transaction

ISTANBUL = ZoneInfo("Europe/Istanbul")


class SupplierDecisionOutcomeConflictError(ValueError):
    pass


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _subjective_signature(item: SupplierDecisionOutcomeFeedback) -> tuple:
    return (
        item.entry_id,
        item.overall_outcome,
        item.communication_quality,
        item.would_choose_again,
        item.note or None,
        item.recorded_by,
    )


def record_supplier_decision_outcome(
    *,
    mina_repository: MinaJobRepository,
    quote_case_repository: QuoteCaseRepository,
    execution_repository: OperationExecutionRepository,
    job_id: str,
    entry_id: str,
    overall_outcome: str,
    communication_quality: str,
    would_choose_again: str,
    recorded_by: str,
    note: str | None = None,
    occurred_at: datetime | None = None,
) -> SupplierDecisionOutcomeFeedback:
    timestamp = occurred_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Supplier outcome timestamp must be timezone-aware.")
    actor = recorded_by.strip()
    if not actor:
        raise ValueError("Supplier outcome operator identity is required.")
    normalized_entry = entry_id.strip()
    if not normalized_entry:
        raise ValueError("Supplier outcome entry_id is required.")
    normalized_note = (note or "").strip() or None

    with atomic_repository_transaction(mina_repository, quote_case_repository, execution_repository):
        job = mina_repository.get(job_id)
        if job is None:
            raise MinaJobNotFoundError(f"MINA job not found: {job_id}")
        if job.lifecycle_version != 2 or job.stage != "completed":
            raise MinaJobTransitionError(
                "Supplier decision outcome can be recorded only after a lifecycle-v2 job is completed."
            )
        if not job.quote_case_id:
            raise SupplierDecisionOutcomeConflictError("Completed job has no quote case.")
        quote_case = quote_case_repository.get(job.quote_case_id)
        if quote_case is None:
            raise SupplierDecisionOutcomeConflictError("Quote case is unavailable for supplier outcome feedback.")
        decision = quote_case.supplier_quote_selection_decision
        if decision is None or quote_case.supplier_quote is None:
            raise SupplierDecisionOutcomeConflictError("Supplier selection evidence is unavailable.")
        if quote_case.supplier_quote.supplier_name != decision.selected_supplier:
            raise SupplierDecisionOutcomeConflictError("Supplier quote and selection decision disagree.")
        snapshot = execution_repository.get_snapshot(job.job_id)
        if snapshot is None or snapshot.delivered_at is None:
            raise SupplierDecisionOutcomeConflictError("Completed job lacks durable delivery evidence.")
        exceptions = execution_repository.list_exceptions(job.job_id)
        if any(item.status == "open" for item in exceptions):
            raise SupplierDecisionOutcomeConflictError("Completed job still has open operation exceptions.")

        required = _parse_date(job.shipment.required_delivery_date)
        delivered_date = snapshot.delivered_at.astimezone(ISTANBUL).date()
        on_time = None if required is None else delivered_date <= required
        feedback = SupplierDecisionOutcomeFeedback(
            entry_id=normalized_entry,
            job_id=job.job_id,
            case_id=quote_case.case_id,
            supplier_name=decision.selected_supplier,
            engine_recommended_supplier=decision.engine_recommended_supplier,
            override_applied=decision.override_applied,
            override_reason_category=decision.override_reason_category,
            overall_outcome=overall_outcome,
            communication_quality=communication_quality,
            would_choose_again=would_choose_again,
            delivered_at=snapshot.delivered_at,
            required_delivery_date=job.shipment.required_delivery_date,
            on_time_delivery=on_time,
            operation_exception_count=len(exceptions),
            actual_delay_count=sum(item.impact_level == "actual_delay" for item in exceptions),
            damage_exception_count=sum(item.exception_type == "damage" for item in exceptions),
            operation_exception_ids=[item.exception_id for item in exceptions],
            operation_snapshot_updated_at=snapshot.updated_at,
            recorded_by=actor,
            recorded_at=timestamp.astimezone(timezone.utc),
            note=normalized_note,
        )
        existing = quote_case.supplier_decision_outcome_feedback
        if existing is not None:
            if _subjective_signature(existing) == _subjective_signature(feedback):
                return existing
            raise SupplierDecisionOutcomeConflictError(
                "Supplier decision outcome feedback already exists for this quote case."
            )

        saved_case = quote_case_repository.save(quote_case.model_copy(update={
            "supplier_decision_outcome_feedback": feedback,
            "updated_at": timestamp.astimezone(timezone.utc),
        }))
        saved = saved_case.supplier_decision_outcome_feedback
        assert saved is not None
        mina_repository.append_event(MinaJobEvent(
            job_id=job.job_id,
            mina_code=job.mina_code,
            event_type="supplier_decision_outcome_recorded",
            occurred_at=timestamp.astimezone(timezone.utc),
            actor=actor,
            resource_type="supplier_decision_outcome_feedback",
            resource_id=saved.feedback_id,
            metadata={
                "supplier_name": saved.supplier_name,
                "engine_recommended_supplier": saved.engine_recommended_supplier,
                "override_applied": saved.override_applied,
                "overall_outcome": saved.overall_outcome,
                "on_time_delivery": saved.on_time_delivery,
                "actual_delay_count": saved.actual_delay_count,
                "damage_exception_count": saved.damage_exception_count,
            },
        ))
        return saved
