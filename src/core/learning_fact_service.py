from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import LearningFactConflictError, LearningFactRepository
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.sqlite_repositories import atomic_repository_transaction


class LearningFactNotFoundError(KeyError):
    pass


def _aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Learning fact timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _actor(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _validate_subject(
    *, subject_type: str, subject_id: str, master_repository: MasterDataRepository | None,
    mina_repository: MinaJobRepository | None,
) -> None:
    if subject_type == "customer" and master_repository is not None:
        if master_repository.get_customer(subject_id) is None:
            raise ValueError(f"Customer master not found: {subject_id}")
    elif subject_type == "supplier" and master_repository is not None:
        if master_repository.get_supplier(subject_id) is None:
            raise ValueError(f"Supplier master not found: {subject_id}")
    elif subject_type == "operation" and mina_repository is not None:
        if mina_repository.get(subject_id) is None:
            raise ValueError(f"MINA job not found: {subject_id}")


def list_learning_facts(
    *, repository: LearningFactRepository, subject_type: str | None = None,
    subject_id: str | None = None, status: str | None = None,
    runtime_only: bool = False,
) -> list[LearningFact]:
    items = repository.list_all()
    if subject_type is not None:
        items = [item for item in items if item.subject_type == subject_type]
    if subject_id is not None:
        items = [item for item in items if item.subject_id == subject_id]
    if status is not None:
        items = [item for item in items if item.status == status]
    if runtime_only:
        items = [item for item in items if item.runtime_authoritative]
    return sorted(items, key=lambda item: (item.subject_type, item.subject_id, item.fact_key, item.created_at, item.fact_id))


def create_learning_fact(
    *, repository: LearningFactRepository, entry_id: str, subject_type: str, subject_id: str,
    subject_label: str, fact_key: str, value: Any, confidence: float, source_type: str,
    evidence: list[LearningEvidence | dict], created_by: str, value_unit: str | None = None,
    supersedes_fact_id: str | None = None, occurred_at: datetime | None = None,
    master_repository: MasterDataRepository | None = None,
    mina_repository: MinaJobRepository | None = None,
) -> LearningFact:
    timestamp = _aware_utc(occurred_at)
    actor = _actor(created_by)
    normalized_entry = entry_id.strip()
    if not normalized_entry:
        raise ValueError("Learning fact entry_id is required.")
    _validate_subject(
        subject_type=subject_type, subject_id=subject_id,
        master_repository=master_repository, mina_repository=mina_repository,
    )
    normalized_fact_key = fact_key.strip().casefold()
    if supersedes_fact_id:
        old = repository.get(supersedes_fact_id)
        if old is None:
            raise ValueError("Superseded learning fact was not found.")
        if old.status != "confirmed":
            raise ValueError("Only a confirmed learning fact may be superseded.")
        if old.subject_type != subject_type or old.subject_id != subject_id or old.fact_key != normalized_fact_key:
            raise ValueError("Replacement fact must target the same subject and fact key.")
    fact = LearningFact(
        entry_id=normalized_entry, subject_type=subject_type, subject_id=subject_id,
        subject_label=subject_label.strip(), fact_key=normalized_fact_key, value=value,
        value_unit=value_unit, confidence=confidence, source_type=source_type,
        evidence=[item if isinstance(item, LearningEvidence) else LearningEvidence.model_validate(item) for item in evidence],
        supersedes_fact_id=supersedes_fact_id, created_at=timestamp, created_by=actor,
        updated_at=timestamp,
    )
    existing = repository.find_by_entry_id(normalized_entry)
    if existing is not None:
        # Preserve original derived creation evidence on true retries.
        fact = LearningFact.model_validate(fact.model_copy(update={
            "fact_id": existing.fact_id, "created_at": existing.created_at,
            "created_by": existing.created_by, "updated_at": existing.updated_at,
        }).model_dump(exclude_computed_fields=True))
    saved, _ = repository.create(fact)
    return saved


def confirm_learning_fact(
    *, repository: LearningFactRepository, fact_id: str, reviewed_by: str, review_note: str,
    occurred_at: datetime | None = None,
) -> LearningFact:
    timestamp = _aware_utc(occurred_at)
    actor = _actor(reviewed_by)
    note = review_note.strip()
    if not note:
        raise ValueError("Learning fact confirmation note is required.")
    with atomic_repository_transaction(repository):
        current = repository.get(fact_id)
        if current is None:
            raise LearningFactNotFoundError(fact_id)
        if current.status == "confirmed":
            return current
        if current.status != "proposed":
            raise LearningFactConflictError("Only a proposed learning fact may be confirmed.")
        confirmed = [
            item for item in repository.list_all()
            if item.status == "confirmed" and item.subject_type == current.subject_type
            and item.subject_id == current.subject_id and item.fact_key == current.fact_key
        ]
        if current.supersedes_fact_id:
            old = repository.get(current.supersedes_fact_id)
            if old is None or old.status != "confirmed":
                raise LearningFactConflictError("Replacement target is no longer an active confirmed fact.")
            if any(item.fact_id != old.fact_id for item in confirmed):
                raise LearningFactConflictError("Another confirmed fact already owns this subject/key authority.")
            old_updated = LearningFact.model_validate(old.model_copy(update={
                "status": "superseded", "superseded_by_fact_id": current.fact_id,
                "updated_at": timestamp, "superseded_at": timestamp,
                "superseded_by": actor, "supersession_note": note,
            }).model_dump(exclude_computed_fields=True))
            repository.save(old_updated)
        elif confirmed:
            raise LearningFactConflictError(
                "A confirmed fact already exists for this subject/key; create an explicit replacement fact."
            )
        updated = LearningFact.model_validate(current.model_copy(update={
            "status": "confirmed", "updated_at": timestamp, "reviewed_at": timestamp,
            "reviewed_by": actor, "review_note": note,
        }).model_dump(exclude_computed_fields=True))
        return repository.save(updated)


def reject_learning_fact(
    *, repository: LearningFactRepository, fact_id: str, reviewed_by: str, review_note: str,
    occurred_at: datetime | None = None,
) -> LearningFact:
    timestamp = _aware_utc(occurred_at)
    actor = _actor(reviewed_by)
    note = review_note.strip()
    if not note:
        raise ValueError("Learning fact rejection note is required.")
    with atomic_repository_transaction(repository):
        current = repository.get(fact_id)
        if current is None:
            raise LearningFactNotFoundError(fact_id)
        if current.status == "rejected":
            return current
        if current.status != "proposed":
            raise LearningFactConflictError("Only a proposed learning fact may be rejected.")
        updated = LearningFact.model_validate(current.model_copy(update={
            "status": "rejected", "updated_at": timestamp, "reviewed_at": timestamp,
            "reviewed_by": actor, "review_note": note,
        }).model_dump(exclude_computed_fields=True))
        return repository.save(updated)


def build_learning_fact_view(
    *, repository: LearningFactRepository, subject_type: str, subject_id: str,
) -> dict[str, Any]:
    items = list_learning_facts(repository=repository, subject_type=subject_type, subject_id=subject_id)
    return {
        "subject_type": subject_type, "subject_id": subject_id,
        "facts": [item.model_dump() for item in items],
        "proposed_count": sum(item.status == "proposed" for item in items),
        "confirmed_count": sum(item.status == "confirmed" for item in items),
        "rejected_count": sum(item.status == "rejected" for item in items),
        "superseded_count": sum(item.status == "superseded" for item in items),
        "runtime_facts": [item.model_dump() for item in items if item.runtime_authoritative],
    }
