from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_rate_validity_review_repository import (
    InMemoryAirRateValidityReviewRepository,
    SQLiteAirRateValidityReviewRepository,
)
from src.core.air_rate_validity_review_service import (
    AirRateValidityReviewTransitionError,
    review_air_rate_validity,
)
from src.core.air_reviewed_surcharge_cost_preview import (
    AirReviewedSurchargeCostPreviewError,
    build_air_reviewed_surcharge_cost_preview,
)
from src.core.air_shadow import AirRateSource
from src.core.air_shadow_repository import InMemoryAirShadowRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import (
    _source_repo,
    _standard_repo,
    _structure_repo,
    _table_repo,
)

NOW = datetime(2026, 9, 13, 11, 10, tzinfo=timezone.utc)


def _review(repo, source_repo, *, start=date(2026, 9, 1), end=date(2026, 9, 30), actor="Senior Air Operator"):
    return review_air_rate_validity(
        source_id="source-0001",
        valid_from=start,
        valid_to=end,
        review_note="Validity period confirmed from exact tariff source.",
        reviewed_by=actor,
        reviewed_at=NOW,
        source_repository=source_repo,
        repository=repo,
    )


def _preview(validity_repo, *, reference_date=None):
    return build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_standard_repo(),
        source_repository=_source_repo(),
        validity_repository=validity_repo,
        reference_date=reference_date,
    )


def evaluate_air_rate_validity_review_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    repo = InMemoryAirRateValidityReviewRepository()
    review = _review(repo, source_repo)
    check(
        review.valid_from == date(2026, 9, 1)
        and review.valid_to == date(2026, 9, 30)
        and review.source_sha256 == "a" * 64
        and review.runtime_authoritative is False,
        "human tariff-validity review stores source-bound date evidence without runtime authority",
    )

    repeat_blocked = False
    try:
        _review(repo, source_repo, start=date(2026, 9, 2), end=date(2026, 9, 30))
    except AirRateValidityReviewTransitionError:
        repeat_blocked = True
    check(repeat_blocked, "reviewed tariff validity cannot be silently re-decided")

    metadata_repo = InMemoryAirShadowRepository()
    metadata_repo.create_rate_source(AirRateSource(
        source_id="source-0001",
        entry_id="validity-metadata-source",
        airline_name="THY",
        document_name="validity.pdf",
        sha256_hex="9" * 64,
        cargo_scope="general_cargo",
        valid_from=date(2026, 9, 1),
        valid_to=date(2026, 9, 30),
        recorded_by="Air Operator",
        recorded_at=NOW,
    ))
    conflict = False
    try:
        _review(InMemoryAirRateValidityReviewRepository(), metadata_repo, start=date(2026, 9, 2))
    except AirRateValidityReviewTransitionError:
        conflict = True
    check(conflict, "validity review cannot contradict immutable source date metadata")

    no_date_preview = _preview(repo)
    check(
        no_date_preview.tariff_validity_confirmed is False
        and no_date_preview.reference_date is None
        and no_date_preview.validity_review_id is None,
        "preview never assumes today or claims tariff validity without an explicit reference date",
    )

    missing_review_blocked = False
    try:
        _preview(InMemoryAirRateValidityReviewRepository(), reference_date=date(2026, 9, 13))
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_review_blocked = str(exc) == "air_rate_validity_review_required"
    check(missing_review_blocked, "reference-dated preview fails closed without source validity review")

    in_range = _preview(repo, reference_date=date(2026, 9, 13))
    check(
        in_range.tariff_validity_confirmed is True
        and in_range.reference_date == date(2026, 9, 13)
        and in_range.validity_review_id == review.review_id
        and in_range.reviewed_valid_from == date(2026, 9, 1)
        and in_range.reviewed_valid_to == date(2026, 9, 30)
        and in_range.capacity_confirmed is False
        and in_range.customer_quote_eligible is False,
        "in-range reference date confirms only reviewed tariff validity and no capacity or quote authority",
    )

    expired_blocked = False
    try:
        _preview(repo, reference_date=date(2026, 10, 1))
    except AirReviewedSurchargeCostPreviewError as exc:
        expired_blocked = str(exc) == "air_rate_tariff_not_valid_for_reference_date"
    check(expired_blocked, "out-of-range tariff reference date fails closed instead of using stale reviewed rates")

    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pilot.sqlite3"
        sqlite_repo = SQLiteAirRateValidityReviewRepository(SQLitePilotStore(db_path))
        created = _review(sqlite_repo, source_repo, actor="Persistence Operator")
        restored = SQLiteAirRateValidityReviewRepository(SQLitePilotStore(db_path)).get_by_source("source-0001")
        check(
            restored is not None
            and restored.review_id == created.review_id
            and restored.valid_from == date(2026, 9, 1)
            and restored.reviewed_by == "Persistence Operator",
            "tariff-validity review survives SQLite repository reconstruction",
        )
    check(
        "air_rate_validity_reviews" in PERSISTENT_STATE_NAMESPACES,
        "tariff-validity review evidence is protected from ordinary retention purge",
    )

    from src import api
    api_repo = InMemoryAirRateValidityReviewRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    originals = (api.air_shadow_repository, api.air_rate_validity_review_repository)
    try:
        api.air_shadow_repository = source_repo
        api.air_rate_validity_review_repository = api_repo
        response = api.review_air_rate_source_validity(
            "source-0001",
            api.AirRateValidityReviewRequest(
                valid_from=date(2026, 9, 1),
                valid_to=date(2026, 9, 30),
                review_note="Exact source validity verified.",
            ),
            request,
        )
    finally:
        api.air_shadow_repository, api.air_rate_validity_review_repository = originals
    check(
        response["review"]["reviewed_by"] == "API Air Operator"
        and response["pricing_authority_enabled"] is False
        and response["capacity_confirmed"] is False
        and response["schedule_confirmed"] is False,
        "controlled API records authenticated validity evidence without pricing capacity or schedule authority",
    )

    check(
        route_allowed("POST", "/air-rate-sources/source-1/validity-review")
        and route_allowed("GET", "/air-rate-validity-reviews"),
        "pilot access admits bounded tariff-validity review and read surface",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_reviewed_surcharge_cost_preview.py").read_text(encoding="utf-8")
    check(
        "Tarife Geçerliliğini Doğrula" in js
        and "Tarife referans tarihi" in js
        and "bugünün tarihi varsayılmaz" in js
        and "openai" not in service.casefold(),
        "browser requires explicit validity review and reference date without AI or current-date inference",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_validity_review_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir tariff validity review regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
