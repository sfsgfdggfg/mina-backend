from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.core.learning_fact import LearningFact
from src.core.learning_fact_repository import LearningFactRepository

PREFERENCE_RUNTIME_MIN_EFFECTIVE_CONFIDENCE = 0.85
COMMERCIAL_ADVISORY_MIN_EFFECTIVE_CONFIDENCE = 0.80

PREFERENCE_FACT_FIELDS = {
    "preference.default_commodity": "default_commodity",
    "preference.default_equipment_type": "default_equipment_type",
    "preference.default_pickup_country": "default_pickup_country",
    "preference.default_pickup_city": "default_pickup_city",
    "preference.default_delivery_country": "default_delivery_country",
    "preference.default_delivery_city": "default_delivery_city",
}
COMMERCIAL_ACCEPTED_CURRENCY_KEY = "commercial.accepted_quote_currency"


class CustomerPreferenceFactEvaluation(BaseModel):
    fact_id: str
    fact_key: str
    value: str
    raw_confidence: float = Field(ge=0, le=1)
    recency_factor: float = Field(ge=0, le=1)
    effective_confidence: float = Field(ge=0, le=1)
    evidence_age_days: float = Field(ge=0)
    runtime_eligible: bool
    effect: Literal["runtime_default", "advisory", "none"]
    reason: str


class CustomerPreferencePolicy(BaseModel):
    customer_id: str
    learned_defaults: dict[str, str] = Field(default_factory=dict)
    learned_default_fact_ids: dict[str, str] = Field(default_factory=dict)
    accepted_quote_currency_advisory: str | None = None
    accepted_quote_currency_fact_id: str | None = None
    evaluations: list[CustomerPreferenceFactEvaluation] = Field(default_factory=list)
    source: str = "customer_preference_policy_v1"


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Customer preference policy timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _latest_evidence_at(fact: LearningFact) -> datetime:
    return max(item.observed_at.astimezone(timezone.utc) for item in fact.evidence)


def _recency(age_days: float) -> float:
    if age_days < 0:
        return 0.0
    if age_days <= 90:
        return 1.0
    if age_days <= 365:
        return 0.85
    if age_days <= 730:
        return 0.60
    return 0.0


def build_customer_preference_policy(
    *, customer_id: str, learning_repository: LearningFactRepository | None,
    as_of: datetime | None = None,
) -> CustomerPreferencePolicy:
    current = _utc(as_of)
    if learning_repository is None:
        return CustomerPreferencePolicy(customer_id=customer_id)
    supported = {*PREFERENCE_FACT_FIELDS, COMMERCIAL_ACCEPTED_CURRENCY_KEY}
    candidates = [
        item for item in learning_repository.list_all()
        if item.subject_type == "customer" and item.subject_id == customer_id
        and item.status == "confirmed" and item.context_key is None
        and item.fact_key in supported
    ]
    active: dict[str, LearningFact] = {}
    for fact in sorted(candidates, key=lambda item: (item.updated_at, item.fact_id)):
        active[fact.fact_key] = fact

    defaults: dict[str, str] = {}
    default_fact_ids: dict[str, str] = {}
    currency = None
    currency_fact_id = None
    evaluations: list[CustomerPreferenceFactEvaluation] = []
    for key, fact in active.items():
        value = fact.value.strip() if isinstance(fact.value, str) else ""
        observed = _latest_evidence_at(fact)
        raw_age = (current - observed).total_seconds() / 86400
        age = max(0.0, raw_age)
        recency = _recency(raw_age)
        effective = round(fact.confidence * recency, 4)
        valid = bool(value)
        effect: Literal["runtime_default", "advisory", "none"] = "none"
        reason = "eligible_confirmed_customer_preference"
        if not valid:
            reason = "invalid_customer_preference_value"
        elif raw_age < 0:
            reason = "future_evidence_not_authoritative"
        elif recency == 0:
            reason = "customer_preference_evidence_too_old"
        elif key in PREFERENCE_FACT_FIELDS and effective >= PREFERENCE_RUNTIME_MIN_EFFECTIVE_CONFIDENCE:
            field = PREFERENCE_FACT_FIELDS[key]
            defaults[field] = value
            default_fact_ids[field] = fact.fact_id
            effect = "runtime_default"
            reason = "confirmed_repeated_request_preference_may_fill_missing_field"
        elif key == COMMERCIAL_ACCEPTED_CURRENCY_KEY and effective >= COMMERCIAL_ADVISORY_MIN_EFFECTIVE_CONFIDENCE:
            currency = value.upper()
            currency_fact_id = fact.fact_id
            effect = "advisory"
            reason = "confirmed_accepted_quote_currency_is_advisory_only"
        elif valid:
            reason = "confirmed_customer_preference_below_runtime_confidence"
        evaluations.append(CustomerPreferenceFactEvaluation(
            fact_id=fact.fact_id, fact_key=key, value=value,
            raw_confidence=fact.confidence, recency_factor=recency,
            effective_confidence=effective, evidence_age_days=round(age, 2),
            runtime_eligible=bool(valid and recency > 0), effect=effect, reason=reason,
        ))
    return CustomerPreferencePolicy(
        customer_id=customer_id, learned_defaults=defaults,
        learned_default_fact_ids=default_fact_ids,
        accepted_quote_currency_advisory=currency,
        accepted_quote_currency_fact_id=currency_fact_id,
        evaluations=evaluations,
    )
