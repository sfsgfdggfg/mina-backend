from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.core.air_rate_structure_review import AirRateStructureCandidate, AirRateStructureReview
from src.core.air_rate_structure_review_repository import InMemoryAirRateStructureReviewRepository
from src.core.air_rate_table_review import AirRateTableReview, AirRateTableRowCandidate
from src.core.air_rate_table_review_repository import InMemoryAirRateTableReviewRepository
from src.core.air_shadow_calculation import (
    AirShadowCalculationError,
    AirShadowPackage,
    build_air_shadow_calculation_preview,
)
from src.core.pilot_access import route_allowed


NOW = datetime(2026, 9, 13, 7, 0, tzinfo=timezone.utc)


def _structure(*, extra_divisor: bool = False) -> AirRateStructureReview:
    candidates = [
        AirRateStructureCandidate(
            candidate_id="confirmed-divisor-6000",
            kind="volumetric_divisor",
            value="6000",
            occurrence_count=1,
            source_line_numbers=[1],
            status="confirmed",
            reviewed_by="Air Operator",
            reviewed_at=NOW,
            review_note="Commercial-air volumetric divisor verified in tariff source.",
        )
    ]
    if extra_divisor:
        candidates.append(AirRateStructureCandidate(
            candidate_id="confirmed-divisor-5000",
            kind="volumetric_divisor",
            value="5000",
            occurrence_count=1,
            source_line_numbers=[2],
            status="confirmed",
            reviewed_by="Air Operator",
            reviewed_at=NOW,
            review_note="Second divisor is also visible; scope is ambiguous.",
        ))
    return AirRateStructureReview(
        review_id="structure-review-1",
        source_id="source-1",
        source_sha256="a" * 64,
        extracted_text_sha256="b" * 64,
        extracted_character_count=100,
        candidates=candidates,
        status="completed",
        requested_by="Air Operator",
        created_at=NOW,
    )


def _table(*, row_status: str = "confirmed") -> AirRateTableReview:
    review_kwargs = {}
    if row_status != "proposed":
        review_kwargs = {
            "reviewed_by": "Air Operator",
            "reviewed_at": NOW,
            "review_note": "Numeric row verified against source PDF.",
        }
    row = AirRateTableRowCandidate(
        candidate_id="confirmed-row-fra",
        destination_label="FRA",
        destination_code="FRA",
        currency="USD",
        rates={
            "MIN": Decimal("120"),
            "+45": Decimal("2.50"),
            "+100": Decimal("2.30"),
            "+300": Decimal("2.00"),
            "+500": Decimal("1.80"),
        },
        source_line_number=2,
        source_line_sha256="c" * 64,
        status=row_status,
        **review_kwargs,
    )
    return AirRateTableReview(
        review_id="table-review-1",
        source_id="source-1",
        source_sha256="a" * 64,
        structure_review_id="structure-review-1",
        extracted_text_sha256="b" * 64,
        weight_breaks=["MIN", "+45", "+100", "+300", "+500"],
        candidates=[row],
        status="pending" if row_status == "proposed" else "completed",
        requested_by="Air Operator",
        created_at=NOW,
    )


