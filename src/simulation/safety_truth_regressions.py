from __future__ import annotations

from src.ai.email_parser import build_shipment_from_extraction
from src.ai.extraction_models import ShipmentExtraction


def _extraction(**updates) -> ShipmentExtraction:
    data = {
        "customer_name": "Synthetic Safety Truth Customer",
        "pickup_country": "Türkiye",
        "pickup_city": "Adana",
        "delivery_country": "Almanya",
        "delivery_city": "Hamburg",
        "commodity": "Tekstil",
        "gross_weight_kg": 12000,
        "service_type": "FTL",
        "transport_mode": "road",
        "is_adr": None,
        "is_temperature_controlled": None,
        "is_high_value": None,
    }
    data.update(updates)
    return ShipmentExtraction.model_validate(data)


def evaluate_safety_truth_regressions() -> dict:
    failures: list[str] = []

    neutral_text = "Adana'dan Hamburg'a 12000 kg tekstil FTL talebi."

    ai_negative = build_shipment_from_extraction(
        _extraction(
            is_adr=False,
            is_temperature_controlled=False,
            is_high_value=False,
        ),
        neutral_text,
    )
    if ai_negative.is_adr is not None:
        failures.append("AI-only ADR false became authoritative")
    if ai_negative.is_temperature_controlled is not None:
        failures.append("AI-only temperature false became authoritative")
    if ai_negative.is_high_value is not None:
        failures.append("AI-only high-value false became authoritative")

    explicit_non_adr = build_shipment_from_extraction(
        _extraction(is_adr=False),
        neutral_text + " Yük ADR değil.",
    )
    if explicit_non_adr.is_adr is not False:
        failures.append("explicit non-ADR source evidence was not preserved")

    explicit_labeled_non_adr = build_shipment_from_extraction(
        _extraction(is_adr=True),
        neutral_text + " Cargo: non-dangerous textile goods. ADR: no.",
    )
    if explicit_labeled_non_adr.is_adr is not False:
        failures.append("explicit ADR: no source evidence was not preserved")

    explicit_temperature_negative = build_shipment_from_extraction(
        _extraction(is_temperature_controlled=True),
        neutral_text + " Temperature control: not required.",
    )
    if explicit_temperature_negative.is_temperature_controlled is not False:
        failures.append("explicit temperature-control negative was not preserved")

    unsupported_stackable = build_shipment_from_extraction(
        _extraction(
            packages=[
                {
                    "package_type": "pallet",
                    "quantity": 33,
                    "length_cm": 120,
                    "width_cm": 80,
                    "height_cm": 150,
                    "stackable": True,
                }
            ]
        ),
        neutral_text + " 33 pallets 120 x 80 x 150 cm.",
    )
    if unsupported_stackable.packages[0].stackable is not None:
        failures.append("AI-only stackability became authoritative")

    unsupported_package_weight = build_shipment_from_extraction(
        _extraction(
            gross_weight_kg=20000,
            packages=[
                {
                    "package_type": "pallet",
                    "quantity": 33,
                    "length_cm": 120,
                    "width_cm": 80,
                    "height_cm": 150,
                    "weight_kg": 20000,
                }
            ],
        ),
        (
            "Adana'dan Hamburg'a 33 palet tekstil. "
            "Paletler 120 x 80 x 150 cm. Total gross weight: 20,000 kg."
        ),
    )
    if unsupported_package_weight.packages[0].weight_kg is not None:
        failures.append("AI-only package-line weight became authoritative")

    explicit_per_piece_weight = build_shipment_from_extraction(
        _extraction(
            gross_weight_kg=19800,
            packages=[
                {
                    "package_type": "pallet",
                    "quantity": 33,
                    "length_cm": 120,
                    "width_cm": 80,
                    "height_cm": 150,
                    "weight_kg": 600,
                }
            ],
        ),
        (
            "Adana'dan Hamburg'a 33 palet tekstil. "
            "Each pallet is 600 kg. Total gross weight: 19,800 kg."
        ),
    )
    if explicit_per_piece_weight.packages[0].weight_kg != 600:
        failures.append("explicit per-piece package weight was not preserved")

    conflicting_adr = build_shipment_from_extraction(
        _extraction(is_adr=False),
        neutral_text + " Yük ADR değil. ADR Class 3.",
    )
    if conflicting_adr.is_adr is not None:
        failures.append("conflicting ADR source signals did not remain unresolved")

    conservative_positive = build_shipment_from_extraction(
        _extraction(
            is_adr=True,
            is_temperature_controlled=True,
            is_high_value=True,
        ),
        neutral_text,
    )
    if conservative_positive.is_adr is not True:
        failures.append("conservative AI ADR positive was lost")
    if conservative_positive.is_temperature_controlled is not True:
        failures.append("conservative AI temperature positive was lost")
    if conservative_positive.is_high_value is not True:
        failures.append("conservative AI high-value positive was lost")

    return {
        "name": "Safety truth authority",
        "passed": not failures,
        "failures": failures,
    }


def main() -> int:
    result = evaluate_safety_truth_regressions()
    print(result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
