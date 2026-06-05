from pydantic import BaseModel, Field
from typing import List
from src.core.models import Shipment


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

    # Machine cargo requires dimensions
    if shipment.commodity and "makine" in shipment.commodity.lower():
        has_dimensions = any(
            package.length_cm and package.width_cm and package.height_cm
            for package in shipment.packages
        )

        if not has_dimensions:
            missing_fields.append("machine dimensions")

    # If critical missing info exists, stop quote flow
    critical_fields = {
        "pickup location",
        "delivery location",
        "commodity",
        "cargo ready date",
        "machine dimensions",
    }

    critical_missing = [field for field in missing_fields if field in critical_fields]

    if critical_missing:
        return MissingInfoResult(
            can_continue_to_quote=False,
            missing_fields=missing_fields,
            reason="Kritik eksik bilgi bulundu. Fiyat çalışması durduruldu.",
        )

    return MissingInfoResult(
        can_continue_to_quote=True,
        missing_fields=missing_fields,
        reason="Fiyat çalışmasına devam edilebilir.",
    )