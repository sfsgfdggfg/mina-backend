from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository

LossReasonCategory = Literal[
    "price", "transit_time", "capacity_availability", "service_scope",
    "customer_cancelled", "competitor_selected", "customer_no_response",
    "timing_deadline", "payment_terms", "relationship_preference",
    "internal_customer_decision", "other", "unknown",
]
LossEvidenceBasis = Literal[
    "customer_explicit", "operator_assessment", "internal_customer_decision", "unknown",
]
LossSourceChannel = Literal[
    "email", "phone", "whatsapp", "portal", "face_to_face", "internal", "other", "unknown",
]


class LossFeedbackConflictError(ValueError):
    pass


class LossFeedbackEvidence(BaseModel):
    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    entry_id: str = Field(min_length=1, max_length=300)
    job_id: str = Field(min_length=1, max_length=100)
    category: LossReasonCategory
    evidence_basis: LossEvidenceBasis
    source_channel: LossSourceChannel
    note: str = Field(min_length=3, max_length=1200)
    competitor_name: str | None = Field(default=None, max_length=240)
    customer_stated_target_price: float | None = Field(default=None, gt=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    supersedes_feedback_id: str | None = Field(default=None, max_length=100)
    recorded_by: str = Field(min_length=1, max_length=200)
    recorded_at: datetime
    source: Literal["customer_loss_feedback_v1"] = "customer_loss_feedback_v1"

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.recorded_at.tzinfo is None:
            raise ValueError("Loss feedback timestamp must be timezone-aware.")
        if self.customer_stated_target_price is not None:
            if self.evidence_basis != "customer_explicit":
                raise ValueError("Customer-stated target price requires explicit customer evidence.")
            if not self.currency:
                raise ValueError("Customer-stated target price requires currency evidence.")
        if self.currency:
            object.__setattr__(self, "currency", self.currency.strip().upper())
        if self.competitor_name:
            object.__setattr__(self, "competitor_name", self.competitor_name.strip() or None)
        return self


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Loss feedback timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def loss_feedback_from_event(event: MinaJobEvent) -> LossFeedbackEvidence | None:
    if event.event_type != "loss_feedback_recorded":
        return None
    payload = event.metadata.get("loss_feedback") if isinstance(event.metadata, dict) else None
    if not isinstance(payload, dict):
        return None
    try:
        return LossFeedbackEvidence.model_validate(payload)
    except ValueError:
        return None


def list_loss_feedback(repository: MinaJobRepository, *, job_id: str) -> list[LossFeedbackEvidence]:
    items = [
        parsed for event in repository.list_events(job_id)
        if (parsed := loss_feedback_from_event(event)) is not None
    ]
    return sorted(items, key=lambda item: (item.recorded_at, item.feedback_id))


def current_loss_feedback(repository: MinaJobRepository, *, job_id: str) -> LossFeedbackEvidence | None:
    items = list_loss_feedback(repository, job_id=job_id)
    if not items:
        return None
    superseded = {item.supersedes_feedback_id for item in items if item.supersedes_feedback_id}
    active = [item for item in items if item.feedback_id not in superseded]
    return active[-1] if active else items[-1]


def _semantic_payload(item: LossFeedbackEvidence) -> dict:
    return item.model_dump(exclude={"feedback_id", "recorded_at", "source"})


def record_loss_feedback(
    *, repository: MinaJobRepository, job_id: str, entry_id: str,
    category: LossReasonCategory, evidence_basis: LossEvidenceBasis,
    source_channel: LossSourceChannel, note: str, recorded_by: str,
    competitor_name: str | None = None, customer_stated_target_price: float | None = None,
    currency: str | None = None, supersedes_feedback_id: str | None = None,
    occurred_at: datetime | None = None,
) -> LossFeedbackEvidence:
    job = repository.get(job_id)
    if job is None:
        raise KeyError(job_id)
    if job.stage != "lost":
        raise LossFeedbackConflictError("Structured loss feedback may be recorded only for a lost MINA job.")
    actor = recorded_by.strip()
    if not actor:
        raise ValueError("Loss feedback operator identity is required.")
    feedback = LossFeedbackEvidence(
        entry_id=entry_id.strip(), job_id=job.job_id, category=category,
        evidence_basis=evidence_basis, source_channel=source_channel, note=note.strip(),
        competitor_name=competitor_name, customer_stated_target_price=customer_stated_target_price,
        currency=currency, supersedes_feedback_id=supersedes_feedback_id,
        recorded_by=actor, recorded_at=_utc(occurred_at),
    )
    history = list_loss_feedback(repository, job_id=job.job_id)
    for existing in history:
        if existing.entry_id != feedback.entry_id:
            continue
        if _semantic_payload(existing) == _semantic_payload(feedback):
            return existing
        raise LossFeedbackConflictError("Loss feedback entry_id already exists with different evidence.")
    current = current_loss_feedback(repository, job_id=job.job_id)
    if current is None:
        if supersedes_feedback_id is not None:
            raise LossFeedbackConflictError("First loss feedback cannot supersede a missing record.")
    elif supersedes_feedback_id != current.feedback_id:
        raise LossFeedbackConflictError(
            "A new loss feedback revision must explicitly supersede the current feedback record."
        )
    repository.append_event(MinaJobEvent(
        job_id=job.job_id, mina_code=job.mina_code, event_type="loss_feedback_recorded",
        occurred_at=feedback.recorded_at, actor=actor, resource_type="loss_feedback",
        resource_id=feedback.feedback_id,
        metadata={"loss_feedback": feedback.model_dump(mode="json")},
    ))
    return feedback


def build_loss_feedback_view(repository: MinaJobRepository, *, job_id: str) -> dict:
    job = repository.get(job_id)
    if job is None:
        raise KeyError(job_id)
    history = list_loss_feedback(repository, job_id=job_id)
    current = current_loss_feedback(repository, job_id=job_id)
    lost_event = next((
        event for event in reversed(repository.list_events(job_id))
        if event.event_type == "stage_changed" and event.metadata.get("to_stage") == "lost"
    ), None)
    return {
        "job_id": job_id,
        "stage": job.stage,
        "recordable": job.stage == "lost",
        "legacy_stage_reason": None if lost_event is None else lost_event.metadata.get("reason"),
        "current": None if current is None else current.model_dump(mode="json"),
        "history": [item.model_dump(mode="json") for item in history],
        "structured_feedback_count": len(history),
        "source": "customer_loss_feedback_view_v1",
    }
