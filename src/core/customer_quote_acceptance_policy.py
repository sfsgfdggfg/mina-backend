from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from src.core.learning_fact import LearningFact
from src.core.learning_fact_repository import LearningFactRepository

QUOTE_ACCEPTANCE_ADVISORY_MIN_EFFECTIVE_CONFIDENCE = 0.75
QUOTE_ACCEPTANCE_RATE_KEY = "commercial.quote_outcome_acceptance_rate_percent"
QUOTE_NEGOTIATION_RATE_KEY = "commercial.quote_negotiation_rate_percent"
ACCEPTED_FINAL_PRICE_MEDIAN_KEY = "commercial.accepted_final_price_median"
ACCEPTED_MARKUP_MEDIAN_KEY = "commercial.accepted_markup_value_median"
SUPPORTED_QUOTE_ACCEPTANCE_FACTS = {
    QUOTE_ACCEPTANCE_RATE_KEY, QUOTE_NEGOTIATION_RATE_KEY,
    ACCEPTED_FINAL_PRICE_MEDIAN_KEY, ACCEPTED_MARKUP_MEDIAN_KEY,
}


class CustomerQuoteAcceptanceFactEvaluation(BaseModel):
    fact_id: str
    fact_key: str
    context_key: str | None = None
    value: float
    value_unit: str
    raw_confidence: float = Field(ge=0, le=1)
    recency_factor: float = Field(ge=0, le=1)
    effective_confidence: float = Field(ge=0, le=1)
    evidence_age_days: float = Field(ge=0)
    effect: Literal["advisory", "none"]
    reason: str


class CustomerQuoteAcceptancePolicy(BaseModel):
    customer_id: str
    overall_acceptance_rate_percent: float | None = Field(default=None, ge=0, le=100)
    overall_acceptance_rate_fact_id: str | None = None
    negotiation_rate_percent: float | None = Field(default=None, ge=0, le=100)
    negotiation_rate_fact_id: str | None = None
    contextual_advisories: list[CustomerQuoteAcceptanceFactEvaluation] = Field(default_factory=list)
    evaluations: list[CustomerQuoteAcceptanceFactEvaluation] = Field(default_factory=list)
    pricing_authority_created: bool = False
    causal_claim_created: bool = False
    source: str = "customer_quote_acceptance_policy_v1"


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Quote acceptance policy timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


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


def _latest_evidence_at(fact: LearningFact) -> datetime:
    return max(item.observed_at.astimezone(timezone.utc) for item in fact.evidence)


def build_customer_quote_acceptance_policy(
    *, customer_id: str, learning_repository: LearningFactRepository | None,
    as_of: datetime | None = None,
) -> CustomerQuoteAcceptancePolicy:
    current = _utc(as_of)
    if learning_repository is None:
        return CustomerQuoteAcceptancePolicy(customer_id=customer_id)
    candidates = [
        item for item in learning_repository.list_all()
        if item.subject_type == "customer" and item.subject_id == customer_id
        and item.status == "confirmed" and item.fact_key in SUPPORTED_QUOTE_ACCEPTANCE_FACTS
    ]
    active: dict[tuple[str, str | None], LearningFact] = {}
    for fact in sorted(candidates, key=lambda item: (item.updated_at, item.fact_id)):
        active[(fact.fact_key, fact.context_key)] = fact

    evaluations: list[CustomerQuoteAcceptanceFactEvaluation] = []
    overall = negotiation = None
    overall_id = negotiation_id = None
    contextual: list[CustomerQuoteAcceptanceFactEvaluation] = []
    for (key, context_key), fact in active.items():
        value = float(fact.value) if isinstance(fact.value, (int, float)) and not isinstance(fact.value, bool) else None
        observed = _latest_evidence_at(fact)
        raw_age = (current - observed).total_seconds() / 86400
        age = max(0.0, raw_age)
        recency = _recency(raw_age)
        effective = round(fact.confidence * recency, 4)
        valid = value is not None and (
            (key == ACCEPTED_FINAL_PRICE_MEDIAN_KEY and value > 0)
            or (key == ACCEPTED_MARKUP_MEDIAN_KEY and value >= 0)
            or (key in {QUOTE_ACCEPTANCE_RATE_KEY, QUOTE_NEGOTIATION_RATE_KEY} and 0 <= value <= 100)
        )
        effect: Literal["advisory", "none"] = "none"
        reason = "confirmed_observational_quote_metric_below_advisory_confidence"
        if not valid:
            reason = "invalid_quote_acceptance_metric"
        elif raw_age < 0:
            reason = "future_quote_outcome_evidence_not_authoritative"
        elif recency == 0:
            reason = "quote_outcome_evidence_too_old"
        elif effective >= QUOTE_ACCEPTANCE_ADVISORY_MIN_EFFECTIVE_CONFIDENCE:
            effect = "advisory"
            reason = "confirmed_observational_quote_metric_is_advisory_only"
        evaluation = CustomerQuoteAcceptanceFactEvaluation(
            fact_id=fact.fact_id, fact_key=key, context_key=context_key,
            value=0.0 if value is None else value, value_unit=fact.value_unit or "",
            raw_confidence=fact.confidence, recency_factor=recency,
            effective_confidence=effective, evidence_age_days=round(age, 2),
            effect=effect, reason=reason,
        )
        evaluations.append(evaluation)
        if effect != "advisory":
            continue
        if context_key is not None:
            contextual.append(evaluation)
        elif key == QUOTE_ACCEPTANCE_RATE_KEY:
            overall = value; overall_id = fact.fact_id
        elif key == QUOTE_NEGOTIATION_RATE_KEY:
            negotiation = value; negotiation_id = fact.fact_id
    return CustomerQuoteAcceptancePolicy(
        customer_id=customer_id, overall_acceptance_rate_percent=overall,
        overall_acceptance_rate_fact_id=overall_id, negotiation_rate_percent=negotiation,
        negotiation_rate_fact_id=negotiation_id, contextual_advisories=contextual,
        evaluations=evaluations, pricing_authority_created=False, causal_claim_created=False,
    )
