from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from src.core.customer_preference_policy import (
    COMMERCIAL_ACCEPTED_CURRENCY_KEY,
    PREFERENCE_FACT_FIELDS,
)
from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data import normalize_master_text
from src.core.master_data_repository import MasterDataRepository
from src.core.mina_job_repository import MinaJobRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_customer_context import resolve_customer_master_profile

PREFERENCE_MIN_SAMPLE_COUNT = 5
PREFERENCE_MIN_DOMINANCE = 0.80
COMMERCIAL_CURRENCY_MIN_SAMPLE_COUNT = 3
COMMERCIAL_CURRENCY_MIN_DOMINANCE = 0.80

_FIELD_FACTS = {
    "commodity": "preference.default_commodity",
    "equipment_type": "preference.default_equipment_type",
    "pickup_country": "preference.default_pickup_country",
    "pickup_city": "preference.default_pickup_city",
    "delivery_country": "preference.default_delivery_country",
    "delivery_city": "preference.default_delivery_city",
}
_ACCEPTED_STAGES = {
    "accepted", "operations", "operation_opened", "supplier_confirmation_pending",
    "vehicle_details_pending", "vehicle_assigned", "pre_loading_check", "ready_for_loading",
    "loaded", "in_transit", "delivery", "delivered", "pod_cmr_pending", "closing_review", "completed",
}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Customer preference learning timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _confidence(sample_count: int) -> float:
    return min(0.95, round(0.58 + 0.04 * sample_count, 4))


def _commercial_confidence(sample_count: int) -> float:
    return min(0.95, round(0.55 + 0.07 * sample_count, 4))


def _active_confirmed(repository: LearningFactRepository, *, customer_id: str, fact_key: str) -> LearningFact | None:
    items = [
        item for item in repository.list_all()
        if item.subject_type == "customer" and item.subject_id == customer_id
        and item.fact_key == fact_key and item.context_key is None and item.status == "confirmed"
    ]
    return max(items, key=lambda item: (item.updated_at, item.fact_id)) if items else None


def _dominant(observations: list[tuple[str, datetime, str]], *, minimum: int, threshold: float):
    usable = [(rid, when, value.strip()) for rid, when, value in observations if str(value or "").strip()]
    if len(usable) < minimum:
        return None
    normalized = [normalize_master_text(value) for _rid, _when, value in usable]
    counts = Counter(normalized)
    winner, count = counts.most_common(1)[0]
    dominance = count / len(usable)
    if dominance < threshold:
        return None
    displays = [(when, value) for _rid, when, value in usable if normalize_master_text(value) == winner]
    display = max(displays, key=lambda item: item[0])[1]
    evidence_ids = sorted(rid for rid, _when, value in usable if normalize_master_text(value) == winner)
    latest = max(when for _rid, when, value in usable if normalize_master_text(value) == winner)
    return display, len(usable), count, round(dominance * 100, 2), evidence_ids, latest


def _proposal(
    *, customer, fact_key: str, value: str, observed_count: int, support_count: int,
    dominance_percent: float, evidence_ids: list[str], latest_observed: datetime,
    confidence: float, learning_repository: LearningFactRepository,
    master_repository: MasterDataRepository, created_by: str, occurred_at: datetime,
    evidence_kind: str,
) -> LearningFact | None:
    payload = {
        "customer_id": customer.customer_id, "fact_key": fact_key, "value": value,
        "observed_count": observed_count, "support_count": support_count,
        "dominance_percent": dominance_percent, "evidence_ids": evidence_ids,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]
    active = _active_confirmed(learning_repository, customer_id=customer.customer_id, fact_key=fact_key)
    if active is not None and active.value == value:
        active_observed = max(item.observed_at.astimezone(timezone.utc) for item in active.evidence)
        if active.confidence >= confidence and active_observed >= latest_observed:
            return None
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference=f"customer-preference:{customer.customer_id}:{digest}",
        observed_at=latest_observed,
        dataset_key=evidence_kind,
        summary=(
            f"Derived from {observed_count} observed customer records; {support_count} support '{value}' "
            f"({dominance_percent:.1f}% dominance). Human review is required before runtime use."
        ),
    )
    return create_learning_fact(
        repository=learning_repository,
        entry_id=f"customer-preference:{customer.customer_id}:{fact_key}:{digest}",
        subject_type="customer", subject_id=customer.customer_id, subject_label=customer.customer_name,
        fact_key=fact_key, value=value, value_unit="text", confidence=confidence,
        source_type="minai_inference", evidence=[evidence], created_by=created_by,
        supersedes_fact_id=None if active is None else active.fact_id,
        occurred_at=occurred_at, master_repository=master_repository,
    )


