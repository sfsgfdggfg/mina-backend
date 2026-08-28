from __future__ import annotations

from datetime import datetime

from src.core.missing_info import MissingInfoResult
from src.core.models import Shipment


_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
)


def _parse_date(value: str | None):
    if not value:
        return None

    normalized = str(value).strip()

    for date_format in _DATE_FORMATS:
        try:
            return datetime.strptime(
                normalized,
                date_format,
            ).date()
        except ValueError:
            continue

    return None


def _normalize_country(value: str | None) -> str:
    return (
        str(value or "")
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ü", "u")
        .replace("Ü", "u")
    )


def _is_turkiye(value: str | None) -> bool:
    return _normalize_country(value) in {
        "turkiye",
        "turkey",
    }


def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def apply_road_rfq_readiness(
    shipment: Shipment,
    base: MissingInfoResult,
) -> MissingInfoResult:
    """Add controlled-pilot road RFQ commercial requirements."""

    if shipment.transport_mode != "road":
        return base

    if getattr(shipment, "quote_mode", "firm") == "indicative":
        missing: list[str] = []
        if not shipment.pickup_country:
            _append_unique(missing, "pickup country")
        if not shipment.delivery_country:
            _append_unique(missing, "delivery country")
        return MissingInfoResult(
            can_continue_to_quote=not missing,
            missing_fields=missing,
            reason=(
                "İndikatif road fiyatı için rota bilgisi yeterli."
                if not missing
                else "İndikatif fiyat için temel rota bilgisi eksik."
            ),
        )

    missing = list(base.missing_fields)
    road_blocking_missing: list[str] = []

    def add_road_missing(value: str) -> None:
        _append_unique(missing, value)
        _append_unique(road_blocking_missing, value)

    if not shipment.pickup_country:
        add_road_missing("pickup country")

    if not shipment.delivery_country:
        add_road_missing("delivery country")

    if (
        shipment.gross_weight_kg is None
        or shipment.gross_weight_kg <= 0
    ):
        add_road_missing("gross weight")

    if not shipment.packages:
        add_road_missing("package count and dimensions")
    else:
        for package in shipment.packages:
            if package.quantity <= 0:
                add_road_missing("package count and dimensions")
                break

            dimensions = (
                package.length_cm,
                package.width_cm,
                package.height_cm,
            )

            if any(
                value is None or value <= 0
                for value in dimensions
            ):
                add_road_missing("package count and dimensions")
                break

    ready_date = _parse_date(shipment.cargo_ready_date)
    required_delivery_provided = bool(
        str(shipment.required_delivery_date or "").strip()
    )
    required_date = _parse_date(
        shipment.required_delivery_date
    )

    if ready_date is None:
        add_road_missing("cargo ready date")

    if required_delivery_provided and (
        required_date is None
        or (
            ready_date is not None
            and required_date < ready_date
        )
    ):
        add_road_missing("required delivery date")

    if (
        shipment.pickup_country
        and not _is_turkiye(shipment.pickup_country)
        and not shipment.pickup_postcode
    ):
        add_road_missing("pickup postcode")

    if (
        shipment.delivery_country
        and not _is_turkiye(shipment.delivery_country)
        and not shipment.delivery_postcode
    ):
        add_road_missing("delivery postcode")

    if not base.can_continue_to_quote or road_blocking_missing:
        return MissingInfoResult(
            can_continue_to_quote=False,
            missing_fields=missing,
            reason=(
                "Karayolu RFQ hazırlamak için kritik ticari "
                "bilgiler eksik veya geçersiz."
            ),
        )

    return MissingInfoResult(
        can_continue_to_quote=True,
        missing_fields=missing,
        reason=(
            base.reason if missing else "Karayolu RFQ bilgileri yeterli."
        ),
    )
