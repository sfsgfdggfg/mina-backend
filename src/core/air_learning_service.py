from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from statistics import median
from typing import Any

from src.core.air_learning_feedback import AirLearningFeedback
from src.core.air_learning_feedback_repository import (
    AirLearningFeedbackConflictError,
    AirLearningFeedbackRepository,
)
from src.core.air_operation_handoff_repository import AirOperationHandoffRepository
from src.core.air_quote_context import AirQuoteContextSnapshot
from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.mina_job import MinaJobEvent
from src.core.mina_job_repository import MinaJobRepository
from src.core.sqlite_repositories import atomic_repository_transaction


AIR_VARIANCE_MIN_SAMPLE_COUNT = 3
AIR_RATE_MIN_SAMPLE_COUNT = 5
AIR_CORRECTION_MIN_SAMPLE_COUNT = 3
AIR_FACT_KEYS = {
    "air.cost_basis_variance_median_percent",
    "air.chargeable_weight_variance_median_percent",
    "air.quoted_tariff_exact_use_rate_percent",
    "air.route_plan_unchanged_rate_percent",
    "air.expected_delivery_met_rate_percent",
    "air.frequent_correction_categories",
}


class AirLearningTransitionError(ValueError):
    pass


def _aware(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Air learning timestamp must be timezone-aware.")
    return current.astimezone(timezone.utc)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.strip().casefold()).strip("-")
    return normalized or "unknown"


