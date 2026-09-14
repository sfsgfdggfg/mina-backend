from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.core.air_additional_cost_evidence import AirAdditionalCostEvidence
from src.core.air_additional_cost_evidence_repository import (
    AirAdditionalCostEvidenceConflictError,
    AirAdditionalCostEvidenceRepository,
)
from src.core.air_shadow_repository import AirShadowRepository


class AirAdditionalCostEvidenceNotFoundError(ValueError):
    pass


class AirAdditionalCostEvidenceTransitionError(ValueError):
    pass


def record_air_additional_cost_evidence(
    *,
    source_id: str,
    entry_id: str,
    inquiry_reference: str,
    cost_category: str,
    provider_name: str,
    amount: Decimal,
    currency: str,
    quantity_basis: str,
    evidence_source: str,
    evidence_reference: str,
    evidence_note: str,
    recorded_by: str,
    source_repository: AirShadowRepository,
    repository: AirAdditionalCostEvidenceRepository,
    recorded_at: datetime | None = None,
) -> tuple[AirAdditionalCostEvidence, bool]:
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirAdditionalCostEvidenceNotFoundError(
            f"Air rate source not found: {source_id}"
        )
    try:
        item = AirAdditionalCostEvidence(
            entry_id=entry_id,
            inquiry_reference=inquiry_reference,
            source_id=source.source_id,
            source_sha256=source.sha256_hex,
            cost_category=cost_category,
            provider_name=provider_name,
            amount=amount,
            currency=currency,
            quantity_basis=quantity_basis,
            evidence_source=evidence_source,
            evidence_reference=evidence_reference,
            evidence_note=evidence_note,
            recorded_by=recorded_by,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise AirAdditionalCostEvidenceTransitionError(str(exc)) from exc
    try:
        return repository.create(item)
    except AirAdditionalCostEvidenceConflictError as exc:
        raise AirAdditionalCostEvidenceTransitionError(str(exc)) from exc


def build_air_additional_cost_evidence_view(
    *, repository: AirAdditionalCostEvidenceRepository,
) -> dict:
    items = sorted(
        repository.list_all(),
        key=lambda item: (item.recorded_at, item.evidence_id),
        reverse=True,
    )
    return {
        "evidence": [item.model_dump(mode="json") for item in items],
        "runtime_authoritative": False,
        "pricing_authority_enabled": False,
        "cost_preview_consumption_enabled": False,
        "automatic_fx_enabled": False,
        "customer_quote_eligible": False,
        "duties_and_taxes_supported": False,
        "variable_or_weight_based_costs_supported": False,
    }
