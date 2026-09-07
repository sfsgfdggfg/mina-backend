from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from statistics import median

from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import MasterDataRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _minutes(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    a, b = _aware(start), _aware(end)
    if b < a:
        return None
    return round((b - a).total_seconds() / 60, 2)


def derive_supplier_history_learning(
    *, supplier_id: str, master_repository: MasterDataRepository,
    supplier_repository: SupplierRFQRepository, learning_repository: LearningFactRepository,
    created_by: str, occurred_at: datetime | None = None,
) -> dict:
    supplier = master_repository.get_supplier(supplier_id)
    if supplier is None:
        raise KeyError(supplier_id)
    timestamp = occurred_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        raise ValueError("Supplier learning derivation timestamp must be timezone-aware.")

    drafts = [d for d in supplier_repository.list_drafts() if d.supplier_name == supplier.supplier_name]
    response_minutes: list[float] = []
    ack_to_quote_minutes: list[float] = []
    quoted_count = 0
    responded_count = 0
    evidence_ids: list[str] = []
    for draft in drafts:
        responses = supplier_repository.list_responses(draft.rfq_id)
        if not responses:
            continue
        latest = max(responses, key=lambda item: _aware(item.received_at))
        responded_count += 1
        quoted_count += int(latest.status == "quoted" and latest.is_price_usable)
        evidence_ids.append(draft.rfq_id)
        elapsed = _minutes(draft.sent_at, latest.received_at)
        if elapsed is not None:
            response_minutes.append(elapsed)
        acknowledgements = supplier_repository.list_acknowledgements(draft.rfq_id)
        if acknowledgements:
            latest_ack = max(acknowledgements, key=lambda item: _aware(item.acknowledged_at))
            elapsed_ack = _minutes(latest_ack.acknowledged_at, latest.received_at)
            if elapsed_ack is not None:
                ack_to_quote_minutes.append(elapsed_ack)

    fingerprint_source = {
        "supplier_id": supplier.supplier_id,
        "rfq_ids": sorted(evidence_ids),
        "response_minutes": response_minutes,
        "ack_to_quote_minutes": ack_to_quote_minutes,
        "quoted_count": quoted_count,
        "responded_count": responded_count,
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference=f"supplier-rfq-history:{supplier.supplier_id}:{digest}",
        observed_at=timestamp,
        summary=(
            f"Derived from {len(drafts)} RFQ records, {responded_count} supplier responses "
            f"and {quoted_count} usable quotes for {supplier.supplier_name}."
        ),
    )

    proposals = []
    metrics = []
    if response_minutes:
        metrics.extend([
            ("response.median_minutes", round(float(median(response_minutes)), 2), "minutes", min(0.95, 0.55 + 0.05 * len(response_minutes))),
            ("response.average_minutes", round(sum(response_minutes) / len(response_minutes), 2), "minutes", min(0.92, 0.50 + 0.05 * len(response_minutes))),
        ])
    if ack_to_quote_minutes:
        metrics.append((
            "response.after_ack_median_minutes", round(float(median(ack_to_quote_minutes)), 2), "minutes",
            min(0.95, 0.55 + 0.05 * len(ack_to_quote_minutes)),
        ))
    if responded_count:
        metrics.append((
            "commercial.usable_quote_rate_percent", round(100 * quoted_count / responded_count, 2), "percent",
            min(0.90, 0.50 + 0.05 * responded_count),
        ))

    for fact_key, value, unit, confidence in metrics:
        fact = create_learning_fact(
            repository=learning_repository,
            entry_id=f"supplier-history:{supplier.supplier_id}:{fact_key}:{digest}",
            subject_type="supplier", subject_id=supplier.supplier_id,
            subject_label=supplier.supplier_name, fact_key=fact_key,
            value=value, value_unit=unit, confidence=confidence,
            source_type="minai_inference", evidence=[evidence], created_by=created_by,
            occurred_at=timestamp, master_repository=master_repository,
        )
        proposals.append(fact)
    return {
        "supplier_id": supplier.supplier_id,
        "supplier_name": supplier.supplier_name,
        "rfq_count": len(drafts),
        "responded_count": responded_count,
        "usable_quote_count": quoted_count,
        "proposed_facts": [item.model_dump() for item in proposals],
        "note": "Derived observations remain proposed until a human confirms them.",
    }
