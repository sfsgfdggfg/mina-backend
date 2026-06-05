from src.core.models import Shipment, Package


def get_simulation_scenarios() -> list[Shipment]:
    """
    Scenario-Based Simulation v1.

    Her senaryo farklı operasyon kararlarını test eder:
    - equipment decision
    - risk assessment
    - pricing adjustment
    - quote draft
    """

    return [
        Shipment(
            customer_name="Demo Textile",
            pickup_country="Türkiye",
            pickup_city="Adana",
            pickup_area="Adana Organize Sanayi Bölgesi",
            delivery_country="Almanya",
            delivery_city="Hamburg",
            commodity="Tekstil",
            gross_weight_kg=20000,
            service_type="FTL",
            cargo_ready_date="2026-06-15",
            packages=[
                Package(
                    package_type="loose / textile",
                    quantity=1,
                    weight_kg=20000,
                )
            ],
            special_notes="Standart tekstil yükü.",
        ),
        Shipment(
            customer_name="Cold Food Export",
            pickup_country="Türkiye",
            pickup_city="Mersin",
            delivery_country="Almanya",
            delivery_city="Munich",
            commodity="Gıda ürünü",
            gross_weight_kg=18000,
            service_type="FTL",
            is_temperature_controlled=True,
            temperature_requirement="+4°C",
            cargo_ready_date="2026-06-18",
            packages=[
                Package(
                    package_type="pallet",
                    quantity=33,
                    weight_kg=18000,
                    stackable=False,
                )
            ],
            special_notes="+4 derece sıcaklık kontrollü taşıma.",
        ),
        Shipment(
            customer_name="Machine Exporter",
            pickup_country="Türkiye",
            pickup_city="Konya",
            delivery_country="Romanya",
            delivery_city="Bucharest",
            commodity="Makine",
            gross_weight_kg=7000,
            service_type="FTL",
            cargo_ready_date="2026-06-20",
            packages=[
                Package(
                    package_type="machine",
                    quantity=1,
                    length_cm=250,
                    width_cm=120,
                    height_cm=290,
                    weight_kg=7000,
                )
            ],
            special_notes="Yük yüksekliği 2.90 m.",
        ),
        Shipment(
            customer_name="Heavy Machine Ltd",
            pickup_country="Türkiye",
            pickup_city="İzmir",
            delivery_country="Fransa",
            delivery_city="Lyon",
            commodity="Makine",
            gross_weight_kg=12000,
            service_type="FTL",
            cargo_ready_date="2026-06-21",
            packages=[
                Package(
                    package_type="machine",
                    quantity=1,
                    length_cm=400,
                    width_cm=180,
                    height_cm=320,
                    weight_kg=12000,
                )
            ],
            special_notes="Yük yüksekliği 3.20 m, gabari dışı olabilir.",
        ),
        Shipment(
            customer_name="Chemical Research",
            pickup_country="Türkiye",
            pickup_city="Gebze",
            delivery_country="Avusturya",
            delivery_city="Vienna",
            commodity="ADR yük",
            gross_weight_kg=5000,
            service_type="FTL",
            is_adr=True,
            adr_class="7",
            cargo_ready_date="2026-06-22",
            packages=[
                Package(
                    package_type="crate",
                    quantity=4,
                    weight_kg=5000,
                )
            ],
            special_notes="ADR Class 7.",
        ),
        Shipment(
            customer_name="Unknown Customer",
            pickup_country="Türkiye",
            pickup_city="Bursa",
            delivery_country="Almanya",
            delivery_city="Stuttgart",
            commodity="Makine",
            gross_weight_kg=3000,
            service_type="FTL",
            cargo_ready_date="2026-06-23",
            packages=[
                Package(
                    package_type="machine",
                    quantity=1,
                    weight_kg=3000,
                )
            ],
            special_notes="Yeni müşteri, makine yükü, ölçü bilgisi eksik.",
        ),
    ]