def air_route_subject_from_parts(
    *, origin_airport: str, destination_code: str, airline_name: str,
    routing_context: str, via_airport: str | None = None,
) -> tuple[str, str]:
    origin = str(origin_airport or "").strip().upper()
    destination = str(destination_code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", origin) or not re.fullmatch(r"[A-Z]{3}", destination):
        raise AirLearningTransitionError(
            "Air learning requires exact three-letter origin and destination IATA codes."
        )
    if routing_context not in {"direct", "connecting"}:
        raise AirLearningTransitionError("Air learning routing context must be direct or connecting.")
    via = str(via_airport or "").strip().upper()
    if routing_context == "direct" and via:
        raise AirLearningTransitionError("Direct air learning context cannot carry a via airport.")
    if routing_context == "connecting" and not re.fullmatch(r"[A-Z]{3}", via):
        raise AirLearningTransitionError("Connecting air learning context requires a three-letter via airport.")
    airline = _slug(airline_name)
    subject_id = (
        f"air:{origin.casefold()}>{destination.casefold()}|airline={airline}|"
        f"routing={routing_context}"
    )
    if via:
        subject_id += f"|via={via.casefold()}"
    label = f"{origin}→{destination} · {airline_name.strip()} · {routing_context}"
    if via:
        label += f" via {via}"
    return subject_id, label


def air_route_subject(context: AirQuoteContextSnapshot) -> tuple[str, str]:
    return air_route_subject_from_parts(
        origin_airport=context.origin_airport or "",
        destination_code=context.destination_code or "",
        airline_name=context.airline_name,
        routing_context=context.routing_context,
        via_airport=context.via_airport,
    )


def current_air_learning_feedback(
    repository: AirLearningFeedbackRepository, *, job_id: str,
) -> AirLearningFeedback | None:
    items = repository.list_for_job(job_id)
    if not items:
        return None
    superseded = {item.supersedes_feedback_id for item in items if item.supersedes_feedback_id}
    active = [item for item in items if item.feedback_id not in superseded]
    if len(active) > 1:
        raise AirLearningFeedbackConflictError(
            "Air learning feedback history has multiple active records for one MINA job."
        )
    return active[0] if active else None


def _current_all(repository: AirLearningFeedbackRepository) -> tuple[list[AirLearningFeedback], int]:
    grouped: dict[str, list[AirLearningFeedback]] = {}
    for item in repository.list_all():
        grouped.setdefault(item.job_id, []).append(item)
    current: list[AirLearningFeedback] = []
    integrity_excluded = 0
    for items in grouped.values():
        superseded = {item.supersedes_feedback_id for item in items if item.supersedes_feedback_id}
        active = [item for item in items if item.feedback_id not in superseded]
        if len(active) != 1:
            integrity_excluded += 1
            continue
        current.append(active[0])
    return current, integrity_excluded


def record_air_learning_feedback(
    *,
    feedback_repository: AirLearningFeedbackRepository,
    handoff_repository: AirOperationHandoffRepository,
    mina_repository: MinaJobRepository,
    job_id: str,
    entry_id: str,
    tariff_usage: str,
    actual_airline_name: str,
    actual_routing_context: str,
    evidence_source: str,
    source_reference: str,
    note: str,
    recorded_by: str,
    actual_via_airport: str | None = None,
    actual_service_date=None,
    actual_delivery_date=None,
    actual_chargeable_weight_kg=None,
    actual_cost_amount=None,
    actual_cost_currency: str | None = None,
    correction_categories: list[str] | None = None,
    supersedes_feedback_id: str | None = None,
    occurred_at: datetime | None = None,
) -> AirLearningFeedback:
    timestamp = _aware(occurred_at)
    actor = str(recorded_by or "").strip()
    if not actor:
        raise ValueError("Air learning feedback operator identity is required.")
    normalized_job = str(job_id or "").strip()
    normalized_entry = str(entry_id or "").strip()
    if not normalized_job or not normalized_entry:
        raise ValueError("Air learning feedback job_id and entry_id are required.")

    with atomic_repository_transaction(feedback_repository, mina_repository):
        job = mina_repository.get(normalized_job)
        if job is None:
            raise KeyError(normalized_job)
        if job.lifecycle_version != 2 or job.shipment.transport_mode != "air":
            raise AirLearningTransitionError(
                "Air learning feedback requires a lifecycle-v2 air MINA job."
            )
        handoff = handoff_repository.find_by_job(job.job_id)
        if handoff is None:
            raise AirLearningTransitionError(
                "Air learning feedback requires a durable accepted-quote operation handoff."
            )
        if job.quote_case_id != handoff.quote_case_id:
            raise AirLearningTransitionError("Air learning handoff no longer matches the MINA quote case.")
        if timestamp < handoff.handed_off_at.astimezone(timezone.utc):
            raise AirLearningTransitionError("Air learning feedback cannot precede the durable operation handoff.")
        air_route_subject(handoff.air_quote_context)

        current = current_air_learning_feedback(feedback_repository, job_id=job.job_id)

        item = AirLearningFeedback(
            entry_id=normalized_entry,
            job_id=job.job_id,
            mina_code=job.mina_code,
            handoff_id=handoff.handoff_id,
            supersedes_feedback_id=supersedes_feedback_id,
            quoted_air_context=handoff.air_quote_context,
            tariff_usage=tariff_usage,
            actual_airline_name=actual_airline_name,
            actual_routing_context=actual_routing_context,
            actual_via_airport=actual_via_airport,
            actual_service_date=actual_service_date,
            actual_delivery_date=actual_delivery_date,
            actual_chargeable_weight_kg=actual_chargeable_weight_kg,
            actual_cost_amount=actual_cost_amount,
            actual_cost_currency=actual_cost_currency,
            correction_categories=list(correction_categories or []),
            evidence_source=evidence_source,
            source_reference=source_reference,
            note=note,
            recorded_by=actor,
            recorded_at=timestamp,
        )
        existing = feedback_repository.find_by_entry(normalized_entry)
        if existing is not None:
            saved, _ = feedback_repository.create(item)
            return saved
        if current is None and supersedes_feedback_id is not None:
            raise AirLearningTransitionError("First air learning feedback cannot supersede a missing record.")
        if current is not None and supersedes_feedback_id != current.feedback_id:
            raise AirLearningTransitionError(
                "A new air learning feedback revision must explicitly supersede the current feedback record."
            )
        saved, created = feedback_repository.create(item)
        if created:
            mina_repository.append_event(MinaJobEvent(
                job_id=job.job_id,
                mina_code=job.mina_code,
                event_type="air_learning_feedback_recorded",
                occurred_at=timestamp,
                actor=actor,
                resource_type="air_learning_feedback",
                resource_id=saved.feedback_id,
                metadata={
                    "tariff_usage": saved.tariff_usage,
                    "correction_categories": list(saved.correction_categories),
                    "actual_airline_name": saved.actual_airline_name,
                    "actual_routing_context": saved.actual_routing_context,
                    "has_actual_cost": saved.actual_cost_amount is not None,
                    "has_actual_chargeable_weight": saved.actual_chargeable_weight_kg is not None,
                    "supersedes_feedback_id": saved.supersedes_feedback_id,
                },
            ))
            mina_repository.save(job.model_copy(update={"updated_at": timestamp}))
        elif existing is None:
            raise AirLearningFeedbackConflictError("Air learning feedback persistence did not create evidence.")
        return saved


def _active_confirmed(
    repository: LearningFactRepository, *, subject_id: str, fact_key: str,
) -> LearningFact | None:
    candidates = [
        item for item in repository.list_all()
        if item.status == "confirmed" and item.subject_type == "route"
        and item.subject_id == subject_id and item.fact_key == fact_key and item.context_key is None
    ]
    return max(candidates, key=lambda item: (item.updated_at, item.fact_id)) if candidates else None


def _confidence(sample_count: int) -> float:
    return min(0.95, round(0.56 + 0.04 * sample_count, 4))


def _proposal(
    *, repository: LearningFactRepository, subject_id: str, subject_label: str,
    fact_key: str, value: Any, value_unit: str | None, sample_count: int,
    feedback_ids: list[str], latest_observed: datetime, summary: str,
    dataset_key: str, created_by: str, occurred_at: datetime,
) -> LearningFact | None:
    normalized_value = round(value, 2) if isinstance(value, float) else value
    payload = {
        "subject_id": subject_id,
        "fact_key": fact_key,
        "value": normalized_value,
        "value_unit": value_unit,
        "sample_count": sample_count,
        "feedback_ids": sorted(feedback_ids),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    active = _active_confirmed(repository, subject_id=subject_id, fact_key=fact_key)
    confidence = _confidence(sample_count)
    if active is not None and active.value == normalized_value and active.value_unit == value_unit:
        active_observed = max(item.observed_at.astimezone(timezone.utc) for item in active.evidence)
        if active.confidence >= confidence and active_observed >= latest_observed:
            return None
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference=f"air-route-feedback:{subject_id}:{digest}"[:300],
        observed_at=latest_observed,
        dataset_key=dataset_key[:120],
        summary=summary,
    )
    return create_learning_fact(
        repository=repository,
        entry_id=f"air-route:{fact_key}:{digest}"[:300],
        subject_type="route",
        subject_id=subject_id,
        subject_label=subject_label,
        fact_key=fact_key,
        value=normalized_value,
        value_unit=value_unit,
        confidence=confidence,
        source_type="minai_inference",
        evidence=[evidence],
        created_by=created_by,
        supersedes_fact_id=None if active is None else active.fact_id,
        occurred_at=occurred_at,
    )


def _route_unchanged(item: AirLearningFeedback) -> bool:
    context = item.quoted_air_context
    return (
        item.actual_airline_name.strip().casefold() == context.airline_name.strip().casefold()
        and item.actual_routing_context == context.routing_context
        and (item.actual_via_airport or "").strip().upper() == (context.via_airport or "").strip().upper()
    )


def derive_air_route_learning(
    *,
    job_id: str,
    feedback_repository: AirLearningFeedbackRepository,
    learning_repository: LearningFactRepository,
    created_by: str,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = _aware(occurred_at)
    anchor = current_air_learning_feedback(feedback_repository, job_id=job_id)
    if anchor is None:
        raise AirLearningTransitionError("Air learning derivation requires current feedback for the MINA job.")
    subject_id, subject_label = air_route_subject(anchor.quoted_air_context)
    current, integrity_excluded = _current_all(feedback_repository)
    items = [
        item for item in current
        if air_route_subject(item.quoted_air_context)[0] == subject_id
        and item.recorded_at.astimezone(timezone.utc) <= timestamp
    ]
    if not items:
        raise AirLearningTransitionError("No eligible air learning feedback remains for this route context.")
    latest = max(item.recorded_at.astimezone(timezone.utc) for item in items)
    feedback_ids = [item.feedback_id for item in items]
    proposals: list[LearningFact] = []

    cost_values: list[float] = []
    for item in items:
        q = item.quoted_air_context
        if (
            item.actual_cost_amount is not None
            and item.actual_cost_currency == q.confirmed_cost_basis_currency
            and q.confirmed_cost_basis_amount > 0
        ):
            cost_values.append(float((item.actual_cost_amount / q.confirmed_cost_basis_amount - 1) * 100))
    if len(cost_values) >= AIR_VARIANCE_MIN_SAMPLE_COUNT:
        fact = _proposal(
            repository=learning_repository, subject_id=subject_id, subject_label=subject_label,
            fact_key="air.cost_basis_variance_median_percent", value=float(median(cost_values)),
            value_unit="percent", sample_count=len(cost_values), feedback_ids=feedback_ids,
            latest_observed=latest, created_by=created_by, occurred_at=timestamp,
            dataset_key="air_cost_basis_variance_v1",
            summary=(
                f"Median signed actual-vs-confirmed cost-basis variance from {len(cost_values)} same-currency air outcomes "
                f"within {subject_label}. Different-currency outcomes are excluded without explicit FX normalization. "
                "This is advisory accuracy evidence and creates no tariff or pricing authority."
            ),
        )
        if fact is not None:
            proposals.append(fact)

    weight_values: list[float] = []
    for item in items:
        quoted = item.quoted_air_context.quoted_chargeable_weight_kg
        if item.actual_chargeable_weight_kg is not None and quoted is not None and quoted > 0:
            weight_values.append(float((item.actual_chargeable_weight_kg / quoted - 1) * 100))
    if len(weight_values) >= AIR_VARIANCE_MIN_SAMPLE_COUNT:
        fact = _proposal(
            repository=learning_repository, subject_id=subject_id, subject_label=subject_label,
            fact_key="air.chargeable_weight_variance_median_percent", value=float(median(weight_values)),
            value_unit="percent", sample_count=len(weight_values), feedback_ids=feedback_ids,
            latest_observed=latest, created_by=created_by, occurred_at=timestamp,
            dataset_key="air_chargeable_weight_variance_v1",
            summary=(
                f"Median actual-vs-quoted chargeable-weight variance from {len(weight_values)} air outcomes within "
                f"{subject_label}. Historical P2-42 contexts without frozen quoted chargeable weight are excluded. "
                "The observation is advisory only."
            ),
        )
        if fact is not None:
            proposals.append(fact)

    if len(items) >= AIR_RATE_MIN_SAMPLE_COUNT:
        exact_use = 100 * sum(item.tariff_usage == "used_as_quoted" for item in items) / len(items)
        fact = _proposal(
            repository=learning_repository, subject_id=subject_id, subject_label=subject_label,
            fact_key="air.quoted_tariff_exact_use_rate_percent", value=exact_use,
            value_unit="percent", sample_count=len(items), feedback_ids=feedback_ids,
            latest_observed=latest, created_by=created_by, occurred_at=timestamp,
            dataset_key="air_tariff_exact_use_rate_v1",
            summary=(
                f"Quoted tariff was used without correction in {sum(item.tariff_usage == 'used_as_quoted' for item in items)} "
                f"of {len(items)} explicit air outcome feedback records for {subject_label}. This does not select a tariff automatically."
            ),
        )
        if fact is not None:
            proposals.append(fact)
        unchanged = 100 * sum(_route_unchanged(item) for item in items) / len(items)
        fact = _proposal(
            repository=learning_repository, subject_id=subject_id, subject_label=subject_label,
            fact_key="air.route_plan_unchanged_rate_percent", value=unchanged,
            value_unit="percent", sample_count=len(items), feedback_ids=feedback_ids,
            latest_observed=latest, created_by=created_by, occurred_at=timestamp,
            dataset_key="air_route_plan_unchanged_v1",
            summary=(
                f"Actual airline/routing matched the frozen quoted plan in {sum(_route_unchanged(item) for item in items)} "
                f"of {len(items)} explicit outcomes for {subject_label}. This is descriptive only and creates no routing authority."
            ),
        )
        if fact is not None:
            proposals.append(fact)

    delivery_items = [
        item for item in items
        if item.actual_delivery_date is not None and item.quoted_air_context.expected_delivery_date is not None
    ]
    if len(delivery_items) >= AIR_RATE_MIN_SAMPLE_COUNT:
        met = sum(
            item.actual_delivery_date <= item.quoted_air_context.expected_delivery_date
            for item in delivery_items
        )
        fact = _proposal(
            repository=learning_repository, subject_id=subject_id, subject_label=subject_label,
            fact_key="air.expected_delivery_met_rate_percent", value=100 * met / len(delivery_items),
            value_unit="percent", sample_count=len(delivery_items),
            feedback_ids=[item.feedback_id for item in delivery_items], latest_observed=latest,
            created_by=created_by, occurred_at=timestamp, dataset_key="air_expected_delivery_met_v1",
            summary=(
                f"Actual delivery met the frozen expected-delivery date in {met} of {len(delivery_items)} measurable "
                f"air outcomes for {subject_label}. Missing delivery evidence is excluded, not counted as late."
            ),
        )
        if fact is not None:
            proposals.append(fact)

    if len(items) >= AIR_CORRECTION_MIN_SAMPLE_COUNT:
        counts = Counter(category for item in items for category in item.correction_categories)
        threshold = max(2, math.ceil(len(items) * 0.40))
        recurring = [key for key, count in sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])) if count >= threshold]
        if recurring:
            fact = _proposal(
                repository=learning_repository, subject_id=subject_id, subject_label=subject_label,
                fact_key="air.frequent_correction_categories", value=recurring,
                value_unit="categories", sample_count=len(items), feedback_ids=feedback_ids,
                latest_observed=latest, created_by=created_by, occurred_at=timestamp,
                dataset_key="air_recurring_corrections_v1",
                summary=(
                    f"Recurring correction categories across {len(items)} current air feedback records for {subject_label}; "
                    f"included only categories seen in at least {threshold} jobs. Categories are advisory review prompts, not automatic overrides."
                ),
            )
            if fact is not None:
                proposals.append(fact)

    return {
        "subject_type": "route",
        "subject_id": subject_id,
        "subject_label": subject_label,
        "eligible_feedback_count": len(items),
        "integrity_excluded_job_count": integrity_excluded,
        "cost_variance_sample_count": len(cost_values),
        "chargeable_weight_variance_sample_count": len(weight_values),
        "delivery_sample_count": len(delivery_items),
        "minimum_variance_sample_count": AIR_VARIANCE_MIN_SAMPLE_COUNT,
        "minimum_rate_sample_count": AIR_RATE_MIN_SAMPLE_COUNT,
        "proposed_fact_count": len(proposals),
        "proposed_facts": [item.model_dump(mode="json") for item in proposals],
        "pricing_authority_created": False,
        "tariff_authority_created": False,
        "routing_authority_created": False,
        "booking_authority_created": False,
        "note": (
            "Air feedback produces human-reviewable route advisories only. Confirmed facts are not consumed by "
            "pricing, tariff selection, route selection, booking or outbound execution in P2-44."
        ),
    }


