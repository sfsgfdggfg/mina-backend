from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_freight_calculation_preview import (
    AirFreightCalculationPreviewError,
    build_air_freight_calculation_preview,
)
from src.core.air_rate_surcharge_review_repository import InMemoryAirRateSurchargeReviewRepository
from src.core.air_rate_weight_rounding_review import AirRateWeightRoundingReview
from src.core.air_rate_weight_rounding_review_repository import (
    InMemoryAirRateWeightRoundingReviewRepository,
    SQLiteAirRateWeightRoundingReviewRepository,
)
from src.core.air_rate_weight_rounding_review_service import (
    AirRateWeightRoundingReviewTransitionError,
    review_air_rate_weight_rounding,
)
from src.core.air_reviewed_surcharge_cost_preview import build_air_reviewed_surcharge_cost_preview
from src.core.air_shadow import AirRateSource
from src.core.air_shadow_repository import InMemoryAirShadowRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import _standard_repo


NOW = datetime(2026, 9, 14, 8, 0, tzinfo=timezone.utc)


def _source_repo() -> InMemoryAirShadowRepository:
    repo = InMemoryAirShadowRepository()
    repo.create_rate_source(AirRateSource(
        source_id="source-0001",
        entry_id="weight-rounding-source",
        airline_name="THY",
        document_name="rounding.pdf",
        sha256_hex="a" * 64,
        cargo_scope="general_cargo",
        origin_airport="ADA",
        recorded_by="Air Operator",
        recorded_at=NOW,
    ))
    return repo


def _review(repo, source_repo, *, mode="ceiling", increment=Decimal("0.5")):
    return review_air_rate_weight_rounding(
        source_id="source-0001",
        rounding_mode=mode,
        increment_kg=increment,
        review_note="Exact tariff evidence confirms the chargeable-weight rounding rule.",
        reviewed_by="Senior Air Operator",
        reviewed_at=NOW,
        source_repository=source_repo,
        repository=repo,
    )


def _matching_surcharge_repo():
    source = _standard_repo().find_by_source("source-0001")
    assert source is not None
    repo = InMemoryAirRateSurchargeReviewRepository()
    repo.create(source.model_copy(update={"source_sha256": "a" * 64}, deep=True))
    return repo


