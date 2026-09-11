from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from src.core.learning_fact import LearningFact
from src.core.learning_fact_repository import LearningFactRepository

CUSTOMER_QUOTE_REASON_ADVISORY_MIN_EFFECTIVE_CONFIDENCE = 0.75
PRICE_OBJECTION_RATE_KEY = "commercial.customer_stated_price_objection_rate_percent"
TRANSIT_TIME_OBJECTION_RATE_KEY = "commercial.customer_stated_transit_time_objection_rate_percent"
CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY = "commercial.customer_stated_target_price_median"
SUPPORTED_CUSTOMER_QUOTE_REASON_FACTS = {
    PRICE_OBJECTION_RATE_KEY,
    TRANSIT_TIME_OBJECTION_RATE_KEY,
    CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY,
}


class CustomerQuoteReasonFactEvaluation(BaseModel):
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


class CustomerQuoteReasonPolicy(BaseModel):
    customer_id: str
    price_objection_rate_percent: float | None = Field(default=None, ge=0, le=100)
    price_objection_rate_fact_id: str | None = None
    transit_time_objection_rate_percent: float | None = Field(default=None, ge=0, le=100)
    transit_time_objection_rate_fact_id: str | None = None
    target_price_advisories: list[CustomerQuoteReasonFactEvaluation] = Field(default_factory=list)
    evaluations: list[CustomerQuoteReasonFactEvaluation] = Field(default_factory=list)
    pricing_authority_created: bool = False
    margin_mutation_authority_created: bool = False
    supplier_ranking_authority_created: bool = False
    supplier_eligibility_authority_created: bool = False
    automation_authority_created: bool = False
    quote_send_authority_created: bool = False
    causal_claim_created: bool = False
    win_probability_created: bool = False
    price_sensitivity_created: bool = False
    willingness_to_pay_created: bool = False
    source: str = "customer_quote_reason_policy_v1"


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Customer quote reason policy timestamp must be timezone-aware.")
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


def build_customer_quote_reason_policy(
    *, customer_id: str, learning_repository: LearningFactRepository | None,
    as_of: datetime | None = None,
) -> CustomerQuoteReasonPolicy:
    current = _utc(as_of)
    if learning_repository is None:
        return CustomerQuoteReasonPolicy(customer_id=customer_id)
    candidates = [
        item for item in learning_repository.list_all()
        if item.subject_type == "customer" and item.subject_id == customer_id
        and item.status == "confirmed" and item.fact_key in SUPPORTED_CUSTOMER_QUOTE_REASON_FACTS
    ]
    active: dict[tuple[str, str | None], LearningFact] = {}
    for fact in sorted(candidates, key=lambda item: (item.updated_at, item.fact_id)):
        active[(fact.fact_key, fact.context_key)] = fact

    evaluations: list[CustomerQuoteReasonFactEvaluation] = []
    target_prices: list[CustomerQuoteReasonFactEvaluation] = []
    price_rate = transit_rate = None
    price_id = transit_id = None
    for (key, context_key), fact in active.items():
        value = float(fact.value) if isinstance(fact.value, (int, float)) and not isinstance(fact.value, bool) else None
        unit = fact.value_unit or ""
        observed = _latest_evidence_at(fact)
        raw_age = (current - observed).total_seconds() / 86400
        age = max(0.0, raw_age)
        recency = _recency(raw_age)
        effective = round(fact.confidence * recency, 4)
        valid = value is not None and (
            (
                key == CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY
                and context_key is not None and value > 0
                and len(unit) == 3 and unit.isalpha()
                and context_key.endswith(f"|currency={unit.casefold()}")
            )
            or (key in {PRICE_OBJECTION_RATE_KEY, TRANSIT_TIME_OBJECTION_RATE_KEY}
                and context_key is None and unit == "percent" and 0 <= value <= 100)
        )
        effect: Literal["advisory", "none"] = "none"
        reason = "confirmed_customer_stated_metric_below_advisory_confidence"
        if not valid:
            reason = "invalid_customer_quote_reason_metric"
        elif raw_age < 0:
            reason = "future_customer_feedback_evidence_not_authoritative"
        elif recency == 0:
            reason = "customer_feedback_evidence_too_old"
        elif effective >= CUSTOMER_QUOTE_REASON_ADVISORY_MIN_EFFECTIVE_CONFIDENCE:
            effect = "advisory"
            reason = "confirmed_customer_stated_metric_is_advisory_only"
        evaluation = CustomerQuoteReasonFactEvaluation(
            fact_id=fact.fact_id, fact_key=key, context_key=context_key,
            value=0.0 if value is None else value, value_unit=unit,
            raw_confidence=fact.confidence, recency_factor=recency,
            effective_confidence=effective, evidence_age_days=round(age, 2),
            effect=effect, reason=reason,
        )
        evaluations.append(evaluation)
        if effect != "advisory":
            continue
        if key == PRICE_OBJECTION_RATE_KEY:
            price_rate = value
            price_id = fact.fact_id
        elif key == TRANSIT_TIME_OBJECTION_RATE_KEY:
            transit_rate = value
            transit_id = fact.fact_id
        elif key == CUSTOMER_STATED_TARGET_PRICE_MEDIAN_KEY:
            target_prices.append(evaluation)
    return CustomerQuoteReasonPolicy(
        customer_id=customer_id,
        price_objection_rate_percent=price_rate,
        price_objection_rate_fact_id=price_id,
        transit_time_objection_rate_percent=transit_rate,
        transit_time_objection_rate_fact_id=transit_id,
        target_price_advisories=target_prices,
        evaluations=evaluations,
    )
