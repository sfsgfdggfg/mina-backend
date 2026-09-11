from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.sqlite_repositories import atomic_repository_transaction
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.core.supplier_selection_feedback import (
    SelectionFeedbackReason,
    SelectionFeedbackVerdict,
    SupplierSelectionFeedbackEvidence,
)
from src.core.supplier_selection_feedback_repository import SupplierSelectionFeedbackRepository


def _aware_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Selection feedback timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _actor(value: str) -> str:
    actor = value.strip()
    if not actor:
        raise ValueError("Selection feedback requires an authenticated operator.")
    return actor


def _snapshot_sha256(draft) -> str:
    if draft.selection_explanation is None:
        raise ValueError("Selection feedback requires a durable selection explanation snapshot.")
    payload = draft.selection_explanation.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_supplier_selection_feedback(
    *, feedback_repository: SupplierSelectionFeedbackRepository,
    mina_repository: MinaJobRepository, supplier_repository: SupplierRFQRepository,
    job_id: str, rfq_id: str, entry_id: str, verdict: SelectionFeedbackVerdict,
    reason_code: SelectionFeedbackReason, note: str | None, recorded_by: str,
    recorded_at: datetime | None = None,
) -> SupplierSelectionFeedbackEvidence:
    timestamp = _aware_utc(recorded_at)
    actor = _actor(recorded_by)
    normalized_entry = entry_id.strip()
    if not normalized_entry:
        raise ValueError("Selection feedback entry_id is required.")
    with atomic_repository_transaction(feedback_repository, mina_repository):
        job = mina_repository.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.is_closed:
            raise ValueError("Closed MINA jobs do not accept new supplier selection feedback.")
        if not job.supplier_rfq_workflow_id:
            raise ValueError("MINA job has no supplier RFQ workflow.")
        draft = supplier_repository.get_draft(rfq_id)
        if draft is None:
            raise LookupError(rfq_id)
        if draft.workflow_id != job.supplier_rfq_workflow_id:
            raise ValueError("Supplier RFQ does not belong to this MINA job workflow.")
        explanation = draft.selection_explanation
        snapshot_hash = _snapshot_sha256(draft)
        evidence = SupplierSelectionFeedbackEvidence(
            entry_id=normalized_entry, mina_job_id=job.job_id, mina_code=job.mina_code,
            workflow_id=draft.workflow_id, rfq_id=draft.rfq_id, supplier_name=draft.supplier_name,
            selection_priority=explanation.selection_rank, verdict=verdict, reason_code=reason_code,
            note=(note or "").strip() or None, selection_snapshot_sha256=snapshot_hash,
            recorded_by=actor, recorded_at=timestamp,
        )
        saved, created = feedback_repository.create(evidence)
        if created:
            mina_repository.append_event(MinaJobEvent(
                job_id=job.job_id, mina_code=job.mina_code,
                event_type="supplier_selection_feedback_recorded", occurred_at=timestamp, actor=actor,
                resource_type="supplier_selection_feedback", resource_id=saved.feedback_id,
                metadata={
                    "rfq_id": draft.rfq_id, "supplier_name": draft.supplier_name,
                    "selection_priority": explanation.selection_rank, "verdict": verdict,
                    "reason_code": reason_code, "selection_snapshot_sha256": snapshot_hash,
                },
            ))
        return saved
