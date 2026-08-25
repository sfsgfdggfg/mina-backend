from __future__ import annotations

from src.ai.email_parser import build_shipment_from_extraction
from src.ai.extraction_models import ShipmentExtraction


def _extraction(transport_mode: str | None = None) -> ShipmentExtraction:
    return ShipmentExtraction(
        customer_name="Explicit Road Regression Customer",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        commodity="Tekstil",
        gross_weight_kg=12000,
        transport_mode=transport_mode,
        is_adr=None,
        is_temperature_controlled=None,
        is_high_value=None,
    )


def evaluate_explicit_road_inference_regressions() -> dict:
    failures: list[str] = []

    tenteli = build_shipment_from_extraction(
        _extraction(),
        "Tenteli komple araç fiyatı rica ederiz.",
    )
    if tenteli.transport_mode != "road":
        failures.append("tenteli/komple araç wording did not infer road mode")

    curtainsider = build_shipment_from_extraction(
        _extraction(),
        "Please quote a curtainsider.",
    )
    if curtainsider.transport_mode != "road":
        failures.append("curtainsider wording did not infer road mode")

    city_pair_only = build_shipment_from_extraction(
        _extraction(),
        "Adana'dan Hamburg'a 12000 kg tekstil taşıması.",
    )
    if city_pair_only.transport_mode is not None:
        failures.append("city pair alone inferred a transport mode")

    explicit_sea = build_shipment_from_extraction(
        _extraction("sea"),
        "Sea freight request; unrelated note mentions curtainsider.",
    )
    if explicit_sea.transport_mode != "sea":
        failures.append("explicit non-road mode was overwritten")

    if any(
        value is not None
        for proposal in (tenteli, curtainsider, city_pair_only, explicit_sea)
        for value in (
            proposal.is_adr,
            proposal.is_temperature_controlled,
            proposal.is_high_value,
        )
    ):
        failures.append("unknown exception fields did not remain None")

    return {
        "name": "Explicit road-mode inference",
        "passed": not failures,
        "failures": failures,
    }


def main() -> int:
    result = evaluate_explicit_road_inference_regressions()
    print(result)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
