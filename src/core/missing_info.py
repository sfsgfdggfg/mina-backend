from pydantic import BaseModel, Field
from typing import List
from src.core.models import Shipment
from src.core.extraction_confirmation import require_operational_shipment
from src.core.commodity_profile import get_commodity_operational_profile
from src.core.cargo_weight import assess_cargo_weight
from src.core.clarification_requirements import (
    get_commodity_clarification_requirements,
    is_clarification_requirement_answered,
)


class MissingInfoResult(BaseModel):
    can_continue_to_quote: bool = True
    missing_fields: List[str] = Field(default_factory=list)
    reason: str = ""


def check_missing_information(shipment: Shipment) -> MissingInfoResult:
    """
    Missing Information Engine v1.

    Bu motor fiyat çalışmasına devam edilip edilmeyeceğini belirler.
    """

    require_operational_shipment(shipment)
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
    clarification_requirements = (
        get_commodity_clarification_requirements(shipment.commodity)
    )

    for requirement in clarification_requirements:
        if not is_clarification_requirement_answered(
            shipment,
            requirement,
        ):
            missing_fields.append(requirement.key)

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

    critical_fields.update(
        requirement.key
        for requirement in clarification_requirements
        if requirement.critical
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