def derive_customer_preference_learning(
    *, customer_id: str, master_repository: MasterDataRepository,
    mina_repository: MinaJobRepository, learning_repository: LearningFactRepository,
    quote_case_repository: QuoteCaseRepository | None, created_by: str,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    customer = master_repository.get_customer(customer_id)
    if customer is None:
        raise KeyError(customer_id)
    timestamp = _aware(occurred_at or datetime.now(timezone.utc))
    jobs = []
    future_job_count = 0
    for job in mina_repository.list_all():
        if _aware(job.opened_at) > timestamp:
            future_job_count += 1
            continue
        matched = resolve_customer_master_profile(
            customer_name=getattr(job.shipment, "customer_name", None), master_repository=master_repository,
        )
        if matched is not None and matched.customer_id == customer.customer_id:
            jobs.append(job)

    proposals: list[LearningFact] = []
    for shipment_field, fact_key in _FIELD_FACTS.items():
        observations = [
            (job.job_id, _aware(job.opened_at), str(getattr(job.shipment, shipment_field, "") or ""))
            for job in jobs
        ]
        dominant = _dominant(
            observations, minimum=PREFERENCE_MIN_SAMPLE_COUNT, threshold=PREFERENCE_MIN_DOMINANCE,
        )
        if dominant is None:
            continue
        value, observed_count, support_count, dominance, ids, latest = dominant
        fact = _proposal(
            customer=customer, fact_key=fact_key, value=value,
            observed_count=observed_count, support_count=support_count,
            dominance_percent=dominance, evidence_ids=ids, latest_observed=latest,
            confidence=_confidence(observed_count), learning_repository=learning_repository,
            master_repository=master_repository, created_by=created_by, occurred_at=timestamp,
            evidence_kind="customer_request_preference_v1",
        )
        if fact is not None:
            proposals.append(fact)

    commercial_proposals: list[LearningFact] = []
    accepted_observations: list[tuple[str, datetime, str]] = []
    if quote_case_repository is not None:
        for job in jobs:
            if job.job_kind != "price_request" or job.stage not in _ACCEPTED_STAGES or not job.quote_case_id:
                continue
            case = quote_case_repository.get(job.quote_case_id)
            if case is None or case.customer_quote is None:
                continue
            accepted_observations.append((job.job_id, _aware(job.updated_at), case.customer_quote.currency))
    currency = _dominant(
        accepted_observations,
        minimum=COMMERCIAL_CURRENCY_MIN_SAMPLE_COUNT,
        threshold=COMMERCIAL_CURRENCY_MIN_DOMINANCE,
    )
    if currency is not None:
        value, observed_count, support_count, dominance, ids, latest = currency
        fact = _proposal(
            customer=customer, fact_key=COMMERCIAL_ACCEPTED_CURRENCY_KEY, value=value.upper(),
            observed_count=observed_count, support_count=support_count,
            dominance_percent=dominance, evidence_ids=ids, latest_observed=latest,
            confidence=_commercial_confidence(observed_count), learning_repository=learning_repository,
            master_repository=master_repository, created_by=created_by, occurred_at=timestamp,
            evidence_kind="accepted_quote_currency_v1",
        )
        if fact is not None:
            commercial_proposals.append(fact)

    return {
        "customer_id": customer.customer_id,
        "customer_name": customer.customer_name,
        "matched_job_count": len(jobs),
        "future_job_count_excluded": future_job_count,
        "minimum_request_sample_count": PREFERENCE_MIN_SAMPLE_COUNT,
        "minimum_dominance_percent": PREFERENCE_MIN_DOMINANCE * 100,
        "proposed_fact_count": len(proposals),
        "proposed_facts": [item.model_dump() for item in proposals],
        "accepted_quote_observation_count": len(accepted_observations),
        "commercial_proposed_fact_count": len(commercial_proposals),
        "commercial_proposed_facts": [item.model_dump() for item in commercial_proposals],
        "note": (
            "Repeated request defaults remain proposed until human review. Explicit request values and Customer Master "
            "always outrank learned defaults; accepted currency is advisory only."
        ),
    }
