from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from starlette.requests import Request

from src.core.air_freight_calculation_preview import (
    AirFreightCalculationPreviewError,
    build_air_freight_calculation_preview,
)
from src.core.air_rate_structure_review import AirRateStructureCandidate, AirRateStructureReview
from src.core.air_rate_structure_review_repository import InMemoryAirRateStructureReviewRepository
from src.core.air_rate_table_review import AirRateTableReview, AirRateTableRowCandidate
from src.core.air_rate_table_review_repository import InMemoryAirRateTableReviewRepository
from src.core.pilot_access import route_allowed


NOW = datetime(2026, 9, 13, 6, 40, tzinfo=timezone.utc)


def _structure_repo(*, divisor: str = "6000", divisor_status: str = "confirmed"):
    repo = InMemoryAirRateStructureReviewRepository()
    candidates = [
        AirRateStructureCandidate(
            candidate_id="break-min-0001", kind="weight_break", value="MIN", occurrence_count=1,
            source_line_numbers=[1], status="confirmed", reviewed_by="Air Operator",
            reviewed_at=NOW, review_note="Verified header.",
        ),
        AirRateStructureCandidate(
            candidate_id="break-100-0001", kind="weight_break", value="+100", occurrence_count=1,
            source_line_numbers=[1], status="confirmed", reviewed_by="Air Operator",
            reviewed_at=NOW, review_note="Verified header.",
        ),
        AirRateStructureCandidate(
            candidate_id="break-300-0001", kind="weight_break", value="+300", occurrence_count=1,
            source_line_numbers=[1], status="confirmed", reviewed_by="Air Operator",
            reviewed_at=NOW, review_note="Verified header.",
        ),
        AirRateStructureCandidate(
            candidate_id="break-500-0001", kind="weight_break", value="+500", occurrence_count=1,
            source_line_numbers=[1], status="confirmed", reviewed_by="Air Operator",
            reviewed_at=NOW, review_note="Verified header.",
        ),
        AirRateStructureCandidate(
            candidate_id="currency-usd-01", kind="currency", value="USD", occurrence_count=1,
            source_line_numbers=[1], status="confirmed", reviewed_by="Air Operator",
            reviewed_at=NOW, review_note="Verified currency.",
        ),
        AirRateStructureCandidate(
            candidate_id="divisor-6000-01", kind="volumetric_divisor", value=divisor, occurrence_count=1,
            source_line_numbers=[7], status=divisor_status,
            reviewed_by="Air Operator" if divisor_status != "proposed" else None,
            reviewed_at=NOW if divisor_status != "proposed" else None,
            review_note="Verified divisor." if divisor_status != "proposed" else None,
        ),
    ]
    status = "completed" if divisor_status != "proposed" else "partially_reviewed"
    review = AirRateStructureReview(
        review_id="structure-review-0001", source_id="source-0001", source_sha256="a" * 64,
        extracted_text_sha256="b" * 64, extracted_character_count=500,
        candidates=candidates, status=status, requested_by="Air Operator", created_at=NOW,
    )
    repo.create(review)
    return repo


def _table_repo(*, row_status: str = "confirmed"):
    repo = InMemoryAirRateTableReviewRepository()
    row = AirRateTableRowCandidate(
        candidate_id="table-row-fra-0001", destination_label="FRA", destination_code="FRA",
        currency="USD",
        rates={
            "MIN": Decimal("120"), "+100": Decimal("2.50"),
            "+300": Decimal("2.00"), "+500": Decimal("1.80"),
        },
        source_line_number=2, source_line_sha256="c" * 64,
        status=row_status,
        reviewed_by="Air Operator" if row_status != "proposed" else None,
        reviewed_at=NOW if row_status != "proposed" else None,
        review_note="Verified all row values." if row_status != "proposed" else None,
    )
    review = AirRateTableReview(
        review_id="table-review-0001", source_id="source-0001", source_sha256="a" * 64,
        structure_review_id="structure-review-0001", extracted_text_sha256="b" * 64,
        weight_breaks=["MIN", "+100", "+300", "+500"], candidates=[row],
        status="completed" if row_status != "proposed" else "pending",
        requested_by="Air Operator", created_at=NOW,
    )
    repo.create(review)
    return repo


