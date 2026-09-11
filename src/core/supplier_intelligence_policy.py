from __future__ import annotations

from datetime import datetime, timezone
from math import ceil
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.core.learning_fact import LearningFact
from src.core.learning_fact_repository import LearningFactRepository
from src.core.master_data import SupplierMasterProfile

RANKING_MIN_EFFECTIVE_CONFIDENCE = 0.70
TIMING_MIN_EFFECTIVE_CONFIDENCE = 0.85
NEGOTIATION_MIN_EFFECTIVE_CONFIDENCE = 0.80
CONTACT_MIN_EFFECTIVE_CONFIDENCE = 0.80
CONTACT_MIN_RATE_ADVANTAGE = 20.0
CONTACT_MIN_WINNER_RATE = 50.0
ESCALATION_MIN_EFFECTIVE_CONFIDENCE = 0.80
ESCALATION_MIN_RATE_ADVANTAGE = 15.0
ESCALATION_MIN_WINNER_RATE = 50.0
MANAGEMENT_MIN_SUCCESS_RATE = 50.0
MAX_RANKING_ADJUSTMENT = 0.06
MAX_LEARNED_FIRST_REMINDER_MINUTES = 60
MAX_LEARNED_ACK_WAIT_MINUTES = 180
MIN_QUOTE_RATE_FOR_PATIENT_TIMING = 70.0

_CANONICAL_UNITS = {
    "response.median_minutes": "minutes",
    "response.after_ack_median_minutes": "minutes",
    "commercial.usable_quote_rate_percent": "percent",
    "commercial.negotiated_reduction_percent": "percent",
    "contact.phone.ack_rate_percent": "percent",
    "contact.whatsapp.ack_rate_percent": "percent",
    "contact.phone.after_ack_quote_median_minutes": "minutes",
    "contact.whatsapp.after_ack_quote_median_minutes": "minutes",
    "escalation.phone.ack_rate_percent": "percent",
    "escalation.whatsapp.ack_rate_percent": "percent",
    "escalation.management.ack_rate_percent": "percent",
}

TimingSource = Literal["supplier_master", "confirmed_learning", "dispatch_default"]


class SupplierLearningFactEvaluation(BaseModel):
    fact_id: str
    fact_key: str
    value: float
    value_unit: str
    raw_confidence: float = Field(ge=0, le=1)
    recency_factor: float = Field(ge=0, le=1)
    effective_confidence: float = Field(ge=0, le=1)
    evidence_age_days: float = Field(ge=0)
    runtime_eligible: bool
    effect: Literal["ranking", "timing", "advisory", "none"]
    reason: str


class SupplierOperationalLearningPolicy(BaseModel):
    supplier_id: str
    supplier_name: str
    ranking_adjustment: float = Field(ge=-MAX_RANKING_ADJUSTMENT, le=MAX_RANKING_ADJUSTMENT)
    effective_first_reminder_minutes: int = Field(ge=5, le=480)
    first_reminder_source: TimingSource
    effective_acknowledged_wait_minutes: int = Field(ge=15, le=720)
    acknowledged_wait_source: TimingSource
    negotiation_advisory_percent: float | None = Field(default=None, ge=0, le=30)
    preferred_contact_channel_advisory: Literal["phone", "whatsapp"] | None = None
    preferred_contact_channel_reason: str | None = None
    preferred_escalation_channel_advisory: Literal["phone", "whatsapp"] | None = None
    preferred_escalation_channel_reason: str | None = None
    management_escalation_advisory: bool = False
    acknowledgement_channel_context: Literal["email", "phone", "whatsapp", "manual"] | None = None
    contact_escalation_learning_applied: bool = False
    evaluations: list[SupplierLearningFactEvaluation] = Field(default_factory=list)
    source: str = "supplier_operational_learning_policy_v3"

    @property
    def applied_fact_ids(self) -> list[str]:
        return [item.fact_id for item in self.evaluations if item.effect != "none"]


def _utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Supplier intelligence policy timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _numeric_value(fact: LearningFact) -> float | None:
    if isinstance(fact.value, bool) or not isinstance(fact.value, (int, float)):
        return None
    return float(fact.value)


def _latest_evidence_at(fact: LearningFact) -> datetime:
    return max(item.observed_at.astimezone(timezone.utc) for item in fact.evidence)


