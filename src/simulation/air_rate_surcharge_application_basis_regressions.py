from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_rate_surcharge_review import AirRateSurchargeCandidate, AirRateSurchargeReview
from src.core.air_rate_surcharge_review_repository import (
    InMemoryAirRateSurchargeReviewRepository,
    SQLiteAirRateSurchargeReviewRepository,
)
from src.core.air_rate_surcharge_review_service import (
    AirRateSurchargeReviewTransitionError,
    decide_air_rate_surcharge_application_basis,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore


def _confirmed_candidate(*, candidate_id: str, basis: str) -> AirRateSurchargeCandidate:
    return AirRateSurchargeCandidate(
        candidate_id=candidate_id,
        surcharge_code="FSC" if basis == "per_kg" else "HANDLING",
        amount="0.50" if basis == "per_kg" else "25",
        currency="USD",
        basis=basis,
        source_line_number=3,
        source_line_sha256="a" * 64,
        status="confirmed",
        reviewed_by="Senior Air Operator",
        reviewed_at=datetime(2026, 9, 13, 7, 0, tzinfo=timezone.utc),
        review_note="Amount, currency and unit verified.",
    )


def _review(*candidates: AirRateSurchargeCandidate) -> AirRateSurchargeReview:
    return AirRateSurchargeReview(
        review_id="surcharge-review-basis",
        source_id="air-source-basis",
        source_sha256="b" * 64,
        structure_review_id="structure-review-basis",
        extracted_text_sha256="c" * 64,
        candidates=list(candidates),
        status="completed",
        requested_by="Pilot Operator",
        created_at=datetime(2026, 9, 13, 7, 0, tzinfo=timezone.utc),
    )


def evaluate_air_rate_surcharge_application_basis_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    legacy = AirRateSurchargeCandidate.model_validate({
        "candidate_id": "legacy-confirmed-001",
        "surcharge_code": "FSC",
        "amount": "0.50",
        "currency": "USD",
        "basis": "per_kg",
        "source_line_number": 3,
        "source_line_sha256": "d" * 64,
        "status": "confirmed",
        "reviewed_by": "Senior Air Operator",
        "reviewed_at": "2026-09-13T07:00:00Z",
        "review_note": "Legacy reviewed surcharge.",
    })
    check(legacy.application_basis is None,
          "legacy confirmed surcharge remains readable with missing application-basis evidence")

    repo = InMemoryAirRateSurchargeReviewRepository()
    per_kg = _confirmed_candidate(candidate_id="perkg-confirmed-001", basis="per_kg")
    flat = _confirmed_candidate(candidate_id="flat-confirmed-001", basis="flat")
    review, _ = repo.create(_review(per_kg, flat))
    decided = decide_air_rate_surcharge_application_basis(
        review_id=review.review_id, candidate_id=per_kg.candidate_id,
        application_basis="chargeable_weight",
        review_note="Airline tariff applies FSC to chargeable weight.",
        reviewed_by="Senior Air Operator", repository=repo,
        reviewed_at=datetime(2026, 9, 13, 7, 5, tzinfo=timezone.utc),
    )
    updated = next(item for item in decided.candidates if item.candidate_id == per_kg.candidate_id)
    check(
        updated.application_basis == "chargeable_weight"
        and updated.application_basis_reviewed_by == "Senior Air Operator"
        and updated.application_basis_review_note == "Airline tariff applies FSC to chargeable weight."
        and updated.runtime_authoritative is False,
        "human application-basis review records explicit weight semantics without runtime authority",
    )

    duplicate_blocked = False
    try:
        decide_air_rate_surcharge_application_basis(
            review_id=review.review_id, candidate_id=per_kg.candidate_id,
            application_basis="pivot_billed_weight", review_note="Conflicting second basis.",
            reviewed_by="Senior Air Operator", repository=repo,
        )
    except AirRateSurchargeReviewTransitionError:
        duplicate_blocked = True
    check(duplicate_blocked, "reviewed surcharge application basis cannot be silently re-decided")

    wrong_basis_blocked = False
    try:
        decide_air_rate_surcharge_application_basis(
            review_id=review.review_id, candidate_id=flat.candidate_id,
            application_basis="chargeable_weight", review_note="Invalid flat mapping.",
            reviewed_by="Senior Air Operator", repository=repo,
        )
    except AirRateSurchargeReviewTransitionError:
        wrong_basis_blocked = True
    check(wrong_basis_blocked, "flat surcharge cannot be assigned a weight application basis")

    flat_decided = decide_air_rate_surcharge_application_basis(
        review_id=review.review_id, candidate_id=flat.candidate_id,
        application_basis="flat", review_note="Source states a flat shipment/AWB charge.",
        reviewed_by="Senior Air Operator", repository=repo,
    )
    flat_updated = next(item for item in flat_decided.candidates if item.candidate_id == flat.candidate_id)
    check(flat_updated.application_basis == "flat",
          "flat surcharge requires an explicit flat application-basis confirmation")

    proposed_repo = InMemoryAirRateSurchargeReviewRepository()
    proposed = AirRateSurchargeCandidate(
        candidate_id="proposed-basis-001", surcharge_code="FSC", amount="0.50", currency="USD",
        basis="per_kg", source_line_number=3, source_line_sha256="e" * 64,
    )
    proposed_review = AirRateSurchargeReview(
        review_id="pending-review-basis", source_id="pending-source-basis", source_sha256="f" * 64,
        structure_review_id="pending-structure-basis", extracted_text_sha256="1" * 64,
        candidates=[proposed], status="pending", requested_by="Pilot Operator",
    )
    proposed_repo.create(proposed_review)
    proposed_blocked = False
    try:
        decide_air_rate_surcharge_application_basis(
            review_id=proposed_review.review_id, candidate_id=proposed.candidate_id,
            application_basis="chargeable_weight", review_note="Too early.",
            reviewed_by="Senior Air Operator", repository=proposed_repo,
        )
    except AirRateSurchargeReviewTransitionError:
        proposed_blocked = True
    check(proposed_blocked, "unconfirmed surcharge cannot receive application-basis evidence")

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = SQLitePilotStore(root / "pilot.sqlite3")
        sqlite_repo = SQLiteAirRateSurchargeReviewRepository(store)
        candidate = _confirmed_candidate(candidate_id="durable-basis-001", basis="per_kg")
        durable_review = _review(candidate).model_copy(update={"review_id": "durable-review-basis"})
        sqlite_repo.create(durable_review)
        decide_air_rate_surcharge_application_basis(
            review_id=durable_review.review_id, candidate_id=candidate.candidate_id,
            application_basis="pivot_billed_weight",
            review_note="Airline source explicitly ties this surcharge to booked/pivot weight.",
            reviewed_by="Senior Air Operator", repository=sqlite_repo,
        )
        reopened = SQLiteAirRateSurchargeReviewRepository(SQLitePilotStore(root / "pilot.sqlite3"))
        stored = reopened.get(durable_review.review_id)
        stored_candidate = None if stored is None else stored.candidates[0]
        check(
            stored_candidate is not None
            and stored_candidate.application_basis == "pivot_billed_weight"
            and stored_candidate.application_basis_reviewed_by == "Senior Air Operator",
            "surcharge application-basis evidence survives SQLite repository reconstruction",
        )

    from src import api
    api_repo = InMemoryAirRateSurchargeReviewRepository()
    api_candidate = _confirmed_candidate(candidate_id="api-basis-001", basis="per_kg")
    api_review = _review(api_candidate).model_copy(update={"review_id": "api-review-basis"})
    api_repo.create(api_review)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    original = api.air_rate_surcharge_review_repository
    try:
        api.air_rate_surcharge_review_repository = api_repo
        response = api.decide_air_rate_surcharge_application_basis_endpoint(
            api_review.review_id, api_candidate.candidate_id,
            api.AirRateSurchargeApplicationBasisRequest(
                application_basis="actual_weight",
                review_note="Explicit airline condition says actual weight.",
            ),
            request,
        )
        listing = api.list_air_rate_surcharge_reviews()
    finally:
        api.air_rate_surcharge_review_repository = original
    api_updated = response["review"]["candidates"][0]
    check(
        api_updated["application_basis"] == "actual_weight"
        and api_updated["application_basis_reviewed_by"] == "API Air Operator"
        and response["pricing_authority_enabled"] is False
        and response["calculation_consumption_enabled"] is False
        and listing["application_basis_review_enabled"] is True
        and listing["application_weight_authority_enabled"] is False,
        "controlled API records authenticated application-basis review without calculation authority",
    )

    check(
        route_allowed("POST", "/air-rate-surcharge-reviews/review-1/candidates/candidate-1/application-basis"),
        "pilot access admits bounded surcharge application-basis review route",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    preview = (root / "src" / "core" / "air_freight_calculation_preview.py").read_text(encoding="utf-8")
    check(
        "Uygulama Tabanını Doğrula" in js
        and "Gerçek ağırlık" in js
        and "Chargeable weight" in js
        and "Pivot sonucu billed weight" in js
        and "Bu seçim surcharge'ı hesaba katmaz" in js,
        "browser requires explicit surcharge application-basis review and states it is not calculation consumption",
    )
    check(
        "air_rate_surcharge" not in preview
        and "AirRateSurcharge" not in preview,
        "freight calculation preview still does not consume surcharge review evidence",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_surcharge_application_basis_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir surcharge application-basis regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
