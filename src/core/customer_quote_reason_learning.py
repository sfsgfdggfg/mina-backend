from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any

from src.core.customer_loss_feedback import LossFeedbackEvidence, loss_feedback_from_event
from src.core.customer_quote_context import customer_quote_context_key
from src.core.customer_quote_reason_policy import (
    CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
    PRICE_OBJECTION_RATE_KEY,
    TRANSIT_TIME_OBJECTION_RATE_KEY,
)
from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.models import CustomerQuote
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_customer_context import resolve_customer_master_profile

REASON_RATE_MIN_STRUCTURED_FEEDBACK_COUNT = 5
REASON_RATE_MIN_COVERAGE_PERCENT = 80.0
REASON_RATE_MIN_EXPLICIT_REASON_COUNT = 3
TARGET_PRICE_MIN_SAMPLE_COUNT = 3

_REASON_FACT_KEYS = {
    "price": PRICE_OBJECTION_RATE_KEY,
    "transit_time": TRANSIT_TIME_OBJECTION_RATE_KEY,
}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Customer quote reason learning timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _stage_time(events, stage: str, *, as_of: datetime) -> datetime | None:
    times = [
        _aware(event.occurred_at) for event in events
        if event.event_type == "stage_changed" and event.metadata.get("to_stage") == stage
        and _aware(event.occurred_at) <= as_of
    ]
    return min(times) if times else None


def _last_send_event(events, *, before: datetime):
    candidates = [
        event for event in events
        if event.event_type == "customer_quote_sent" and _aware(event.occurred_at) < before
    ]
    return max(candidates, key=lambda item: (_aware(item.occurred_at), item.event_id)) if candidates else None


def _quote_for_sent_revision(case: QuoteCase, revision_number: int) -> CustomerQuote | None:
    # Keep this reconstruction identical to quote-acceptance learning: revision 0
    # means the original quote, including when a later unsent revision exists.
    if revision_number == 0:
        if case.quote_revisions:
            first = min(case.quote_revisions, key=lambda item: item.revision_number)
            if first.revision_number == 1:
                return first.previous_customer_quote
        return case.customer_quote
    revision = next((item for item in case.quote_revisions if item.revision_number == revision_number), None)
    return None if revision is None else revision.revised_customer_quote


def _current_feedback_as_of(events, *, as_of: datetime) -> LossFeedbackEvidence | None:
    items = []
    for event in events:
        if _aware(event.occurred_at) > as_of:
            continue
        parsed = loss_feedback_from_event(event)
        if parsed is not None and _aware(parsed.recorded_at) <= as_of:
            items.append(parsed)
    if not items:
        return None
    items.sort(key=lambda item: (_aware(item.recorded_at), item.feedback_id))
    superseded = {item.supersedes_feedback_id for item in items if item.supersedes_feedback_id}
    active = [item for item in items if item.feedback_id not in superseded]
    return active[-1] if active else items[-1]


def _quote_case_for_job(job, repository: QuoteCaseRepository) -> QuoteCase | None:
    case = repository.get(job.quote_case_id) if job.quote_case_id else None
    if case is not None:
        return case
    candidates = [
        item for item in repository.list_all()
        if item.mina_job_id == job.job_id or item.mina_code == job.mina_code
    ]
    return candidates[0] if len(candidates) == 1 else None


def _active_confirmed(
    repository: LearningFactRepository, *, customer_id: str, fact_key: str, context_key: str | None,
) -> LearningFact | None:
    items = [
        item for item in repository.list_all()
        if item.subject_type == "customer" and item.subject_id == customer_id
        and item.fact_key == fact_key and item.context_key == context_key and item.status == "confirmed"
    ]
    return max(items, key=lambda item: (item.updated_at, item.fact_id)) if items else None


def _confidence(sample_count: int) -> float:
    return min(0.95, round(0.60 + 0.03 * sample_count, 4))


def _target_price_confidence(sample_count: int) -> float:
    return min(0.95, round(0.68 + 0.04 * sample_count, 4))


