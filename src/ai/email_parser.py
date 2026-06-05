from src.core.models import Shipment, Package


def parse_email_to_shipment(email_text: str) -> Shipment:
    """
    MVP v0 parser.

    Bu dosya şimdilik deterministic/mock çalışır.
    Bir sonraki versiyonda OpenAI structured extraction eklenecek.
    """

    shipment = Shipment(
        customer_name="Demo Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        pickup_area="Adana Organize Sanayi Bölgesi",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=20000,
        weight_is_approximate=True,
        service_type="FTL",
        cargo_ready_date="2026-06-15",
        required_delivery_date=None,
        packages=[
            Package(
                package_type="loose / textile",
                quantity=1,
                weight_kg=20000,
                stackable=None,
            )
        ],
        special_notes="Müşteri komple araç fiyat istemiştir.",
    )

    return shipment