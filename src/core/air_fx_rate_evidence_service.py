from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from src.core.air_fx_rate_evidence import AirFxRateEvidence
from src.core.air_fx_rate_evidence_repository import (
    AirFxRateEvidenceConflictError,
    AirFxRateEvidenceRepository,
)
from src.core.air_shadow_repository import AirShadowRepository


class AirFxRateEvidenceNotFoundError(ValueError):
    pass


class AirFxRateEvidenceTransitionError(ValueError):
    pass


def record_air_fx_rate_evidence(
    *,
    source_id: str,
    entry_id: str,
    inquiry_reference: str,
    base_currency: str,
    quote_currency: str,
    rate: Decimal,
    effective_at: datetime,
    evidence_source: str,
    evidence_reference: str,
    evidence_note: str,
    recorded_by: str,
    source_repository: AirShadowRepository,
    repository: AirFxRateEvidenceRepository,
    recorded_at: datetime | None = None,
) -> tuple[AirFxRateEvidence, bool]:
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirFxRateEvidenceNotFoundError(f"Air rate source not found: {source_id}")
    try:
        item = AirFxRateEvidence(
            entry_id=entry_id,
            inquiry_reference=inquiry_reference,
            source_id=source.source_id,
            source_sha256=source.sha256_hex,
            base_currency=base_currency,
            quote_currency=quote_currency,
            rate=rate,
            effective_at=effective_at,
            evidence_source=evidence_source,
            evidence_reference=evidence_reference,
            evidence_note=evidence_note,
            recorded_by=recorded_by,
            recorded_at=recorded_at or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise AirFxRateEvidenceTransitionError(str(exc)) from exc
    try:
        return repository.create(item)
    except AirFxRateEvidenceConflictError as exc:
        raise AirFxRateEvidenceTransitionError(str(exc)) from exc


def build_air_fx_rate_evidence_view(*, repository: AirFxRateEvidenceRepository) -> dict:
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
    }