def evaluate_air_freight_calculation_preview_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    tables = _table_repo()
    structures = _structure_repo()
    preview = build_air_freight_calculation_preview(
        review_id="table-review-0001", candidate_id="table-row-fra-0001",
        actual_weight_kg=287, volumetric_weight_kg=250,
        table_repository=tables, structure_repository=structures,
    )
    check(
        preview.chargeable_weight_kg == Decimal("287")
        and preview.recommended_break == "+300"
        and preview.recommended_billed_weight_kg == Decimal("300")
        and preview.recommended_base_freight == Decimal("600.00")
        and preview.pivot_applied is True,
        "287 kg preview compares higher break and selects cheaper +300 pivot",
    )
    option_100 = next(item for item in preview.options if item.weight_break == "+100")
    check(
        option_100.billed_weight_kg == Decimal("287")
        and option_100.base_freight == Decimal("717.50"),
        "lower eligible break bills actual chargeable weight instead of threshold",
    )
    check(
        preview.runtime_authoritative is False
        and preview.customer_quote_eligible is False
        and preview.surcharges_included is False
        and preview.capacity_confirmed is False
        and preview.rounding_applied is False,
        "calculation preview is freight-only non-authoritative evidence with no rounding or capacity claim",
    )

    low_weight = build_air_freight_calculation_preview(
        review_id="table-review-0001", candidate_id="table-row-fra-0001",
        actual_weight_kg=10, volumetric_weight_kg=8,
        table_repository=tables, structure_repository=structures,
    )
    check(
        low_weight.minimum_charge == Decimal("120")
        and all(item.base_freight >= Decimal("120") for item in low_weight.options),
        "MIN charge floors every per-kg break option without absorbing surcharges",
    )

    volume_preview = build_air_freight_calculation_preview(
        review_id="table-review-0001", candidate_id="table-row-fra-0001",
        actual_weight_kg=100, total_volume_cm3=1_200_000,
        table_repository=tables, structure_repository=structures,
    )
    check(
        volume_preview.volumetric_divisor == Decimal("6000")
        and volume_preview.volumetric_weight_kg == Decimal("200")
        and volume_preview.chargeable_weight_kg == Decimal("200")
        and volume_preview.volumetric_source == "confirmed_divisor_from_total_volume",
        "total volume uses exactly one human-confirmed volumetric divisor",
    )

    unreviewed_blocked = False
    try:
        build_air_freight_calculation_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=287, volumetric_weight_kg=250,
            table_repository=_table_repo(row_status="proposed"), structure_repository=structures,
        )
    except AirFreightCalculationPreviewError as exc:
        unreviewed_blocked = str(exc) == "air_rate_table_row_must_be_confirmed"
    check(unreviewed_blocked, "unreviewed tariff row cannot enter freight calculation preview")

    divisor_blocked = False
    try:
        build_air_freight_calculation_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=100, total_volume_cm3=1_200_000,
            table_repository=tables, structure_repository=_structure_repo(divisor_status="proposed"),
        )
    except AirFreightCalculationPreviewError as exc:
        divisor_blocked = str(exc) == "air_rate_structure_review_must_be_completed"
    check(divisor_blocked, "volume-derived chargeable weight fails closed without completed divisor review")

    ambiguous_input_blocked = False
    try:
        build_air_freight_calculation_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=100, volumetric_weight_kg=90, total_volume_cm3=540_000,
            table_repository=tables, structure_repository=structures,
        )
    except AirFreightCalculationPreviewError as exc:
        ambiguous_input_blocked = str(exc) == "provide_exactly_one_volumetric_input"
    check(ambiguous_input_blocked, "preview refuses competing volumetric inputs instead of choosing silently")

    from src import api
    originals = (api.air_rate_table_review_repository, api.air_rate_structure_review_repository)
    try:
        api.air_rate_table_review_repository = tables
        api.air_rate_structure_review_repository = structures
        response = api.preview_air_freight_calculation(
            "table-review-0001", "table-row-fra-0001",
            api.AirFreightCalculationPreviewRequest(actual_weight_kg=287, volumetric_weight_kg=250),
        )
    finally:
        api.air_rate_table_review_repository, api.air_rate_structure_review_repository = originals
    check(
        response["recommended_break"] == "+300"
        and response["runtime_authoritative"] is False
        and response["customer_quote_eligible"] is False,
        "controlled API exposes pivot preview without customer quote authority",
    )
    check(
        route_allowed("POST", "/air-rate-table-reviews/review-1/rows/row-1/calculation-preview"),
        "pilot access admits bounded air-freight calculation preview route",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_freight_calculation_preview.py").read_text(encoding="utf-8")
    check(
        "Navlun Önizleme" in js
        and "Surcharge dahil değil" in js
        and "Müşteri teklifi değildir" in js
        and "openai" not in service.casefold(),
        "browser labels preview as non-quote freight comparison and service has no OpenAI dependency",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_freight_calculation_preview_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir freight calculation preview regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
