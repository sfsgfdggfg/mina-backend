from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from statistics import median
from collections import defaultdict

from src.core.learning_fact import LearningEvidence
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import MasterDataRepository
from src.core.supplier_rfq_repository import SupplierRFQRepository
from src.core.supplier_price_repository import SupplierPriceRepository
from src.core.supplier_context import shipment_context_keys


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
    price_repository: SupplierPriceRepository | None = None,
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
    contact_attempt_counts = {"phone": 0, "whatsapp": 0}
    contact_ack_counts = {"phone": 0, "whatsapp": 0}
    contact_ack_to_quote_minutes: dict[str, list[float]] = {"phone": [], "whatsapp": []}
    escalation_attempt_counts = {"phone": 0, "whatsapp": 0, "management": 0}
    escalation_ack_counts = {"phone": 0, "whatsapp": 0, "management": 0}
    quoted_count = 0
    responded_count = 0
    evidence_ids: list[str] = []
    observed_times: list[datetime] = []
    negotiation_reductions: list[float] = []
    negotiation_ids: list[str] = []
    contextual: dict[str, dict] = defaultdict(lambda: {
        "responded_count": 0, "quoted_count": 0, "response_minutes": [],
        "rfq_ids": [], "observed_times": [],
    })
    for draft in drafts:
        workflow = supplier_repository.get_workflow(draft.workflow_id)
        context_keys = shipment_context_keys(workflow.shipment) if workflow is not None else []
        if draft.sent_at is not None:
            observed_times.append(_aware(draft.sent_at))
        attempts = supplier_repository.list_contact_attempts(draft.rfq_id)
        for attempt in attempts:
            observed_times.append(_aware(attempt.attempted_at))
            contact_attempt_counts[attempt.channel] += 1
            if attempt.outcome == "acknowledged_working":
                contact_ack_counts[attempt.channel] += 1
        escalations = supplier_repository.list_escalation_evidence(draft.rfq_id)
        for escalation in escalations:
            observed_times.append(_aware(escalation.escalated_at))
            key = "management" if escalation.level == "management" else escalation.channel
            escalation_attempt_counts[key] += 1
            if escalation.outcome == "acknowledged_working":
                escalation_ack_counts[key] += 1
        responses = supplier_repository.list_responses(draft.rfq_id)
        if not responses:
            continue
        latest = max(responses, key=lambda item: _aware(item.received_at))
        observed_times.extend(_aware(item.received_at) for item in responses)
        responded_count += 1
        is_usable_quote = latest.status == "quoted" and latest.is_price_usable
        quoted_count += int(is_usable_quote)
        evidence_ids.append(draft.rfq_id)
        elapsed = _minutes(draft.sent_at, latest.received_at)
        if elapsed is not None:
            response_minutes.append(elapsed)
        for context_key in context_keys:
            stats = contextual[context_key]
            stats["responded_count"] += 1
            stats["quoted_count"] += int(is_usable_quote)
            stats["rfq_ids"].append(draft.rfq_id)
            if draft.sent_at is not None:
                stats["observed_times"].append(_aware(draft.sent_at))
            stats["observed_times"].extend(_aware(item.received_at) for item in responses)
            if elapsed is not None:
                stats["response_minutes"].append(elapsed)
        acknowledgements = supplier_repository.list_acknowledgements(draft.rfq_id)
        observed_times.extend(_aware(item.acknowledged_at) for item in acknowledgements)
        if acknowledgements:
            latest_ack = max(acknowledgements, key=lambda item: _aware(item.acknowledged_at))
            elapsed_ack = _minutes(latest_ack.acknowledged_at, latest.received_at)
            if elapsed_ack is not None:
                ack_to_quote_minutes.append(elapsed_ack)
        if is_usable_quote:
            for channel in ("phone", "whatsapp"):
                successful = [
                    item for item in attempts
                    if item.channel == channel and item.outcome == "acknowledged_working"
                    and _aware(item.attempted_at) <= _aware(latest.received_at)
                ]
                if successful:
                    latest_success = max(successful, key=lambda item: _aware(item.attempted_at))
                    elapsed_channel = _minutes(latest_success.attempted_at, latest.received_at)
                    if elapsed_channel is not None:
                        contact_ack_to_quote_minutes[channel].append(elapsed_channel)

    if price_repository is not None:
        for negotiation in price_repository.list_negotiations():
            if negotiation.supplier_name.strip().casefold() != supplier.supplier_name.strip().casefold():
                continue
            negotiation_reductions.append(float(negotiation.reduction_percent))
            negotiation_ids.append(negotiation.negotiation_id)
            observed_times.append(_aware(negotiation.recorded_at))

    fingerprint_source = {
        "supplier_id": supplier.supplier_id,
        "rfq_ids": sorted(evidence_ids),
        "response_minutes": response_minutes,
        "ack_to_quote_minutes": ack_to_quote_minutes,
        "quoted_count": quoted_count,
        "responded_count": responded_count,
        "contact_attempt_counts": contact_attempt_counts,
        "contact_ack_counts": contact_ack_counts,
        "contact_ack_to_quote_minutes": contact_ack_to_quote_minutes,
        "escalation_attempt_counts": escalation_attempt_counts,
        "escalation_ack_counts": escalation_ack_counts,
        "negotiation_ids": sorted(negotiation_ids),
        "negotiation_reductions": negotiation_reductions,
    }
    digest = hashlib.sha256(
        json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference=f"supplier-rfq-history:{supplier.supplier_id}:{digest}",
        observed_at=max(observed_times) if observed_times else timestamp,
        summary=(
            f"Derived from {len(drafts)} RFQ records, {responded_count} supplier responses "
            f"and {quoted_count} usable quotes for {supplier.supplier_name}; "
            f"contact attempts: phone={contact_attempt_counts['phone']}, "
            f"whatsapp={contact_attempt_counts['whatsapp']}; "
            f"explicit escalations: phone={escalation_attempt_counts['phone']}, "
            f"whatsapp={escalation_attempt_counts['whatsapp']}, "
            f"management={escalation_attempt_counts['management']}; "
            f"explicit negotiation records={len(negotiation_reductions)}."
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
    for channel in ("phone", "whatsapp"):
        attempts = contact_attempt_counts[channel]
        if attempts:
            metrics.append((
                f"contact.{channel}.ack_rate_percent",
                round(100 * contact_ack_counts[channel] / attempts, 2), "percent",
                min(0.90, 0.50 + 0.05 * attempts),
            ))
        channel_timings = contact_ack_to_quote_minutes[channel]
        if channel_timings:
            metrics.append((
                f"contact.{channel}.after_ack_quote_median_minutes",
                round(float(median(channel_timings)), 2), "minutes",
                min(0.95, 0.55 + 0.05 * len(channel_timings)),
            ))

    for escalation_key in ("phone", "whatsapp", "management"):
        attempts = escalation_attempt_counts[escalation_key]
        if attempts:
            metrics.append((
                f"escalation.{escalation_key}.ack_rate_percent",
                round(100 * escalation_ack_counts[escalation_key] / attempts, 2), "percent",
                min(0.90, 0.50 + 0.05 * attempts),
            ))

    if negotiation_reductions:
        metrics.append((
            "commercial.negotiated_reduction_percent",
            round(float(median(negotiation_reductions)), 2), "percent",
            min(0.95, 0.55 + 0.05 * len(negotiation_reductions)),
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

    contextual_proposals = []
    for context_key, stats in sorted(contextual.items()):
        sample_count = int(stats["responded_count"])
        if sample_count < 3 or not stats["response_minutes"]:
            continue
        context_fingerprint = {
            "supplier_id": supplier.supplier_id, "context_key": context_key,
            "rfq_ids": sorted(stats["rfq_ids"]),
            "response_minutes": stats["response_minutes"],
            "quoted_count": stats["quoted_count"], "responded_count": sample_count,
        }
        context_digest = hashlib.sha256(
            json.dumps(context_fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:16]
        context_evidence = LearningEvidence(
            source_type="operation_history",
            source_reference=f"supplier-context:{supplier.supplier_id}:{context_digest}",
            observed_at=max(stats["observed_times"]),
            dataset_key=context_key[:120],
            summary=(
                f"Derived from {sample_count} supplier responses for context {context_key}; "
                f"usable quotes={stats['quoted_count']}. Context learning remains human-reviewed."
            ),
        )
        context_metrics = [
            (
                "response.median_minutes",
                round(float(median(stats["response_minutes"])), 2), "minutes",
                min(0.95, 0.55 + 0.05 * sample_count),
            ),
            (
                "commercial.usable_quote_rate_percent",
                round(100 * stats["quoted_count"] / sample_count, 2), "percent",
                min(0.90, 0.50 + 0.05 * sample_count),
            ),
        ]
        for fact_key, value, unit, confidence in context_metrics:
            confirmed = [
                item for item in learning_repository.list_all()
                if item.status == "confirmed" and item.subject_type == "supplier"
                and item.subject_id == supplier.supplier_id and item.fact_key == fact_key
                and item.context_key == context_key
            ]
            active = max(confirmed, key=lambda item: item.updated_at) if confirmed else None
            if active is not None and active.value == value and active.value_unit == unit:
                continue
            fact = create_learning_fact(
                repository=learning_repository,
                entry_id=(
                    f"supplier-context:{supplier.supplier_id}:{fact_key}:"
                    f"{context_digest}"
                ),
                subject_type="supplier", subject_id=supplier.supplier_id,
                subject_label=supplier.supplier_name, fact_key=fact_key, context_key=context_key,
                value=value, value_unit=unit, confidence=confidence,
                source_type="minai_inference", evidence=[context_evidence], created_by=created_by,
                supersedes_fact_id=None if active is None else active.fact_id,
                occurred_at=timestamp, master_repository=master_repository,
            )
            contextual_proposals.append(fact)

    return {
        "supplier_id": supplier.supplier_id,
        "supplier_name": supplier.supplier_name,
        "rfq_count": len(drafts),
        "responded_count": responded_count,
        "usable_quote_count": quoted_count,
        "negotiation_evidence_count": len(negotiation_reductions),
        "escalation_evidence_count": sum(escalation_attempt_counts.values()),
        "proposed_facts": [item.model_dump() for item in proposals],
        "contextual_proposed_fact_count": len(contextual_proposals),
        "contextual_proposed_facts": [item.model_dump() for item in contextual_proposals],
        "note": "Derived observations remain proposed until a human confirms them.",
    }
