from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from statistics import median
from typing import Any

from src.core.customer_quote_acceptance_policy import (
    ACCEPTED_FINAL_PRICE_MEDIAN_KEY, ACCEPTED_MARKUP_MEDIAN_KEY,
    QUOTE_ACCEPTANCE_RATE_KEY, QUOTE_NEGOTIATION_RATE_KEY,
)
from src.core.customer_quote_context import customer_quote_context_key
from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.models import CustomerQuote
from src.core.quote_case import QuoteCase
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_customer_context import resolve_customer_master_profile

QUOTE_OUTCOME_MIN_SAMPLE_COUNT = 5
ACCEPTED_PRICE_MIN_SAMPLE_COUNT = 3


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Quote acceptance learning timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _outcome_confidence(sample_count: int) -> float:
    return min(0.95, round(0.60 + 0.03 * sample_count, 4))


def _accepted_quote_confidence(sample_count: int) -> float:
    return min(0.95, round(0.68 + 0.04 * sample_count, 4))


def _stage_time(events, stage: str) -> datetime | None:
    times = [
        _aware(event.occurred_at) for event in events
        if event.event_type == "stage_changed" and event.metadata.get("to_stage") == stage
    ]
    return min(times) if times else None


def _last_send_event(events, *, before: datetime):
    candidates = [
        event for event in events
        if event.event_type == "customer_quote_sent" and _aware(event.occurred_at) <= before
    ]
    return max(candidates, key=lambda item: (item.occurred_at, item.event_id)) if candidates else None


def _quote_for_sent_revision(case: QuoteCase, revision_number: int) -> CustomerQuote | None:
    if revision_number == 0:
        if case.quote_revisions:
            first = min(case.quote_revisions, key=lambda item: item.revision_number)
            if first.revision_number == 1:
                return first.previous_customer_quote
        return case.customer_quote
    revision = next((item for item in case.quote_revisions if item.revision_number == revision_number), None)
    return None if revision is None else revision.revised_customer_quote


def _active_confirmed(
    repository: LearningFactRepository, *, customer_id: str, fact_key: str, context_key: str | None,
) -> LearningFact | None:
    items = [
        item for item in repository.list_all()
        if item.subject_type == "customer" and item.subject_id == customer_id
        and item.fact_key == fact_key and item.context_key == context_key and item.status == "confirmed"
    ]
    return max(items, key=lambda item: (item.updated_at, item.fact_id)) if items else None


def _proposal(
    *, customer, fact_key: str, context_key: str | None, value: float, value_unit: str,
    sample_count: int, evidence_ids: list[str], latest_observed: datetime, confidence: float,
    learning_repository: LearningFactRepository, master_repository: MasterDataRepository,
    created_by: str, occurred_at: datetime, summary: str, dataset_key: str,
) -> LearningFact | None:
    payload = {
        "customer_id": customer.customer_id, "fact_key": fact_key, "context_key": context_key,
        "value": round(value, 4), "value_unit": value_unit, "sample_count": sample_count,
        "evidence_ids": sorted(evidence_ids),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    active = _active_confirmed(
        learning_repository, customer_id=customer.customer_id, fact_key=fact_key, context_key=context_key,
    )
    if active is not None and active.value == round(value, 2) and active.value_unit == value_unit:
        active_observed = max(item.observed_at.astimezone(timezone.utc) for item in active.evidence)
        if active.confidence >= confidence and active_observed >= latest_observed:
            return None
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference=f"quote-acceptance:{customer.customer_id}:{digest}",
        observed_at=latest_observed, dataset_key=dataset_key, summary=summary,
    )
    return create_learning_fact(
        repository=learning_repository,
        entry_id=f"quote-acceptance:{customer.customer_id}:{fact_key}:{digest}",
        subject_type="customer", subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key=fact_key, context_key=context_key, value=round(value, 2), value_unit=value_unit,
        confidence=confidence, source_type="minai_inference", evidence=[evidence],
        created_by=created_by, supersedes_fact_id=None if active is None else active.fact_id,
        occurred_at=occurred_at, master_repository=master_repository,
    )