def build_air_route_learning_advisory_for_route(
    *, learning_repository: LearningFactRepository, origin_airport: str, destination_code: str,
    airline_name: str, routing_context: str, via_airport: str | None = None,
) -> dict[str, Any]:
    subject_id, subject_label = air_route_subject_from_parts(
        origin_airport=origin_airport, destination_code=destination_code,
        airline_name=airline_name, routing_context=routing_context, via_airport=via_airport,
    )
    facts = [
        item for item in learning_repository.list_all()
        if item.subject_type == "route" and item.subject_id == subject_id
        and item.status == "confirmed" and item.fact_key in AIR_FACT_KEYS
    ]
    facts.sort(key=lambda item: (item.fact_key, item.updated_at, item.fact_id))
    return {
        "subject_type": "route",
        "subject_id": subject_id,
        "subject_label": subject_label,
        "confirmed_facts": [item.model_dump(mode="json") for item in facts],
        "confirmed_fact_count": len(facts),
        "source_fact_ids": [item.fact_id for item in facts],
        "advisory_only": True,
        "pricing_authority": False,
        "tariff_authority": False,
        "routing_authority": False,
        "booking_authority": False,
        "outbound_authority": False,
        "note": (
            "Confirmed air route learning is shown as historical advisory evidence only. It does not modify the current "
            "tariff, cost calculation, customer price, route, booking or outbound decision."
        ),
    }


