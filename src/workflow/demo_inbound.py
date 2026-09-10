from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.core.extraction_confirmation import ShipmentProposalSnapshot
from src.core.models import Package
from src.core.privacy import PrivacySafeText


def _deadline(hours: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=hours)


def parse_demo_customer_email(safe_text: PrivacySafeText) -> ShipmentProposalSnapshot:
    """Deterministic parser for the isolated synthetic demo mailbox only."""
    text = str(safe_text).casefold()
    if "demo:reefer" in text:
        return ShipmentProposalSnapshot(
            customer_name="Nova Gıda", pickup_country="Türkiye", pickup_city="Mersin",
            delivery_country="Germany", delivery_city="Münih", delivery_postcode="80331", commodity="Gıda",
            gross_weight_kg=18000, weight_is_approximate=False, service_type="FTL",
            transport_mode="road", equipment_type="Reefer", cargo_ready_date="2026-09-11",
            required_delivery_date="2026-09-15", customer_quote_deadline_at=_deadline(2),
            is_adr=False, is_temperature_controlled=True,
            temperature_requirement="+4°C", is_high_value=False,
            packages=[Package(quantity=18, length_cm=120, width_cm=80, height_cm=120, weight_kg=1000)],
        )
    if "demo:machine" in text:
        return ShipmentProposalSnapshot(
            customer_name="Mavi Makina", pickup_country="Türkiye", pickup_city="Bursa",
            delivery_country="Germany", delivery_city="Stuttgart", delivery_postcode="70173", commodity="Makina",
            gross_weight_kg=3000, weight_is_approximate=True, service_type="FTL",
            transport_mode="road", equipment_type="Tenteli", cargo_ready_date="2026-09-12",
            is_adr=False, is_temperature_controlled=False, is_high_value=False,
            special_notes="Makina ölçüleri e-postada belirtilmedi; clarification beklenir.",
            packages=[Package(package_type="kasa", quantity=1, weight_kg=3000)],
        )

    return ShipmentProposalSnapshot(
        customer_name="Atlas Tekstil", pickup_country="Türkiye", pickup_city="Adana",
        delivery_country="Germany", delivery_city="Hamburg", delivery_postcode="20095", commodity="Tekstil",
        gross_weight_kg=20000, weight_is_approximate=False, service_type="FTL",
        transport_mode="road", equipment_type="Tenteli", cargo_ready_date="2026-09-11",
        required_delivery_date="2026-09-16", customer_quote_deadline_at=_deadline(4),
        is_adr=False, is_temperature_controlled=False, is_high_value=False,
        packages=[Package(quantity=20, length_cm=120, width_cm=80, height_cm=100, weight_kg=1000, stackable=True)],
    )
