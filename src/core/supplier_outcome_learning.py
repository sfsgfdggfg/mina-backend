from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from src.core.learning_fact import LearningEvidence, LearningFact
from src.core.learning_fact_repository import LearningFactRepository
from src.core.learning_fact_service import create_learning_fact
from src.core.master_data_repository import MasterDataRepository
from src.core.quote_case_repository import QuoteCaseRepository
from src.core.supplier_context import shipment_context_keys
from src.core.supplier_customer_context import (
    resolve_customer_master_profile,
    supplier_customer_context_keys,
)

OUTCOME_MIN_SAMPLE_COUNT = 5
OUTCOME_FACT_KEYS = {
    "operation.on_time_delivery_rate_percent",
    "operation.problematic_outcome_rate_percent",
    "operation.actual_delay_rate_percent",
    "operation.damage_incident_rate_percent",
    "operation.choose_again_rate_percent",
}


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("Supplier outcome learning timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


def _confidence(sample_count: int) -> float:
    return min(0.95, round(0.58 + 0.04 * sample_count, 4))


def _active_confirmed(
    repository: LearningFactRepository,
    *, supplier_id: str, fact_key: str, context_key: str | None,
) -> LearningFact | None:
    candidates = [
        item for item in repository.list_all()
        if item.status == "confirmed" and item.subject_type == "supplier"
        and item.subject_id == supplier_id and item.fact_key == fact_key
        and item.context_key == context_key
    ]
    return max(candidates, key=lambda item: (item.updated_at, item.fact_id)) if candidates else None


def _metrics(items: list[tuple[Any, Any]]) -> list[tuple[str, float, int]]:
    total = len(items)
    if total < OUTCOME_MIN_SAMPLE_COUNT:
        return []
    feedback = [item[1] for item in items]
    metrics: list[tuple[str, float, int]] = [
        (
            "operation.problematic_outcome_rate_percent",
            round(100 * sum(item.overall_outcome == "problematic" for item in feedback) / total, 2),
            total,
        ),
        (
            "operation.actual_delay_rate_percent",
            round(100 * sum(item.actual_delay_count > 0 for item in feedback) / total, 2),
            total,
        ),
        (
            "operation.damage_incident_rate_percent",
            round(100 * sum(item.damage_exception_count > 0 for item in feedback) / total, 2),
            total,
        ),
        (
            "operation.choose_again_rate_percent",
            round(100 * sum(item.would_choose_again == "yes" for item in feedback) / total, 2),
            total,
        ),
    ]
    measurable = [item for item in feedback if item.on_time_delivery is not None]
    if len(measurable) >= OUTCOME_MIN_SAMPLE_COUNT:
        metrics.append((
            "operation.on_time_delivery_rate_percent",
            round(100 * sum(item.on_time_delivery is True for item in measurable) / len(measurable), 2),
            len(measurable),
        ))
    return metrics


def _fingerprint(
    *, supplier_id: str, context_key: str | None, items: list[tuple[Any, Any]], metrics,
) -> str:
    payload = {
        "supplier_id": supplier_id,
        "context_key": context_key,
        "feedback": [
            {
                "feedback_id": feedback.feedback_id,
                "job_id": feedback.job_id,
                "overall_outcome": feedback.overall_outcome,
                "on_time_delivery": feedback.on_time_delivery,
                "actual_delay": feedback.actual_delay_count > 0,
                "damage": feedback.damage_exception_count > 0,
                "would_choose_again": feedback.would_choose_again,
                "recorded_at": _aware(feedback.recorded_at).isoformat(),
            }
            for _case, feedback in sorted(items, key=lambda pair: pair[1].feedback_id)
        ],
        "metrics": [(key, value, sample_count) for key, value, sample_count in metrics],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]


def _propose_metrics(
    *, supplier, context_key: str | None, items: list[tuple[Any, Any]],
    learning_repository: LearningFactRepository,
    master_repository: MasterDataRepository,
    created_by: str, occurred_at: datetime,
) -> list[LearningFact]:
    metrics = _metrics(items)
    if not metrics:
        return []
    digest = _fingerprint(
        supplier_id=supplier.supplier_id, context_key=context_key, items=items, metrics=metrics,
    )
    latest_observed = max(_aware(feedback.recorded_at) for _case, feedback in items)
    feedback_count = len(items)
    on_time_known = sum(feedback.on_time_delivery is not None for _case, feedback in items)
    context_text = context_key or "global"
    scope_token = (
        "global" if context_key is None
        else hashlib.sha256(context_key.encode("utf-8")).hexdigest()[:12]
    )
    evidence = LearningEvidence(
        source_type="operation_history",
        source_reference=f"supplier-outcomes:{supplier.supplier_id}:{digest}",
        observed_at=latest_observed,
        dataset_key=(context_key or "supplier_outcome_v1")[:120],
        summary=(
            f"Derived from {feedback_count} final selected-supplier outcome records for {supplier.supplier_name} "
            f"in {context_text}; on-time measurable={on_time_known}. Rates count affected jobs, not incident totals. "
            "Unselected suppliers receive no counterfactual outcome."
        ),
    )
    proposals: list[LearningFact] = []
    for fact_key, value, sample_count in metrics:
        confidence = _confidence(sample_count)
        active = _active_confirmed(
            learning_repository,
            supplier_id=supplier.supplier_id,
            fact_key=fact_key,
            context_key=context_key,
        )
        if active is not None and active.value == value and active.value_unit == "percent":
            active_observed = max(_aware(item.observed_at) for item in active.evidence)
            if active.confidence >= confidence and active_observed >= latest_observed:
                continue
        fact = create_learning_fact(
            repository=learning_repository,
            entry_id=f"supplier-outcome:{supplier.supplier_id}:{fact_key}:{scope_token}:{digest}",
            subject_type="supplier",
            subject_id=supplier.supplier_id,
            subject_label=supplier.supplier_name,
            fact_key=fact_key,
            context_key=context_key,
            value=value,
            value_unit="percent",
            confidence=confidence,
            source_type="minai_inference",
            evidence=[evidence],
            created_by=created_by,
            supersedes_fact_id=None if active is None else active.fact_id,
            occurred_at=occurred_at,
            master_repository=master_repository,
        )
        proposals.append(fact)
    return proposals


def derive_supplier_outcome_learning(
    *, supplier_id: str, master_repository: MasterDataRepository,
    quote_case_repository: QuoteCaseRepository, learning_repository: LearningFactRepository,
    created_by: str, occurred_at: datetime | None = None,
) -> dict[str, Any]:
    supplier = master_repository.get_supplier(supplier_id)
    if supplier is None:
        raise KeyError(supplier_id)
    timestamp = occurred_at or datetime.now(timezone.utc)
    timestamp = _aware(timestamp)
    normalized_name = supplier.supplier_name.strip().casefold()
    eligible: list[tuple[Any, Any]] = []
    excluded_integrity_count = 0
    for case in quote_case_repository.list_all():
        feedback = case.supplier_decision_outcome_feedback
        if feedback is None or feedback.supplier_name.strip().casefold() != normalized_name:
            continue
        decision = case.supplier_quote_selection_decision
        if (
            decision is None
            or decision.selected_supplier.strip().casefold() != normalized_name
            or (case.mina_job_id is not None and feedback.job_id != case.mina_job_id)
            or feedback.case_id != case.case_id
        ):
            excluded_integrity_count += 1
            continue
        eligible.append((case, feedback))

    global_proposals = _propose_metrics(
        supplier=supplier,
        context_key=None,
        items=eligible,
        learning_repository=learning_repository,
        master_repository=master_repository,
        created_by=created_by,
        occurred_at=timestamp,
    )
    contextual_groups: dict[str, list[tuple[Any, Any]]] = {}
    customer_contextual_groups: dict[str, list[tuple[Any, Any]]] = {}
    unmatched_customer_context_count = 0
    for case, feedback in eligible:
        for context_key in shipment_context_keys(case.shipment):
            contextual_groups.setdefault(context_key, []).append((case, feedback))
        customer = resolve_customer_master_profile(
            customer_name=case.shipment.customer_name, master_repository=master_repository,
        )
        if customer is None:
            unmatched_customer_context_count += 1
            continue
        for context_key in supplier_customer_context_keys(
            case.shipment, customer_id=customer.customer_id,
        ):
            customer_contextual_groups.setdefault(context_key, []).append((case, feedback))
    contextual_proposals: list[LearningFact] = []
    for context_key, items in sorted(contextual_groups.items()):
        contextual_proposals.extend(_propose_metrics(
            supplier=supplier,
            context_key=context_key,
            items=items,
            learning_repository=learning_repository,
            master_repository=master_repository,
            created_by=created_by,
            occurred_at=timestamp,
        ))
    customer_contextual_proposals: list[LearningFact] = []
    for context_key, items in sorted(customer_contextual_groups.items()):
        customer_contextual_proposals.extend(_propose_metrics(
            supplier=supplier,
            context_key=context_key,
            items=items,
            learning_repository=learning_repository,
            master_repository=master_repository,
            created_by=created_by,
            occurred_at=timestamp,
        ))
    return {
        "supplier_id": supplier.supplier_id,
        "supplier_name": supplier.supplier_name,
        "outcome_feedback_count": len(eligible),
        "excluded_integrity_count": excluded_integrity_count,
        "minimum_sample_count": OUTCOME_MIN_SAMPLE_COUNT,
        "proposed_fact_count": len(global_proposals),
        "proposed_facts": [item.model_dump() for item in global_proposals],
        "contextual_proposed_fact_count": len(contextual_proposals),
        "contextual_proposed_facts": [item.model_dump() for item in contextual_proposals],
        "customer_contextual_proposed_fact_count": len(customer_contextual_proposals),
        "customer_contextual_proposed_facts": [
            item.model_dump() for item in customer_contextual_proposals
        ],
        "unmatched_customer_context_count": unmatched_customer_context_count,
        "note": (
            "Outcome-derived facts are selected-supplier observations only. They remain proposed until human review, "
            "and runtime ranking requires an additional effective-confidence threshold."
        ),
    }
