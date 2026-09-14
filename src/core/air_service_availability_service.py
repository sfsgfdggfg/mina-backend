from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from src.core.air_service_availability import AirServiceAvailabilityConfirmation
from src.core.air_service_availability_repository import (
    AirServiceAvailabilityConflictError,
    AirServiceAvailabilityRepository,
)
from src.core.air_shadow_repository import AirShadowRepository


class AirServiceAvailabilityNotFoundError(ValueError):
    pass


class AirServiceAvailabilityTransitionError(ValueError):
    pass


def record_air_service_availability_confirmation(
    *,
    source_id: str,
    entry_id: str,
    inquiry_reference: str,
    destination_code: str,
    routing_context: str,
    service_date: date,
    capacity_status: str,
    schedule_status: str,
    evidence_channel: str,
    evidence_reference: str,
    evidence_note: str,
    confirmed_by: str,
    source_repository: AirShadowRepository,
    repository: AirServiceAvailabilityRepository,
    via_airport: Optional[str] = None,
    flight_reference: Optional[str] = None,
    expected_delivery_date: Optional[date] = None,
    confirmed_at: Optional[datetime] = None,
) -> tuple[AirServiceAvailabilityConfirmation, bool]:
    source = source_repository.get_rate_source(source_id)
    if source is None:
        raise AirServiceAvailabilityNotFoundError(f"Air rate source not found: {source_id}")
    try:
        item = AirServiceAvailabilityConfirmation(
            entry_id=entry_id,
            inquiry_reference=inquiry_reference,
            source_id=source.source_id,
            source_sha256=source.sha256_hex,
            airline_name=source.airline_name,
            destination_code=destination_code,
            routing_context=routing_context,
            via_airport=via_airport,
            service_date=service_date,
            expected_delivery_date=expected_delivery_date,
            capacity_status=capacity_status,
            schedule_status=schedule_status,
            flight_reference=flight_reference,
            evidence_channel=evidence_channel,
            evidence_reference=evidence_reference,
            evidence_note=evidence_note,
            confirmed_by=confirmed_by,
            confirmed_at=confirmed_at or datetime.now(timezone.utc),
        )
    except ValueError as exc:
        raise AirServiceAvailabilityTransitionError(str(exc)) from exc
    try:
        return repository.create(item)
    except AirServiceAvailabilityConflictError as exc:
        raise AirServiceAvailabilityTransitionError(str(exc)) from exc


def build_air_service_availability_view(*, repository: AirServiceAvailabilityRepository) -> dict:
    items = sorted(
        repository.list_all(),
        key=lambda item: (item.confirmed_at, item.confirmation_id),
        reverse=True,
    )
    return {
        "confirmations": [item.model_dump(mode="json") for item in items],
        "runtime_authoritative": False,
        "pricing_authority_enabled": False,
        "booking_authority_enabled": False,
        "cost_preview_consumption_enabled": False,
    }