def build_air_route_learning_advisory(
    *, learning_repository: LearningFactRepository, context: AirQuoteContextSnapshot,
) -> dict[str, Any]:
    return build_air_route_learning_advisory_for_route(
        learning_repository=learning_repository,
        origin_airport=context.origin_airport or "",
        destination_code=context.destination_code or "",
        airline_name=context.airline_name,
        routing_context=context.routing_context,
        via_airport=context.via_airport,
    )


def build_air_learning_feedback_view(
    *,
    job_id: str,
    feedback_repository: AirLearningFeedbackRepository,
    learning_repository: LearningFactRepository,
    handoff_repository: AirOperationHandoffRepository,
) -> dict[str, Any]:
    history = sorted(
        feedback_repository.list_for_job(job_id),
        key=lambda item: (item.recorded_at, item.feedback_id),
    )
    current = current_air_learning_feedback(feedback_repository, job_id=job_id)
    handoff = handoff_repository.find_by_job(job_id)
    advisory = None
    if handoff is not None:
        advisory = build_air_route_learning_advisory(
            learning_repository=learning_repository, context=handoff.air_quote_context,
        )
    route_facts: list[LearningFact] = []
    if handoff is not None:
        subject_id, _ = air_route_subject(handoff.air_quote_context)
        route_facts = [
            item for item in learning_repository.list_all()
            if item.subject_type == "route" and item.subject_id == subject_id
            and item.fact_key in AIR_FACT_KEYS
        ]
        route_facts.sort(key=lambda item: (item.created_at, item.fact_id))
    return {
        "job_id": job_id,
        "recordable": handoff is not None,
        "current": None if current is None else current.model_dump(mode="json"),
        "history": [item.model_dump(mode="json") for item in history],
        "route_facts": [item.model_dump(mode="json") for item in route_facts],
        "advisory": advisory,
        "pricing_authority": False,
        "tariff_authority": False,
        "routing_authority": False,
        "booking_authority": False,
    }
