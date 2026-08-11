from pydantic import BaseModel, Field
from typing import List
from src.core.models import Shipment
from src.core.commodity_profile import get_commodity_operational_profile
from src.core.cargo_weight import assess_cargo_weight


class MissingInfoResult(BaseModel):
    can_continue_to_quote: bool = True
    missing_fields: List[str] = Field(default_factory=list)
    reason: str = ""


def check_missing_information(shipment: Shipment) -> MissingInfoResult:
    """
    Missing Information Engine v1.

    Bu motor fiyat çalışmasına devam edilip edilmeyeceğini belirler.
    """

    missing_fields = []

    # Route checks
    if not shipment.pickup_city and not shipment.pickup_postcode:
        missing_fields.append("pickup location")

    if not shipment.delivery_city and not shipment.delivery_postcode:
        missing_fields.append("delivery location")

    # Commodity check
    if not shipment.commodity:
        missing_fields.append("commodity")

    # Ready date check
    if not shipment.cargo_ready_date:
        missing_fields.append("cargo ready date")

    # ADR cargo requires an explicit ADR class
    if shipment.is_adr and not shipment.adr_class:
        missing_fields.append("adr class")

    cargo_weight = assess_cargo_weight(shipment)
    if cargo_weight.requires_clarification:
        missing_fields.append("package count and per-piece weights")

    # Machine cargo requires dimensions
    if shipment.commodity and "makine" in shipment.commodity.lower():
        has_dimensions = any(
            package.length_cm and package.width_cm and package.height_cm
            for package in shipment.packages
        )

        if not has_dimensions:
            missing_fields.append("machine dimensions")

    # Commodity profile driven missing info
    commodity_profile = get_commodity_operational_profile(shipment.commodity)

    profile_missing_fields = commodity_profile.get("missing_info_fields", [])
    if isinstance(profile_missing_fields, list):
        for field in profile_missing_fields:
            if not isinstance(field, str):
                continue

            if (
                field == "adr status"
                and shipment.is_adr
                and shipment.adr_class
            ):
                continue

            if field not in missing_fields:
                missing_fields.append(field)

    # If critical missing info exists, stop quote flow
    critical_fields = {
        "pickup location",
        "delivery location",
        "commodity",
        "cargo ready date",
        "machine dimensions",
        "adr class",
        "package count and per-piece weights",
    }

    profile_critical_fields = commodity_profile.get("critical_missing_info_fields", [])
    if isinstance(profile_critical_fields, list):
        critical_fields.update(
            field for field in profile_critical_fields if isinstance(field, str)
        )

    critical_missing = [field for field in missing_fields if field in critical_fields]

    if critical_missing:
        reason = commodity_profile.get("missing_info_reason") or "Kritik eksik bilgi bulundu. Fiyat çalışması durduruldu."

        return MissingInfoResult(
            can_continue_to_quote=False,
            missing_fields=missing_fields,
            reason=reason,
        )

    return MissingInfoResult(
        can_continue_to_quote=True,
        missing_fields=missing_fields,
        reason="Fiyat çalışmasına devam edilebilir.",
    )