def evaluate_air_shadow_calculation_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    structures = InMemoryAirRateStructureReviewRepository()
    tables = InMemoryAirRateTableReviewRepository()
    structures.create(_structure())
    tables.create(_table())
    packages = [AirShadowPackage(quantity=1, length_cm=100, width_cm=80, height_cm=60)]
    preview = build_air_shadow_calculation_preview(
        review_id="table-review-1",
        candidate_id="confirmed-row-fra",
        actual_weight_kg=Decimal("287"),
        packages=packages,
        table_repository=tables,
        structure_repository=structures,
    )
    check(
        preview.volumetric_weight_kg == Decimal("80.000")
        and preview.chargeable_weight_kg_unrounded == Decimal("287.000")
        and preview.standard_option.rate_break == "+100"
        and preview.standard_option.freight_amount == Decimal("660.10"),
        "shadow worksheet computes actual-versus-volumetric chargeable weight without hidden rounding",
    )
    check(
        preview.lowest_math_option.rate_break == "+300"
        and preview.lowest_math_option.billed_weight_kg == Decimal("300.000")
        and preview.lowest_math_option.freight_amount == Decimal("600.00")
        and preview.lowest_math_option.pivoted_up,
        "shadow worksheet detects cheaper higher-weight pivot option",
    )
    check(
        preview.runtime_authoritative is False
        and preview.quote_authority is False
        and preview.weight_rounding_applied is False
        and preview.surcharges_included is False
        and preview.pickup_included is False
        and preview.door_delivery_included is False
        and preview.capacity_confirmed is False
        and preview.schedule_confirmed is False,
        "shadow worksheet keeps base-freight math separate from quote and operational authority",
    )

    volume_preview = build_air_shadow_calculation_preview(
        review_id="table-review-1",
        candidate_id="confirmed-row-fra",
        actual_weight_kg=Decimal("50"),
        packages=[AirShadowPackage(quantity=1, length_cm=120, width_cm=100, height_cm=100)],
        table_repository=tables,
        structure_repository=structures,
    )
    check(
        volume_preview.volumetric_weight_kg == Decimal("200.000")
        and volume_preview.chargeable_weight_kg_unrounded == Decimal("200.000"),
        "shadow worksheet uses confirmed divisor and chooses volumetric weight when higher",
    )

    unconfirmed_tables = InMemoryAirRateTableReviewRepository()
    unconfirmed_tables.create(_table(row_status="proposed"))
    blocked = False
    try:
        build_air_shadow_calculation_preview(
            review_id="table-review-1", candidate_id="confirmed-row-fra",
            actual_weight_kg=Decimal("287"), packages=packages,
            table_repository=unconfirmed_tables, structure_repository=structures,
        )
    except AirShadowCalculationError as exc:
        blocked = str(exc) == "air_shadow_rate_row_must_be_confirmed"
    check(blocked, "unreviewed numeric tariff row cannot enter shadow freight calculation")

    ambiguous_structures = InMemoryAirRateStructureReviewRepository()
    ambiguous_structures.create(_structure(extra_divisor=True))
    divisor_blocked = False
    try:
        build_air_shadow_calculation_preview(
            review_id="table-review-1", candidate_id="confirmed-row-fra",
            actual_weight_kg=Decimal("287"), packages=packages,
            table_repository=tables, structure_repository=ambiguous_structures,
        )
    except AirShadowCalculationError as exc:
        divisor_blocked = str(exc) == "air_shadow_requires_one_confirmed_volumetric_divisor"
    check(divisor_blocked, "ambiguous confirmed volumetric divisors fail closed instead of choosing one")

    from src import api
    originals = (api.air_rate_table_review_repository, api.air_rate_structure_review_repository)
    try:
        api.air_rate_table_review_repository = tables
        api.air_rate_structure_review_repository = structures
        result = api.preview_air_shadow_calculation(
            "table-review-1", "confirmed-row-fra",
            api.AirShadowCalculationPreviewRequest(
                actual_weight_kg=Decimal("287"), packages=packages
            ),
        )
    finally:
        api.air_rate_table_review_repository, api.air_rate_structure_review_repository = originals
    check(
        result["shadow_only"] is True
        and result["persisted"] is False
        and result["customer_quote_enabled"] is False
        and result["outbound_enabled"] is False
        and result["preview"]["lowest_math_option"]["rate_break"] == "+300",
        "controlled API exposes ephemeral pivot preview without persistence or outbound authority",
    )
    check(
        route_allowed("POST", "/air-rate-table-reviews/review-1/rows/row-1/shadow-preview"),
        "pilot access admits bounded air shadow calculation preview route",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_shadow_calculation.py").read_text(encoding="utf-8")
    check(
        "Shadow Hesap" in js
        and "Pivot" in js
        and "Surcharge dahil değil" in js
        and "customer_quote" not in service
        and "openai" not in service.casefold(),
        "browser exposes bounded shadow calculator while core calculator has no quote or OpenAI dependency",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_shadow_calculation_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir shadow calculation regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
