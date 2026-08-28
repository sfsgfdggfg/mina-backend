from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.core.cargo_weight import assess_cargo_weight
from src.core.commodity_profile import (
    get_commodity_record,
    load_commodity_dictionary,
    normalize_commodity_value,
)
from src.core.models import Shipment
from src.core.pilot_access import pilot_mode_enabled


PILOT_SCOPE_EXCLUDED = "pilot_scope_excluded"
PILOT_SCOPE_ELIGIBLE = "pilot_scope_eligible"

_MEDICAL_COMMODITIES = {
    normalize_commodity_value("Medikal Ürün"),
    normalize_commodity_value("İlaç / Pharma"),
}
_CHEMICAL_COMMODITIES = {
    normalize_commodity_value("Kimyasal Ürün"),
}
_PROJECT_CARGO_SIGNALS = {
    "project cargo",
    "proje yuk",
    "oversize",
    "gabari disi",
    "lowbed",
    "heavy haul",
    "agir yuk",
}


class PilotScopeDecision(BaseModel):
    eligible: bool
    result_type: Literal[
        "pilot_scope_eligible",
        "pilot_scope_excluded",
    ]
    reasons: list[str] = Field(default_factory=list)
    source: str = "pilot_scope_engine"


def _append_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _commodity_classification(shipment: Shipment) -> str:
    record = get_commodity_record(shipment.commodity)
    normalized_commodity = normalize_commodity_value(shipment.commodity)
    if record is None and normalized_commodity:
        record = next(
            (
                item
                for item in load_commodity_dictionary()
                if any(
                    normalize_commodity_value(signal) in normalized_commodity
                    for signal in [
                        item.get("canonical_commodity"),
                        *(item.get("keywords") or []),
                    ]
                    if normalize_commodity_value(signal)
                )
            ),
            None,
        )
    canonical = (
        record.get("canonical_commodity")
        if isinstance(record, dict)
        else shipment.commodity
    )
    return normalize_commodity_value(canonical)


def _project_cargo_text(shipment: Shipment) -> str:
    values = [
        shipment.commodity,
        shipment.equipment_type,
        shipment.special_notes,
        *(package.package_type for package in shipment.packages),
    ]
    return normalize_commodity_value(
        " ".join(str(value) for value in values if value)
    )


def _response_currency(response: Any) -> str | None:
    if isinstance(response, Mapping):
        currency = response.get("currency")
        status = response.get("status")
    else:
        currency = getattr(response, "currency", None)
        status = getattr(response, "status", None)
    if status != "quoted" or not currency:
        return None
    return str(currency).strip().upper() or None


def evaluate_pilot_scope(
    shipment: Shipment,
    *,
    supplier_responses: Iterable[Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> PilotScopeDecision:
    if not pilot_mode_enabled(environ):
        return PilotScopeDecision(
            eligible=True,
            result_type=PILOT_SCOPE_ELIGIBLE,
        )

    reasons: list[str] = []

    if shipment.transport_mode is None:
        _append_reason(reasons, "Transport mode is not confirmed as road freight.")
    elif shipment.transport_mode != "road":
        _append_reason(
            reasons,
            f"Transport mode '{shipment.transport_mode}' is outside road-only pilot scope.",
        )

    if shipment.is_adr:
        _append_reason(reasons, "ADR cargo is excluded from the shadow pilot.")

    if shipment.is_temperature_controlled:
        _append_reason(
            reasons,
            "Temperature-controlled or reefer cargo is excluded from the shadow pilot.",
        )
    if shipment.temperature_requirement and shipment.temperature_requirement.strip():
        _append_reason(
            reasons,
            "A temperature requirement places the cargo outside shadow-pilot scope.",
        )


    classification = _commodity_classification(shipment)
    if classification in _MEDICAL_COMMODITIES:
        _append_reason(reasons, "Medical or pharmaceutical cargo is excluded.")
    if classification in _CHEMICAL_COMMODITIES:
        _append_reason(reasons, "Chemical cargo is excluded from the shadow pilot.")

    for package in shipment.packages:
        if package.width_cm is not None and package.width_cm > 250:
            _append_reason(reasons, "Oversize cargo width exceeds 250 cm.")
        if package.height_cm is not None and package.height_cm > 300:
            _append_reason(reasons, "Oversize cargo height exceeds 300 cm.")

    cargo_weight = assess_cargo_weight(shipment)
    if cargo_weight.is_confirmed_heavy_single_piece:
        _append_reason(
            reasons,
            "Confirmed heavy single-piece cargo is outside simple pilot scope.",
        )
    elif cargo_weight.requires_clarification:
        _append_reason(
            reasons,
            "Potential heavy cargo requires clarification outside simple pilot scope.",
        )

    project_text = _project_cargo_text(shipment)
    if any(signal in project_text for signal in _PROJECT_CARGO_SIGNALS):
        _append_reason(reasons, "Project or explicitly oversize cargo is excluded.")

    currencies = {
        currency
        for response in supplier_responses or []
        if (currency := _response_currency(response)) is not None
    }
    if len(currencies) > 1:
        _append_reason(
            reasons,
            "Mixed supplier quote currencies are excluded: "
            + ", ".join(sorted(currencies)),
        )

    return PilotScopeDecision(
        eligible=not reasons,
        result_type=(
            PILOT_SCOPE_ELIGIBLE if not reasons else PILOT_SCOPE_EXCLUDED
        ),
        reasons=reasons,
    )