def _recency_factor(fact_key: str, age_days: float) -> float:
    if age_days < 0:
        return 0.0
    if fact_key in {"response.median_minutes", "response.after_ack_median_minutes"}:
        if age_days <= 30:
            return 1.0
        if age_days <= 90:
            return 0.90
        if age_days <= 365:
            return 0.70
        return 0.0
    if fact_key == "commercial.usable_quote_rate_percent":
        if age_days <= 90:
            return 1.0
        if age_days <= 365:
            return 0.85
        if age_days <= 1095:
            return 0.60
        return 0.0
    if fact_key == "commercial.negotiated_reduction_percent":
        if age_days <= 90:
            return 1.0
        if age_days <= 365:
            return 0.80
        if age_days <= 1095:
            return 0.50
        return 0.0
    if fact_key.startswith("contact.") or fact_key.startswith("escalation."):
        if age_days <= 90:
            return 1.0
        if age_days <= 365:
            return 0.85
        if age_days <= 730:
            return 0.60
        return 0.0
    return 0.0


def _response_ranking_delta(minutes: float) -> float:
    if minutes <= 30:
        return 0.025
    if minutes <= 60:
        return 0.015
    if minutes <= 120:
        return 0.005
    if minutes <= 240:
        return -0.005
    return -0.020


def _quote_rate_ranking_delta(percent: float) -> float:
    if percent >= 85:
        return 0.035
    if percent >= 70:
        return 0.020
    if percent >= 50:
        return 0.005
    if percent >= 30:
        return -0.015
    return -0.035


def _round_up(value: float, step: int) -> int:
    return int(ceil(value / step) * step)


def _active_confirmed_facts(
    repository: LearningFactRepository | None, supplier_id: str,
) -> dict[str, LearningFact]:
    if repository is None:
        return {}
    candidates = [
        fact for fact in repository.list_all()
        if fact.subject_type == "supplier" and fact.subject_id == supplier_id
        and fact.status == "confirmed" and fact.fact_key in _CANONICAL_UNITS
    ]
    selected: dict[str, LearningFact] = {}
    for fact in sorted(candidates, key=lambda item: (item.updated_at, item.fact_id)):
        selected[fact.fact_key] = fact
    return selected