def evaluate_air_rate_weight_rounding_review_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    sources = _source_repo()
    repo = InMemoryAirRateWeightRoundingReviewRepository()
    review = _review(repo, sources)
    check(
        review.source_sha256 == "a" * 64
        and review.rounding_mode == "ceiling"
        and review.increment_kg == Decimal("0.5")
        and review.applies_to == "chargeable_weight_before_break_evaluation"
        and review.runtime_authoritative is False
        and review.customer_pricing_authority is False,
        "source-bound ceiling rounding review stores exact provenance without pricing authority",
    )

    repeat_blocked = False
    try:
        _review(repo, sources, increment=Decimal("1"))
    except AirRateWeightRoundingReviewTransitionError:
        repeat_blocked = True
    check(repeat_blocked, "weight-rounding review is one-time for the immutable tariff source")

    invalid_none = False
    try:
        _review(
            InMemoryAirRateWeightRoundingReviewRepository(),
            sources,
            mode="none",
            increment=Decimal("0.5"),
        )
    except AirRateWeightRoundingReviewTransitionError:
        invalid_none = True
    check(invalid_none, "explicit no-rounding evidence cannot carry a hidden increment")

    missing_increment = False
    try:
        _review(
            InMemoryAirRateWeightRoundingReviewRepository(),
            sources,
            mode="ceiling",
            increment=None,
        )
    except AirRateWeightRoundingReviewTransitionError:
        missing_increment = True
    check(missing_increment, "ceiling rounding cannot be reviewed without an explicit increment")

    tables = _table_repo()
    structures = _structure_repo()
    rounded = build_air_freight_calculation_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=305.2,
        volumetric_weight_kg=250,
        table_repository=tables,
        structure_repository=structures,
        rounding_repository=repo,
    )
    option_300 = next(item for item in rounded.options if item.weight_break == "+300")
    check(
        rounded.chargeable_weight_kg == Decimal("305.2")
        and rounded.rounded_chargeable_weight_kg == Decimal("305.5")
        and rounded.rounding_review_id == review.review_id
        and rounded.rounding_mode == "ceiling"
        and rounded.rounding_increment_kg == Decimal("0.5")
        and rounded.rounding_applied is True
        and option_300.billed_weight_kg == Decimal("305.5")
        and option_300.base_freight == Decimal("611.000"),
        "reviewed ceiling rule rounds chargeable weight before tariff break evaluation",
    )

    raw = build_air_freight_calculation_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=305.2,
        volumetric_weight_kg=250,
        table_repository=tables,
        structure_repository=structures,
    )
    check(
        raw.chargeable_weight_kg == Decimal("305.2")
        and raw.rounding_review_id is None
        and raw.rounded_chargeable_weight_kg is None
        and raw.rounding_applied is False,
        "missing rounding review preserves legacy raw chargeable weight without inventing a rule",
    )

    none_repo = InMemoryAirRateWeightRoundingReviewRepository()
    none_review = _review(none_repo, sources, mode="none", increment=None)
    explicit_none = build_air_freight_calculation_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=305.2,
        volumetric_weight_kg=250,
        table_repository=tables,
        structure_repository=structures,
        rounding_repository=none_repo,
    )
    check(
        explicit_none.rounding_review_id == none_review.review_id
        and explicit_none.rounding_mode == "none"
        and explicit_none.rounded_chargeable_weight_kg == Decimal("305.2")
        and explicit_none.rounding_applied is False,
        "explicit no-rounding review is distinguishable from missing rounding evidence",
    )

    mismatch_repo = InMemoryAirRateWeightRoundingReviewRepository()
    mismatch_repo.create(AirRateWeightRoundingReview(
        source_id="source-0001",
        source_sha256="f" * 64,
        rounding_mode="ceiling",
        increment_kg=Decimal("1"),
        reviewed_by="Operator",
        reviewed_at=NOW,
        review_note="Synthetic mismatch.",
    ))
    mismatch_blocked = False
    try:
        build_air_freight_calculation_preview(
            review_id="table-review-0001",
            candidate_id="table-row-fra-0001",
            actual_weight_kg=305.2,
            volumetric_weight_kg=250,
            table_repository=tables,
            structure_repository=structures,
            rounding_repository=mismatch_repo,
        )
    except AirFreightCalculationPreviewError as exc:
        mismatch_blocked = str(exc) == "air_rate_weight_rounding_source_mismatch"
    check(mismatch_blocked, "rounding evidence never crosses immutable source SHA boundaries")

    surcharge_preview = build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=305.2,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=tables,
        structure_repository=structures,
        surcharge_repository=_matching_surcharge_repo(),
        source_repository=sources,
        rounding_repository=repo,
    )
    included = {item.surcharge_code: item for item in surcharge_preview.included_surcharges}
    check(
        surcharge_preview.freight.rounded_chargeable_weight_kg == Decimal("305.5")
        and surcharge_preview.freight.recommended_base_freight == Decimal("611.000")
        and included["FSC"].applied_weight_kg == Decimal("305.2")
        and included["SECURITY"].applied_weight_kg == Decimal("305.5"),
        "rounding affects tariff billed weight while preserving separately reviewed surcharge weight bases",
    )

    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pilot.sqlite3"
        sqlite_repo = SQLiteAirRateWeightRoundingReviewRepository(SQLitePilotStore(db_path))
        persisted = _review(sqlite_repo, sources)
        restored = SQLiteAirRateWeightRoundingReviewRepository(SQLitePilotStore(db_path)).get_by_source("source-0001")
        check(
            restored is not None
            and restored.review_id == persisted.review_id
            and restored.increment_kg == Decimal("0.5"),
            "weight-rounding review survives SQLite repository reconstruction",
        )
    check(
        "air_rate_weight_rounding_reviews" in PERSISTENT_STATE_NAMESPACES,
        "weight-rounding evidence is protected from ordinary retention purge",
    )

    from src import api
    api_repo = InMemoryAirRateWeightRoundingReviewRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    originals = (
        api.air_shadow_repository,
        api.air_rate_weight_rounding_review_repository,
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
    )
    try:
        api.air_shadow_repository = sources
        api.air_rate_weight_rounding_review_repository = api_repo
        api.air_rate_table_review_repository = tables
        api.air_rate_structure_review_repository = structures
        response = api.review_air_rate_source_weight_rounding(
            "source-0001",
            api.AirRateWeightRoundingReviewRequest(
                rounding_mode="ceiling",
                increment_kg=0.5,
                review_note="Exact source rounding rule verified.",
            ),
            request,
        )
        api_preview = api.preview_air_freight_calculation(
            "table-review-0001",
            "table-row-fra-0001",
            api.AirFreightCalculationPreviewRequest(
                actual_weight_kg=305.2,
                volumetric_weight_kg=250,
            ),
        )
    finally:
        (
            api.air_shadow_repository,
            api.air_rate_weight_rounding_review_repository,
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
        ) = originals
    check(
        response["review"]["reviewed_by"] == "API Air Operator"
        and response["freight_preview_consumption_enabled"] is True
        and response["customer_pricing_authority_enabled"] is False
        and response["booking_authority_enabled"] is False
        and api_preview["rounding_mode"] == "ceiling"
        and api_preview["rounded_chargeable_weight_kg"] == "305.5",
        "controlled API records and consumes explicit rounding evidence without quote or booking authority",
    )
    check(
        route_allowed("GET", "/air-rate-weight-rounding-reviews")
        and route_allowed("POST", "/air-rate-sources/source-1/weight-rounding-review"),
        "pilot access admits only bounded air weight-rounding review surfaces",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_rate_weight_rounding_review_service.py").read_text(encoding="utf-8")
    check(
        "Airline Weight Rounding" in js
        and "Weight Rounding Doğrula" in js
        and "unreviewed / raw chargeable" in js
        and "openai" not in service.casefold(),
        "browser makes reviewed versus missing rounding evidence visible without AI inference",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_weight_rounding_review_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir weight-rounding review regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