def _proposal(
    *, customer, fact_key: str, context_key: str | None, value: float, value_unit: str,
    sample_count: int, evidence_ids: list[str], latest_observed: datetime, confidence: float,
    learning_repository: LearningFactRepository, master_repository: MasterDataRepository,
    created_by: str, occurred_at: datetime, summary: str, dataset_key: str,
) -> LearningFact | None:
    rounded_value = round(value, 2)
    payload = {
        "customer_id": customer.customer_id, "fact_key": fact_key, "context_key": context_key,
        "value": round(value, 4), "value_unit": value_unit, "sample_count": sample_count,
        "evidence_ids": sorted(evidence_ids),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    active = _active_confirmed(
        learning_repository, customer_id=customer.customer_id, fact_key=fact_key, context_key=context_key,
    )
    if active is not None and active.value == rounded_value and active.value_unit == value_unit:
        active_observed = max(item.observed_at.astimezone(timezone.utc) for item in active.evidence)
        if active.confidence >= confidence and active_observed >= latest_observed:
            return None
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference=f"quote-reason:{customer.customer_id}:{digest}",
        observed_at=latest_observed,
        dataset_key=dataset_key,
        summary=summary,
    )
    return create_learning_fact(
        repository=learning_repository,
        entry_id=f"quote-reason:{customer.customer_id}:{fact_key}:{digest}",
        subject_type="customer", subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key=fact_key, context_key=context_key, value=rounded_value, value_unit=value_unit,
        confidence=confidence, source_type="minai_inference", evidence=[evidence],
        created_by=created_by, supersedes_fact_id=None if active is None else active.fact_id,
        occurred_at=occurred_at, master_repository=master_repository,
    )


