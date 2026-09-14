from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_rate_surcharge_review_repository import (
    InMemoryAirRateSurchargeReviewRepository,
    SQLiteAirRateSurchargeReviewRepository,
)
from src.core.air_rate_surcharge_review_service import (
    AirRateSurchargeReviewTransitionError,
    decide_air_rate_surcharge_flat_quantity_basis,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import (
    _candidate,
    _source_repo,
    _structure_repo,
    _table_repo,
)
from src.core.air_rate_surcharge_review import AirRateSurchargeReview
from src.core.air_reviewed_surcharge_cost_preview import (
    AirReviewedSurchargeCostPreviewError,
    build_air_reviewed_surcharge_cost_preview,
)


NOW = datetime(2026, 9, 13, 10, 10, tzinfo=timezone.utc)


def _flat_review(*, review_id: str = "flat-quantity-review-001", candidate_id: str = "flat-quantity-001") -> AirRateSurchargeReview:
    candidate = _candidate(
        candidate_id,
        "HANDLING",
        "25",
        basis="flat",
        application_basis="flat",
    )
    return AirRateSurchargeReview(
        review_id=review_id,
        source_id="source-0001",
        source_sha256="a" * 64,
        structure_review_id="structure-review-0001",
        extracted_text_sha256="b" * 64,
        candidates=[candidate],
        status="completed",
        requested_by="Air Operator",
        created_at=NOW,
    )


def evaluate_air_rate_surcharge_flat_quantity_basis_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    legacy = _flat_review().candidates[0]
    check(
        legacy.flat_quantity_basis is None
        and legacy.flat_quantity_basis_reviewed_by is None,
        "legacy fully-reviewed flat surcharge remains readable without quantity-basis evidence",
    )

    repo = InMemoryAirRateSurchargeReviewRepository()
    review, _ = repo.create(_flat_review())
    decided = decide_air_rate_surcharge_flat_quantity_basis(
        review_id=review.review_id,
        candidate_id=review.candidates[0].candidate_id,
        flat_quantity_basis="per_awb",
        review_note="Tariff wording explicitly states AWB fee.",
        reviewed_by="Senior Air Operator",
        repository=repo,
        reviewed_at=NOW,
    )
    item = decided.candidates[0]
    check(
        item.flat_quantity_basis == "per_awb"
        and item.flat_quantity_basis_reviewed_by == "Senior Air Operator"
        and item.flat_quantity_basis_review_note == "Tariff wording explicitly states AWB fee."
        and item.runtime_authoritative is False,
        "human review stores explicit flat quantity semantics without pricing authority",
    )

    duplicate_blocked = False
    try:
        decide_air_rate_surcharge_flat_quantity_basis(
            review_id=review.review_id,
            candidate_id=item.candidate_id,
            flat_quantity_basis="per_shipment",
            review_note="Conflicting second choice.",
            reviewed_by="Air Operator",
            repository=repo,
        )
    except AirRateSurchargeReviewTransitionError:
        duplicate_blocked = True
    check(duplicate_blocked, "reviewed flat quantity basis cannot be silently re-decided")

    perkg_repo = InMemoryAirRateSurchargeReviewRepository()
    perkg_review = AirRateSurchargeReview(
        review_id="flat-quantity-perkg-review",
        source_id="source-0001",
        source_sha256="a" * 64,
        structure_review_id="structure-review-0001",
        extracted_text_sha256="b" * 64,
        candidates=[_candidate("flat-quantity-perkg", "FSC", "0.50")],
        status="completed",
        requested_by="Air Operator",
        created_at=NOW,
    )
    perkg_repo.create(perkg_review)
    perkg_blocked = False
    try:
        decide_air_rate_surcharge_flat_quantity_basis(
            review_id=perkg_review.review_id,
            candidate_id=perkg_review.candidates[0].candidate_id,
            flat_quantity_basis="per_awb",
            review_note="Not a flat charge.",
            reviewed_by="Air Operator",
            repository=perkg_repo,
        )
    except AirRateSurchargeReviewTransitionError:
        perkg_blocked = True
    check(perkg_blocked, "per-kg surcharge cannot receive flat quantity-basis evidence")

    incomplete_repo = InMemoryAirRateSurchargeReviewRepository()
    incomplete_candidate = _candidate(
        "flat-quantity-incomplete",
        "HANDLING",
        "25",
        basis="flat",
        application_basis="flat",
        cargo_applicability=None,
        routing_applicability=None,
    )
    incomplete_review = AirRateSurchargeReview(
        review_id="flat-quantity-incomplete-review",
        source_id="source-0001",
        source_sha256="a" * 64,
        structure_review_id="structure-review-0001",
        extracted_text_sha256="b" * 64,
        candidates=[incomplete_candidate],
        status="completed",
        requested_by="Air Operator",
        created_at=NOW,
    )
    incomplete_repo.create(incomplete_review)
    prior_review_blocked = False
    try:
        decide_air_rate_surcharge_flat_quantity_basis(
            review_id=incomplete_review.review_id,
            candidate_id=incomplete_candidate.candidate_id,
            flat_quantity_basis="per_shipment",
            review_note="Too early.",
            reviewed_by="Air Operator",
            repository=incomplete_repo,
        )
    except AirRateSurchargeReviewTransitionError:
        prior_review_blocked = True
    check(prior_review_blocked, "flat quantity review waits for completed destination cargo and routing review evidence")

    with TemporaryDirectory() as td:
        sqlite_repo = SQLiteAirRateSurchargeReviewRepository(SQLitePilotStore(Path(td) / "pilot.sqlite3"))
        sqlite_review, _ = sqlite_repo.create(_flat_review(review_id="flat-quantity-sqlite-review", candidate_id="flat-quantity-sqlite"))
        decide_air_rate_surcharge_flat_quantity_basis(
            review_id=sqlite_review.review_id,
            candidate_id=sqlite_review.candidates[0].candidate_id,
            flat_quantity_basis="per_mawb",
            review_note="MAWB basis verified from tariff evidence.",
            reviewed_by="Persistence Operator",
            repository=sqlite_repo,
            reviewed_at=NOW,
        )
        rebuilt = SQLiteAirRateSurchargeReviewRepository(SQLitePilotStore(Path(td) / "pilot.sqlite3"))
        stored = rebuilt.get(sqlite_review.review_id)
        check(
            stored is not None
            and stored.candidates[0].flat_quantity_basis == "per_mawb"
            and stored.candidates[0].flat_quantity_basis_reviewed_by == "Persistence Operator",
            "flat quantity-basis evidence survives SQLite repository reconstruction",
        )

    from src import api
    api_repo = InMemoryAirRateSurchargeReviewRepository()
    api_review, _ = api_repo.create(_flat_review(review_id="flat-quantity-api-review", candidate_id="flat-quantity-api"))
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    original_repo = api.air_rate_surcharge_review_repository
    try:
        api.air_rate_surcharge_review_repository = api_repo
        response = api.decide_air_rate_surcharge_flat_quantity_basis_endpoint(
            api_review.review_id,
            api_review.candidates[0].candidate_id,
            api.AirRateSurchargeFlatQuantityBasisRequest(
                flat_quantity_basis="per_hawb",
                review_note="HAWB basis explicitly verified.",
            ),
            request,
        )
    finally:
        api.air_rate_surcharge_review_repository = original_repo
    api_item = response["review"]["candidates"][0]
    check(
        api_item["flat_quantity_basis"] == "per_hawb"
        and api_item["flat_quantity_basis_reviewed_by"] == "API Air Operator"
        and response["calculation_consumption_enabled"] is False
        and response["pricing_authority_enabled"] is False,
        "controlled API records authenticated flat quantity semantics without calculation authority",
    )

    check(
        route_allowed("POST", "/air-rate-surcharge-reviews/r/candidates/c/flat-quantity-basis"),
        "pilot access admits bounded flat quantity-basis review route",
    )

    preview_repo = InMemoryAirRateSurchargeReviewRepository()
    preview_review, _ = preview_repo.create(_flat_review(review_id="flat-quantity-preview-review", candidate_id="flat-quantity-preview"))
    decide_air_rate_surcharge_flat_quantity_basis(
        review_id=preview_review.review_id,
        candidate_id=preview_review.candidates[0].candidate_id,
        flat_quantity_basis="per_shipment",
        review_note="Shipment basis verified.",
        reviewed_by="Air Operator",
        repository=preview_repo,
        reviewed_at=NOW,
    )
    missing_count_blocked = False
    try:
        build_air_reviewed_surcharge_cost_preview(
            review_id="table-review-0001",
            candidate_id="table-row-fra-0001",
            actual_weight_kg=287,
            volumetric_weight_kg=250,
            cargo_context="general_cargo",
            routing_context="direct",
            table_repository=_table_repo(),
            structure_repository=_structure_repo(),
            surcharge_repository=preview_repo,
            source_repository=_source_repo(),
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_count_blocked = str(exc) == "flat_surcharge_count_required:per_shipment"
    check(
        missing_count_blocked,
        "reviewed flat quantity evidence still requires an explicit matching preview count",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    preview_service = (root / "src" / "core" / "air_reviewed_surcharge_cost_preview.py").read_text(encoding="utf-8")
    check(
        "Flat Quantity Basis Doğrula" in js
        and "Shipment başına" in js
        and "AWB başına" in js
        and "matching explicit count verilmeden flat ücret cost preview'a eklenmez" in js,
        "browser exposes explicit flat quantity review while keeping count-dependent calculation closed",
    )
    check(
        "flat_quantity_basis" in preview_service
        and "flat_surcharge_count_required" in preview_service
        and "shipment_count" in preview_service,
        "reviewed surcharge cost preview consumes flat quantity basis only behind explicit count input",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_surcharge_flat_quantity_basis_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir flat surcharge quantity-basis regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