def build_supplier_operational_learning_policy(
    *,
    supplier: SupplierMasterProfile,
    learning_repository: LearningFactRepository | None,
    base_first_reminder_minutes: int,
    base_acknowledged_wait_minutes: int,
    acknowledgement_channel: str | None = None,
    as_of: datetime | None = None,
) -> SupplierOperationalLearningPolicy:
    current = _utc(as_of)
    facts = _active_confirmed_facts(learning_repository, supplier.supplier_id)
    evaluations: list[SupplierLearningFactEvaluation] = []
    usable: dict[str, tuple[LearningFact, float, float]] = {}

    for key, fact in facts.items():
        value = _numeric_value(fact)
        expected_unit = _CANONICAL_UNITS[key]
        latest_evidence = _latest_evidence_at(fact)
        raw_age_days = (current - latest_evidence).total_seconds() / 86400
        age_days = max(0.0, raw_age_days)
        recency = _recency_factor(key, raw_age_days)
        effective = round(fact.confidence * recency, 4)
        valid = value is not None and (fact.value_unit or "").casefold() == expected_unit
        bounded = valid and (
            (key.startswith("response.") and value >= 0)
            or (key.startswith("commercial.") and 0 <= value <= 100)
            or ((key.startswith("contact.") or key.startswith("escalation.")) and (
                (key.endswith("_percent") and 0 <= value <= 100)
                or (key.endswith("_minutes") and value >= 0)
            ))
        )
        eligible = bool(bounded and recency > 0)
        reason = "eligible_confirmed_metric"
        if not valid:
            reason = "invalid_metric_value_or_unit"
        elif not bounded:
            reason = "metric_value_out_of_bounds"
        elif raw_age_days < 0:
            reason = "future_evidence_not_authoritative"
        elif recency == 0:
            reason = "evidence_too_old_for_runtime_effect"
        if eligible:
            usable[key] = (fact, float(value), effective)
        evaluations.append(SupplierLearningFactEvaluation(
            fact_id=fact.fact_id,
            fact_key=key,
            value=0.0 if value is None else float(value),
            value_unit=fact.value_unit or "",
            raw_confidence=fact.confidence,
            recency_factor=recency,
            effective_confidence=effective,
            evidence_age_days=round(age_days, 2),
            runtime_eligible=eligible,
            effect="none",
            reason=reason,
        ))

    by_fact_id = {item.fact_id: item for item in evaluations}
    ranking_adjustment = 0.0
    response = usable.get("response.median_minutes")
    if response is not None and response[2] >= RANKING_MIN_EFFECTIVE_CONFIDENCE:
        fact, value, effective = response
        ranking_adjustment += _response_ranking_delta(value) * effective
        by_fact_id[fact.fact_id].effect = "ranking"
        by_fact_id[fact.fact_id].reason = "confirmed_response_metric_affects_bounded_ranking"
    quote_rate = usable.get("commercial.usable_quote_rate_percent")
    if quote_rate is not None and quote_rate[2] >= RANKING_MIN_EFFECTIVE_CONFIDENCE:
        fact, value, effective = quote_rate
        ranking_adjustment += _quote_rate_ranking_delta(value) * effective
        by_fact_id[fact.fact_id].effect = "ranking"
        by_fact_id[fact.fact_id].reason = "confirmed_quote_rate_affects_bounded_ranking"
    ranking_adjustment = max(-MAX_RANKING_ADJUSTMENT, min(MAX_RANKING_ADJUSTMENT, ranking_adjustment))

    relationship = supplier.relationship
    first_minutes = base_first_reminder_minutes
    first_source: TimingSource = "dispatch_default"
    if relationship.first_reminder_minutes is not None:
        first_minutes = relationship.first_reminder_minutes
        first_source = "supplier_master"
    elif response is not None and quote_rate is not None:
        r_fact, response_minutes, response_conf = response
        q_fact, quote_percent, quote_conf = quote_rate
        if (
            response_conf >= TIMING_MIN_EFFECTIVE_CONFIDENCE
            and quote_conf >= TIMING_MIN_EFFECTIVE_CONFIDENCE
            and quote_percent >= MIN_QUOTE_RATE_FOR_PATIENT_TIMING
        ):
            learned = min(MAX_LEARNED_FIRST_REMINDER_MINUTES, _round_up(response_minutes, 5))
            if learned > first_minutes:
                first_minutes = learned
                first_source = "confirmed_learning"
                by_fact_id[r_fact.fact_id].effect = "timing"
                by_fact_id[r_fact.fact_id].reason = "high_confidence_response_history_extends_first_reminder"
                if by_fact_id[q_fact.fact_id].effect == "none":
                    by_fact_id[q_fact.fact_id].effect = "timing"
                    by_fact_id[q_fact.fact_id].reason = "high_quote_rate_supports_patient_supplier_timing"

    ack_minutes = base_acknowledged_wait_minutes
    ack_source: TimingSource = "dispatch_default"
    if relationship.acknowledged_wait_minutes is not None:
        ack_minutes = relationship.acknowledged_wait_minutes
        ack_source = "supplier_master"
    else:
        normalized_ack_channel = (acknowledgement_channel or "").strip().lower()
        channel_after_ack = (
            usable.get(f"contact.{normalized_ack_channel}.after_ack_quote_median_minutes")
            if normalized_ack_channel in {"phone", "whatsapp"} else None
        )
        after_ack = channel_after_ack or usable.get("response.after_ack_median_minutes")
        if after_ack is not None and quote_rate is not None:
            a_fact, after_ack_minutes, after_ack_conf = after_ack
            q_fact, quote_percent, quote_conf = quote_rate
            if (
                after_ack_conf >= TIMING_MIN_EFFECTIVE_CONFIDENCE
                and quote_conf >= TIMING_MIN_EFFECTIVE_CONFIDENCE
                and quote_percent >= MIN_QUOTE_RATE_FOR_PATIENT_TIMING
            ):
                learned = min(MAX_LEARNED_ACK_WAIT_MINUTES, _round_up(after_ack_minutes, 15))
                if learned > ack_minutes:
                    ack_minutes = learned
                    ack_source = "confirmed_learning"
                    by_fact_id[a_fact.fact_id].effect = "timing"
                    by_fact_id[a_fact.fact_id].reason = (
                        "high_confidence_channel_after_ack_history_extends_ack_wait"
                        if channel_after_ack is not None
                        else "high_confidence_after_ack_history_extends_ack_wait"
                    )
                    if by_fact_id[q_fact.fact_id].effect == "none":
                        by_fact_id[q_fact.fact_id].effect = "timing"
                        by_fact_id[q_fact.fact_id].reason = "high_quote_rate_supports_patient_supplier_timing"

    preferred_contact_channel = None
    preferred_contact_reason = None
    phone_rate = usable.get("contact.phone.ack_rate_percent")
    whatsapp_rate = usable.get("contact.whatsapp.ack_rate_percent")
    if phone_rate is not None and whatsapp_rate is not None:
        p_fact, p_rate, p_conf = phone_rate
        w_fact, w_rate, w_conf = whatsapp_rate
        if p_conf >= CONTACT_MIN_EFFECTIVE_CONFIDENCE and w_conf >= CONTACT_MIN_EFFECTIVE_CONFIDENCE:
            difference = abs(p_rate - w_rate)
            winner_rate = max(p_rate, w_rate)
            if difference >= CONTACT_MIN_RATE_ADVANTAGE and winner_rate >= CONTACT_MIN_WINNER_RATE:
                preferred_contact_channel = "phone" if p_rate > w_rate else "whatsapp"
                preferred_contact_reason = (
                    f"confirmed_contact_ack_rate_advantage_{round(difference, 1)}pp"
                )
                winner_fact = p_fact if preferred_contact_channel == "phone" else w_fact
                by_fact_id[winner_fact.fact_id].effect = "advisory"
                by_fact_id[winner_fact.fact_id].reason = "confirmed_contact_history_supports_channel_advisory"

    preferred_escalation_channel = None
    preferred_escalation_reason = None
    escalation_phone = usable.get("escalation.phone.ack_rate_percent")
    escalation_whatsapp = usable.get("escalation.whatsapp.ack_rate_percent")
    if escalation_phone is not None and escalation_whatsapp is not None:
        ep_fact, ep_rate, ep_conf = escalation_phone
        ew_fact, ew_rate, ew_conf = escalation_whatsapp
        if ep_conf >= ESCALATION_MIN_EFFECTIVE_CONFIDENCE and ew_conf >= ESCALATION_MIN_EFFECTIVE_CONFIDENCE:
            difference = abs(ep_rate - ew_rate)
            winner_rate = max(ep_rate, ew_rate)
            if difference >= ESCALATION_MIN_RATE_ADVANTAGE and winner_rate >= ESCALATION_MIN_WINNER_RATE:
                preferred_escalation_channel = "phone" if ep_rate > ew_rate else "whatsapp"
                preferred_escalation_reason = f"confirmed_escalation_ack_rate_advantage_{round(difference, 1)}pp"
                winner_fact = ep_fact if preferred_escalation_channel == "phone" else ew_fact
                by_fact_id[winner_fact.fact_id].effect = "advisory"
                by_fact_id[winner_fact.fact_id].reason = "confirmed_escalation_history_supports_channel_advisory"

    management_advisory = False
    management = usable.get("escalation.management.ack_rate_percent")
    if management is not None:
        m_fact, m_rate, m_conf = management
        if m_conf >= ESCALATION_MIN_EFFECTIVE_CONFIDENCE and m_rate >= MANAGEMENT_MIN_SUCCESS_RATE:
            management_advisory = True
            by_fact_id[m_fact.fact_id].effect = "advisory"
            by_fact_id[m_fact.fact_id].reason = "confirmed_management_escalation_history_supports_advisory"

    negotiation_advisory = None
    negotiation = usable.get("commercial.negotiated_reduction_percent")
    if negotiation is not None:
        n_fact, reduction, effective = negotiation
        if effective >= NEGOTIATION_MIN_EFFECTIVE_CONFIDENCE and 2 <= reduction <= 30:
            negotiation_advisory = round(reduction, 2)
            by_fact_id[n_fact.fact_id].effect = "advisory"
            by_fact_id[n_fact.fact_id].reason = "confirmed_negotiation_history_is_advisory_only"

    return SupplierOperationalLearningPolicy(
        supplier_id=supplier.supplier_id,
        supplier_name=supplier.supplier_name,
        ranking_adjustment=round(ranking_adjustment, 4),
        effective_first_reminder_minutes=first_minutes,
        first_reminder_source=first_source,
        effective_acknowledged_wait_minutes=ack_minutes,
        acknowledged_wait_source=ack_source,
        negotiation_advisory_percent=negotiation_advisory,
        preferred_contact_channel_advisory=preferred_contact_channel,
        preferred_contact_channel_reason=preferred_contact_reason,
        preferred_escalation_channel_advisory=preferred_escalation_channel,
        preferred_escalation_channel_reason=preferred_escalation_reason,
        management_escalation_advisory=management_advisory,
        acknowledgement_channel_context=(
            acknowledgement_channel if acknowledgement_channel in {"email", "phone", "whatsapp", "manual"} else None
        ),
        contact_escalation_learning_applied=bool(preferred_escalation_channel or management_advisory),
        evaluations=list(by_fact_id.values()),
    )


def resolve_supplier_operational_learning_policy(
    *,
    supplier_name: str,
    master_data_repository: Any | None,
    learning_repository: LearningFactRepository | None,
    base_first_reminder_minutes: int,
    base_acknowledged_wait_minutes: int,
    acknowledgement_channel: str | None = None,
    as_of: datetime | None = None,
) -> SupplierOperationalLearningPolicy | None:
    if master_data_repository is None or not supplier_name.strip():
        return None
    supplier = master_data_repository.find_supplier_by_name(supplier_name)
    if supplier is None or not supplier.active:
        return None
    resolved_learning = learning_repository
    if resolved_learning is None and getattr(master_data_repository, "store", None) is not None:
        from src.core.learning_fact_repository import SQLiteLearningFactRepository
        resolved_learning = SQLiteLearningFactRepository(master_data_repository.store)
    return build_supplier_operational_learning_policy(
        supplier=supplier,
        learning_repository=resolved_learning,
        base_first_reminder_minutes=base_first_reminder_minutes,
        base_acknowledged_wait_minutes=base_acknowledged_wait_minutes,
        acknowledgement_channel=acknowledgement_channel,
        as_of=as_of,
    )