def derive_customer_quote_reason_learning(
    *, customer_id: str, master_repository: MasterDataRepository,
    mina_repository: MinaJobRepository, quote_case_repository: QuoteCaseRepository,
    learning_repository: LearningFactRepository, created_by: str,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    customer = master_repository.get_customer(customer_id)
    if customer is None:
        raise KeyError(customer_id)
    timestamp = _aware(occurred_at or datetime.now(timezone.utc))
    sent_lost_count = 0
    eligible: list[dict[str, Any]] = []
    excluded_without_send = excluded_snapshot_integrity = excluded_future = 0

    for job in mina_repository.list_all():
        if job.job_kind != "price_request":
            continue
        if _aware(job.opened_at) > timestamp:
            excluded_future += 1
            continue
        matched = resolve_customer_master_profile(
            customer_name=getattr(job.shipment, "customer_name", None), master_repository=master_repository,
        )
        if matched is None or matched.customer_id != customer.customer_id:
            continue
        events = mina_repository.list_events(job.job_id)
        lost_at = _stage_time(events, "lost", as_of=timestamp)
        if lost_at is None:
            if any(_aware(event.occurred_at) > timestamp for event in events):
                excluded_future += 1
            continue
        sent_event = _last_send_event(events, before=lost_at)
        if sent_event is None:
            excluded_without_send += 1
            continue
        sent_lost_count += 1
        case = _quote_case_for_job(job, quote_case_repository)
        try:
            revision_number = int(sent_event.metadata.get("revision_number") or 0)
        except (TypeError, ValueError):
            revision_number = -1
        sent_quote = None if case is None else _quote_for_sent_revision(case, revision_number)
        if sent_quote is None:
            excluded_snapshot_integrity += 1
            continue
        feedback = _current_feedback_as_of(events, as_of=timestamp)
        eligible.append({
            "job": job, "lost_at": lost_at, "quote": sent_quote, "feedback": feedback,
        })

    structured = [item for item in eligible if item["feedback"] is not None]
    explicit = [item for item in structured if item["feedback"].evidence_basis == "customer_explicit"]
    structured_count = len(structured)
    coverage = 0.0 if sent_lost_count == 0 else 100.0 * structured_count / sent_lost_count
    coverage_gate = (
        structured_count >= REASON_RATE_MIN_STRUCTURED_FEEDBACK_COUNT
        and coverage >= REASON_RATE_MIN_COVERAGE_PERCENT
    )

    proposals: list[LearningFact] = []
    if coverage_gate and explicit:
        latest = max(_aware(item["feedback"].recorded_at) for item in explicit)
        for category, fact_key in _REASON_FACT_KEYS.items():
            supporting = [item for item in explicit if item["feedback"].category == category]
            if len(supporting) < REASON_RATE_MIN_EXPLICIT_REASON_COUNT:
                continue
            fact = _proposal(
                customer=customer, fact_key=fact_key, context_key=None,
                value=100.0 * len(supporting) / len(explicit), value_unit="percent",
                sample_count=len(explicit),
                evidence_ids=[item["feedback"].feedback_id for item in explicit],
                latest_observed=latest, confidence=_confidence(len(explicit)),
                learning_repository=learning_repository, master_repository=master_repository,
                created_by=created_by, occurred_at=timestamp,
                dataset_key="customer_explicit_quote_loss_reason_observation_v1",
                summary=(
                    f"Customer explicitly stated {category} on {len(supporting)} of {len(explicit)} "
                    f"customer-explicit current structured feedback records. Coverage was {coverage:.2f}% "
                    f"({structured_count}/{sent_lost_count}) across sent-and-lost quotes. This is a descriptive "
                    "customer-stated objection frequency, not a causal explanation, win probability, price "
                    "sensitivity, willingness-to-pay signal, or commercial command."
                ),
            )
            if fact is not None:
                proposals.append(fact)

    target_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in explicit:
        feedback = item["feedback"]
        if feedback.customer_stated_target_price is None or not feedback.currency:
            continue
        quote_currency = str(item["quote"].currency).strip().upper()
        if feedback.currency != quote_currency:
            continue
        context = customer_quote_context_key(item["job"].shipment, currency=feedback.currency)
        if context is not None:
            target_groups[context].append(item)
    target_price_proposals: list[LearningFact] = []
    for context, items in sorted(target_groups.items()):
        if len(items) < TARGET_PRICE_MIN_SAMPLE_COUNT:
            continue
        values = [float(item["feedback"].customer_stated_target_price) for item in items]
        latest = max(_aware(item["feedback"].recorded_at) for item in items)
        currency = items[0]["feedback"].currency
        fact = _proposal(
            customer=customer, fact_key=CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
            context_key=context, value=float(median(values)), value_unit=currency,
            sample_count=len(items), evidence_ids=[item["feedback"].feedback_id for item in items],
            latest_observed=latest, confidence=_target_price_confidence(len(items)),
            learning_repository=learning_repository, master_repository=master_repository,
            created_by=created_by, occurred_at=timestamp,
            dataset_key="customer_explicit_target_price_observation_v1",
            summary=(
                f"Median of {len(items)} current customer-explicit target-price statements in {context}. "
                "Currencies and unrelated shipment contexts are not pooled. This is historical advisory "
                "evidence only, never an automatic price, margin, discount, or quote-send command."
            ),
        )
        if fact is not None:
            target_price_proposals.append(fact)

    return {
        "customer_id": customer.customer_id,
        "customer_name": customer.customer_name,
        "sent_and_lost_job_count": sent_lost_count,
        "eligible_snapshot_job_count": len(eligible),
        "current_structured_feedback_count": structured_count,
        "customer_explicit_feedback_count": len(explicit),
        "structured_feedback_coverage_percent": round(coverage, 2),
        "reason_rate_coverage_gate_met": coverage_gate,
        "excluded_without_send_evidence_count": excluded_without_send,
        "excluded_snapshot_integrity_count": excluded_snapshot_integrity,
        "excluded_future_evidence_count": excluded_future,
        "minimum_structured_feedback_count": REASON_RATE_MIN_STRUCTURED_FEEDBACK_COUNT,
        "minimum_structured_feedback_coverage_percent": REASON_RATE_MIN_COVERAGE_PERCENT,
        "minimum_explicit_reason_count": REASON_RATE_MIN_EXPLICIT_REASON_COUNT,
        "minimum_target_price_sample_count": TARGET_PRICE_MIN_SAMPLE_COUNT,
        "proposed_fact_count": len(proposals) + len(target_price_proposals),
        "reason_proposed_facts": [item.model_dump() for item in proposals],
        "target_price_proposed_facts": [item.model_dump() for item in target_price_proposals],
        "pricing_authority_created": False,
        "margin_mutation_authority_created": False,
        "supplier_authority_created": False,
        "automation_authority_created": False,
        "quote_send_authority_created": False,
        "causal_claim_created": False,
        "note": (
            "Only current customer-explicit structured feedback on durably sent-and-lost quote snapshots "
            "supports proposals. Missing feedback remains missing; legacy text and non-customer assessments "
            "are excluded. Every proposal requires human confirmation and remains advisory-only."
        ),
    }
