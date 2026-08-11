from __future__ import annotations

from src.ai.extraction_models import ShipmentExtraction
from src.core.models import Package, Shipment


def shipment_from_extraction(
    extracted: ShipmentExtraction,
) -> Shipment:
    """Map validated AI extraction data into the domain model."""

    packages = [
        Package(
            package_type=package.package_type,
            quantity=package.quantity,
            length_cm=package.length_cm,
            width_cm=package.width_cm,
            height_cm=package.height_cm,
            weight_kg=package.weight_kg,
            stackable=package.stackable,
        )
        for package in extracted.packages
    ]

    return Shipment(
        customer_name=extracted.customer_name,
        pickup_country=extracted.pickup_country,
        pickup_city=extracted.pickup_city,
        pickup_area=extracted.pickup_area,
        pickup_postcode=extracted.pickup_postcode,
        delivery_country=extracted.delivery_country,
        delivery_city=extracted.delivery_city,
        delivery_area=extracted.delivery_area,
        delivery_postcode=extracted.delivery_postcode,
        commodity=extracted.commodity,
        gross_weight_kg=extracted.gross_weight_kg,
        weight_is_approximate=extracted.weight_is_approximate,
        service_type=extracted.service_type,
        equipment_type=extracted.equipment_type,
        cargo_ready_date=extracted.cargo_ready_date,
        required_delivery_date=extracted.required_delivery_date,
        is_adr=extracted.is_adr,
        adr_class=extracted.adr_class,
        is_temperature_controlled=(
            extracted.is_temperature_controlled
        ),
        temperature_requirement=extracted.temperature_requirement,
        is_high_value=extracted.is_high_value,
        special_notes=extracted.special_notes,
        commodity_attributes=extracted.commodity_attributes,
        packages=packages,
    )