def derive_customer_quote_acceptance_learning(
    *, customer_id: str, master_repository: MasterDataRepository,
    mina_repository: MinaJobRepository, quote_case_repository: QuoteCaseRepository,
    learning_repository: LearningFactRepository, created_by: str,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    customer = master_repository.get_customer(customer_id)
    if customer is None:
        raise KeyError(customer_id)
    timestamp = _aware(occurred_at or datetime.now(timezone.utc))
    resolved: list[dict[str, Any]] = []
    excluded_without_send = excluded_unresolved = excluded_integrity = 0
    for job in mina_repository.list_all():
        if job.job_kind != "price_request" or _aware(job.opened_at) > timestamp:
            continue
        matched = resolve_customer_master_profile(
            customer_name=getattr(job.shipment, "customer_name", None), master_repository=master_repository,
        )
        if matched is None or matched.customer_id != customer.customer_id:
            continue
        events = mina_repository.list_events(job.job_id)
        accepted_at = _stage_time(events, "accepted")
        lost_at = _stage_time(events, "lost")
        outcome = "accepted" if accepted_at is not None else ("lost" if lost_at is not None else None)
        outcome_at = accepted_at or lost_at
        if outcome is None or outcome_at is None:
            if any(event.event_type == "customer_quote_sent" for event in events):
                excluded_unresolved += 1
            continue
        sent_event = _last_send_event(events, before=outcome_at)
        if sent_event is None:
            excluded_without_send += 1
            continue
        case = None
        if job.quote_case_id:
            case = quote_case_repository.get(job.quote_case_id)
        if case is None:
            candidates = [
                item for item in quote_case_repository.list_all()
                if item.mina_job_id == job.job_id or item.mina_code == job.mina_code
            ]
            case = candidates[0] if len(candidates) == 1 else None
        revision_number = int(sent_event.metadata.get("revision_number") or 0)
        sent_quote = None if case is None else _quote_for_sent_revision(case, revision_number)
        if sent_quote is None:
            excluded_integrity += 1
            continue
        negotiated = _stage_time(events, "negotiation") is not None
        resolved.append({
            "job": job, "case": case, "outcome": outcome, "outcome_at": outcome_at,
            "sent_at": _aware(sent_event.occurred_at), "revision_number": revision_number,
            "quote": sent_quote, "negotiated": negotiated,
        })

    proposals: list[LearningFact] = []
    accepted_count = sum(item["outcome"] == "accepted" for item in resolved)
    if len(resolved) >= QUOTE_OUTCOME_MIN_SAMPLE_COUNT:
        latest = max(item["outcome_at"] for item in resolved)
        ids = [item["job"].job_id for item in resolved]
        acceptance = 100 * accepted_count / len(resolved)
        fact = _proposal(
            customer=customer, fact_key=QUOTE_ACCEPTANCE_RATE_KEY, context_key=None,
            value=acceptance, value_unit="percent", sample_count=len(resolved), evidence_ids=ids,
            latest_observed=latest, confidence=_outcome_confidence(len(resolved)),
            learning_repository=learning_repository, master_repository=master_repository,
            created_by=created_by, occurred_at=timestamp, dataset_key="quote_outcome_observation_v1",
            summary=(
                f"Observed {accepted_count} accepted and {len(resolved)-accepted_count} lost outcomes among "
                f"{len(resolved)} customer quotes that had durable send evidence. This is observational, not a causal "
                "price or win-probability model, and creates no pricing authority."
            ),
        )
        if fact is not None:
            proposals.append(fact)
        negotiated_count = sum(bool(item["negotiated"]) for item in resolved)
        fact = _proposal(
            customer=customer, fact_key=QUOTE_NEGOTIATION_RATE_KEY, context_key=None,
            value=100 * negotiated_count / len(resolved), value_unit="percent",
            sample_count=len(resolved), evidence_ids=ids, latest_observed=latest,
            confidence=_outcome_confidence(len(resolved)), learning_repository=learning_repository,
            master_repository=master_repository, created_by=created_by, occurred_at=timestamp,
            dataset_key="quote_negotiation_observation_v1",
            summary=(
                f"Observed negotiation stage on {negotiated_count} of {len(resolved)} resolved sent quotes. "
                "The rate is descriptive only and does not identify why a quote was accepted or lost."
            ),
        )
        if fact is not None:
            proposals.append(fact)

    context_outcomes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    accepted_price_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    accepted_markup_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in resolved:
        quote = item["quote"]
        base_context = customer_quote_context_key(item["job"].shipment, currency=quote.currency)
        if base_context is not None:
            context_outcomes[base_context].append(item)
        if item["outcome"] != "accepted" or base_context is None:
            continue
        accepted_price_groups[base_context].append(item)
        markup_context = customer_quote_context_key(
            item["job"].shipment, currency=quote.currency, markup_type=quote.markup_type,
        )
        if markup_context is not None:
            accepted_markup_groups[markup_context].append(item)

    contextual_proposals: list[LearningFact] = []
    for context, items in sorted(context_outcomes.items()):
        if len(items) < QUOTE_OUTCOME_MIN_SAMPLE_COUNT:
            continue
        accepted = sum(item["outcome"] == "accepted" for item in items)
        latest = max(item["outcome_at"] for item in items)
        fact = _proposal(
            customer=customer, fact_key=QUOTE_ACCEPTANCE_RATE_KEY, context_key=context,
            value=100 * accepted / len(items), value_unit="percent", sample_count=len(items),
            evidence_ids=[item["job"].job_id for item in items], latest_observed=latest,
            confidence=_outcome_confidence(len(items)), learning_repository=learning_repository,
            master_repository=master_repository, created_by=created_by, occurred_at=timestamp,
            dataset_key="quote_context_outcome_observation_v1",
            summary=(
                f"Observed {accepted} accepted outcomes among {len(items)} resolved sent quotes in {context}. "
                "This contextual rate is descriptive only; it does not predict acceptance or authorize pricing."
            ),
        )
        if fact is not None:
            contextual_proposals.append(fact)
    for context, items in sorted(accepted_price_groups.items()):
        if len(items) < ACCEPTED_PRICE_MIN_SAMPLE_COUNT:
            continue
        values = [float(item["quote"].final_price) for item in items]
        latest = max(item["outcome_at"] for item in items)
        currency = str(items[0]["quote"].currency).strip().upper()
        fact = _proposal(
            customer=customer, fact_key=ACCEPTED_FINAL_PRICE_MEDIAN_KEY, context_key=context,
            value=float(median(values)), value_unit=currency, sample_count=len(items),
            evidence_ids=[item["job"].job_id for item in items], latest_observed=latest,
            confidence=_accepted_quote_confidence(len(items)), learning_repository=learning_repository,
            master_repository=master_repository, created_by=created_by, occurred_at=timestamp,
            dataset_key="accepted_quote_price_observation_v1",
            summary=(
                f"Median final price across {len(items)} actually sent and later accepted quotes in {context}. "
                "Currencies and shipment contexts are not mixed. The median is historical observation only, not a target price."
            ),
        )
        if fact is not None:
            contextual_proposals.append(fact)
    for context, items in sorted(accepted_markup_groups.items()):
        if len(items) < ACCEPTED_PRICE_MIN_SAMPLE_COUNT:
            continue
        values = [float(item["quote"].markup_value) for item in items]
        latest = max(item["outcome_at"] for item in items)
        fact = _proposal(
            customer=customer, fact_key=ACCEPTED_MARKUP_MEDIAN_KEY, context_key=context,
            value=float(median(values)), value_unit="pricing_formula_value", sample_count=len(items),
            evidence_ids=[item["job"].job_id for item in items], latest_observed=latest,
            confidence=_accepted_quote_confidence(len(items)), learning_repository=learning_repository,
            master_repository=master_repository, created_by=created_by, occurred_at=timestamp,
            dataset_key="accepted_quote_markup_observation_v1",
            summary=(
                f"Median recorded markup value across {len(items)} actually sent and later accepted quotes in {context}. "
                "The statistic is descriptive only and must never change margin or selling price automatically."
            ),
        )
        if fact is not None:
            contextual_proposals.append(fact)

    return {
        "customer_id": customer.customer_id, "customer_name": customer.customer_name,
        "resolved_sent_quote_count": len(resolved), "accepted_count": accepted_count,
        "lost_count": len(resolved) - accepted_count,
        "excluded_without_send_evidence_count": excluded_without_send,
        "excluded_unresolved_sent_quote_count": excluded_unresolved,
        "excluded_snapshot_integrity_count": excluded_integrity,
        "minimum_outcome_sample_count": QUOTE_OUTCOME_MIN_SAMPLE_COUNT,
        "minimum_accepted_price_sample_count": ACCEPTED_PRICE_MIN_SAMPLE_COUNT,
        "proposed_fact_count": len(proposals),
        "proposed_facts": [item.model_dump() for item in proposals],
        "contextual_proposed_fact_count": len(contextual_proposals),
        "contextual_proposed_facts": [item.model_dump() for item in contextual_proposals],
        "pricing_authority_created": False, "causal_claim_created": False,
        "note": (
            "Quote acceptance learning is observational and advisory-only. Lost quotes without durable send evidence, "
            "unresolved sent quotes, currencies and unrelated shipment contexts are not mixed; no price, margin, "
            "supplier or win-probability authority is created."
        ),
    }
