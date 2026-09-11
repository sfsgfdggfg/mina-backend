from datetime import datetime, timezone
from typing import Any

from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import MasterDataRepository
from src.core.relationship_history import RelationshipHistoryAnalysisResult

MIN_RESPONSE_SAMPLES_FOR_CANONICAL_BACKFILL = 3
SOURCE_RESPONSE_KEY = "history.email.counterparty_response_median_minutes"
TARGET_RESPONSE_KEY = "response.median_minutes"


def _aware(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Supplier history backfill timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def propose_supplier_operational_backfill(
    *, analysis: RelationshipHistoryAnalysisResult,
    learning_repository: LearningFactRepository,
    master_repository: MasterDataRepository,
    created_by: str,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = _aware(occurred_at)
    proposed_fact_ids: list[str] = []
    reused_fact_ids: list[str] = []
    skipped_existing_authority: list[str] = []
    skipped_insufficient_samples: list[str] = []
    skipped_missing_metric: list[str] = []

    all_facts = learning_repository.list_all()
    confirmed_response_subjects = {
        item.subject_id for item in all_facts
        if item.subject_type == "supplier"
        and item.fact_key == TARGET_RESPONSE_KEY
        and item.status == "confirmed"
    }

    supplier_subject_count = 0
    for subject in analysis.subjects:
        if subject.subject_type != "supplier":
            continue
        supplier_subject_count += 1
        if subject.subject_id in confirmed_response_subjects:
            skipped_existing_authority.append(subject.subject_id)
            continue
        if subject.counterparty_response_sample_count < MIN_RESPONSE_SAMPLES_FOR_CANONICAL_BACKFILL:
            skipped_insufficient_samples.append(subject.subject_id)
            continue
        if subject.counterparty_response_median_minutes is None or subject.latest_observed_at is None or not subject.history_digest:
            skipped_missing_metric.append(subject.subject_id)
            continue
        entry_id = (
            f"outlook-supplier-backfill:{subject.subject_id}:"
            f"{TARGET_RESPONSE_KEY}:{subject.history_digest[:20]}"
        )
        existing = learning_repository.find_by_entry_id(entry_id)
        if existing is not None:
            reused_fact_ids.append(existing.fact_id)
            continue

        confidence = subject.counterparty_response_confidence or 0.0
        evidence = LearningEvidence(
            source_type="email",
            source_reference=(
                f"outlook-supplier-history:{subject.subject_id}:"
                f"{subject.history_digest[:24]}"
            ),
            observed_at=subject.latest_observed_at,
            summary=(
                f"Canonical supplier response-time proposal derived from "
                f"{subject.counterparty_response_sample_count} deterministic Outlook "
                "response pairs; raw historical message bodies were not persisted."
            ),
            source_sha256=subject.history_digest,
        )
        fact = create_learning_fact(
            repository=learning_repository,
            entry_id=entry_id,
            subject_type="supplier", subject_id=subject.subject_id,
            subject_label=subject.subject_label,
            fact_key=TARGET_RESPONSE_KEY,
            value=subject.counterparty_response_median_minutes,
            value_unit="minutes",
            confidence=confidence,
            source_type="email",
            evidence=[evidence],
            created_by=created_by,
            occurred_at=timestamp,
            master_repository=master_repository,
        )
        proposed_fact_ids.append(fact.fact_id)

    return {
        "supplier_subject_count": supplier_subject_count,
        "proposed_fact_count": len(proposed_fact_ids),
        "proposed_fact_ids": proposed_fact_ids,
        "reused_fact_count": len(reused_fact_ids),
        "reused_fact_ids": reused_fact_ids,
        "skipped_existing_authority_count": len(skipped_existing_authority),
        "skipped_existing_authority_supplier_ids": skipped_existing_authority,
        "skipped_insufficient_samples_count": len(skipped_insufficient_samples),
        "skipped_insufficient_samples_supplier_ids": skipped_insufficient_samples,
        "skipped_missing_metric_count": len(skipped_missing_metric),
        "skipped_missing_metric_supplier_ids": skipped_missing_metric,
        "minimum_response_samples": MIN_RESPONSE_SAMPLES_FOR_CANONICAL_BACKFILL,
        "target_fact_key": TARGET_RESPONSE_KEY,
        "runtime_authority_created": False,
        "note": "Supplier Outlook backfill creates proposed facts only; human confirmation is required for runtime authority.",
    }
