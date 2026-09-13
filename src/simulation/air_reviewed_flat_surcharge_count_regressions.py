from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.core.air_reviewed_surcharge_cost_preview import (
    AirReviewedSurchargeCostPreviewError,
    build_air_reviewed_surcharge_cost_preview,
)
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import (
    _candidate,
    _source_repo,
    _surcharge_repo,
)
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo


def evaluate_air_reviewed_flat_surcharge_count_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    tables = _table_repo()
    structures = _structure_repo()
    sources = _source_repo()
    flat = _candidate(
        "flat-count-00001", "HANDLING", "25",
        basis="flat", application_basis="flat", flat_quantity_basis="per_awb",
    )
    per_kg = _candidate(
        "fsc-count-000001", "FSC", "0.50", application_basis="chargeable_weight",
    )
    surcharges = _surcharge_repo(per_kg, flat)

    missing_blocked = False
    try:
        build_air_reviewed_surcharge_cost_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=287, volumetric_weight_kg=250,
            cargo_context="general_cargo", routing_context="direct",
            table_repository=tables, structure_repository=structures,
            surcharge_repository=surcharges, source_repository=sources,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_blocked = str(exc) == "flat_surcharge_count_required:per_awb"
    check(missing_blocked, "applicable reviewed flat surcharge requires explicit matching count and never assumes one")

    wrong_count_blocked = False
    try:
        build_air_reviewed_surcharge_cost_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=287, volumetric_weight_kg=250,
            cargo_context="general_cargo", routing_context="direct", shipment_count=1,
            table_repository=tables, structure_repository=structures,
            surcharge_repository=surcharges, source_repository=sources,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        wrong_count_blocked = str(exc) == "flat_surcharge_count_required:per_awb"
    check(wrong_count_blocked, "shipment count cannot substitute for reviewed AWB count semantics")

    preview = build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001", candidate_id="table-row-fra-0001",
        actual_weight_kg=287, volumetric_weight_kg=250,
        cargo_context="general_cargo", routing_context="direct", awb_count=2,
        table_repository=tables, structure_repository=structures,
        surcharge_repository=surcharges, source_repository=sources,
    )
    flat_component = preview.included_flat_surcharges[0]
    check(
        flat_component.quantity_basis == "per_awb"
        and flat_component.applied_count == 2
        and flat_component.amount_per_unit == Decimal("25")
        and flat_component.surcharge_cost == Decimal("50")
        and preview.reviewed_flat_surcharge_total == Decimal("50")
        and preview.reviewed_per_kg_surcharge_total == Decimal("143.50")
        and preview.base_plus_reviewed_surcharges == Decimal("793.50")
        and preview.flat_surcharges_included is True,
        "explicit AWB count multiplies only the matching reviewed flat surcharge and joins the partial cost total",
    )
    check(
        preview.all_in_cost is False
        and preview.fx_applied is False
        and preview.tariff_validity_confirmed is False
        and preview.capacity_confirmed is False
        and preview.customer_quote_eligible is False
        and preview.runtime_authoritative is False,
        "flat surcharge consumption remains partial reference cost without all-in or quote authority",
    )

    mismatched = _candidate(
        "flat-muc-000001", "HANDLING", "25",
        basis="flat", application_basis="flat", flat_quantity_basis="per_awb",
        applicability_scope="destination_specific", destination_code="MUC",
    )
    mismatch_preview = build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001", candidate_id="table-row-fra-0001",
        actual_weight_kg=287, volumetric_weight_kg=250,
        cargo_context="general_cargo", routing_context="direct",
        table_repository=tables, structure_repository=structures,
        surcharge_repository=_surcharge_repo(mismatched), source_repository=sources,
    )
    check(
        not mismatch_preview.included_flat_surcharges
        and any(x.reason == "destination_not_applicable" for x in mismatch_preview.excluded_surcharges),
        "context-inapplicable flat surcharge is excluded without demanding an irrelevant count",
    )

    cross_currency = _candidate(
        "flat-eur-000001", "HANDLING", "25", currency="EUR",
        basis="flat", application_basis="flat", flat_quantity_basis="per_awb",
    )
    fx_preview = build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001", candidate_id="table-row-fra-0001",
        actual_weight_kg=287, volumetric_weight_kg=250,
        cargo_context="general_cargo", routing_context="direct",
        table_repository=tables, structure_repository=structures,
        surcharge_repository=_surcharge_repo(cross_currency), source_repository=sources,
    )
    check(
        not fx_preview.included_flat_surcharges
        and any(x.reason == "currency_mismatch_no_fx" for x in fx_preview.excluded_surcharges),
        "cross-currency flat surcharge stays excluded without count demand or FX inference",
    )

    invalid_count_blocked = False
    try:
        build_air_reviewed_surcharge_cost_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=287, volumetric_weight_kg=250,
            cargo_context="general_cargo", routing_context="direct", awb_count=0,
            table_repository=tables, structure_repository=structures,
            surcharge_repository=surcharges, source_repository=sources,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        invalid_count_blocked = str(exc) == "invalid_flat_surcharge_count:per_awb"
    check(invalid_count_blocked, "flat surcharge counts are bounded positive integers in the service contract")

    from src import api
    originals = (
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_shadow_repository,
    )
    try:
        api.air_rate_table_review_repository = tables
        api.air_rate_structure_review_repository = structures
        api.air_rate_surcharge_review_repository = surcharges
        api.air_shadow_repository = sources
        response = api.preview_air_reviewed_surcharge_cost(
            "table-review-0001", "table-row-fra-0001",
            api.AirReviewedSurchargeCostPreviewRequest(
                actual_weight_kg=287, volumetric_weight_kg=250,
                cargo_context="general_cargo", routing_context="direct", awb_count=2,
            ),
        )
    finally:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
        ) = originals
    check(
        Decimal(response["reviewed_flat_surcharge_total"]) == Decimal("50")
        and Decimal(response["base_plus_reviewed_surcharges"]) == Decimal("793.50")
        and response["included_flat_surcharges"][0]["applied_count"] == 2
        and response["all_in_cost"] is False
        and response["customer_quote_eligible"] is False,
        "controlled API accepts explicit flat counts while preserving non-all-in non-quote boundaries",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_reviewed_surcharge_cost_preview.py").read_text(encoding="utf-8")
    check(
        "Shipment count (flat için)" in js
        and "AWB count (flat için)" in js
        and "HAWB count (flat için)" in js
        and "MAWB count (flat için)" in js
        and "Count alanları boş bırakılırsa hiçbir count varsayılmaz" in js,
        "browser exposes blank explicit count inputs and states that no count is assumed",
    )
    check(
        "save(" not in service and ".create(" not in service and "upsert" not in service
        and "openai" not in service.casefold(),
        "flat count consumption remains ephemeral local calculation with no persistence or AI path",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_reviewed_flat_surcharge_count_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir reviewed flat surcharge count regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
