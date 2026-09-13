from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
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
    decide_air_rate_surcharge_applicability_scope,
)
from src.core.air_rate_table_review import AirRateTableReview, AirRateTableRowCandidate
from src.core.air_rate_table_review_repository import InMemoryAirRateTableReviewRepository
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore

NOW = datetime(2026, 9, 13, 8, 40, tzinfo=timezone.utc)


def _candidate(*, candidate_id: str = "scope-candidate-001", application_basis: str | None = "chargeable_weight"):
    kwargs = {}
    if application_basis is not None:
        kwargs = {
            "application_basis": application_basis,
            "application_basis_reviewed_by": "Senior Air Operator",
            "application_basis_reviewed_at": NOW,
            "application_basis_review_note": "Weight basis verified.",
        }
    return AirRateSurchargeCandidate(
        candidate_id=candidate_id,
        surcharge_code="FSC",
        amount="0.50",
        currency="USD",
        basis="per_kg",
        source_line_number=3,
        source_line_sha256="a" * 64,
        status="confirmed",
        reviewed_by="Senior Air Operator",
        reviewed_at=NOW,
        review_note="Amount, currency and unit verified.",
        **kwargs,
    )


def _review(candidate: AirRateSurchargeCandidate, *, review_id: str = "scope-review-001"):
    return AirRateSurchargeReview(
        review_id=review_id,
        source_id="air-source-scope",
        source_sha256="b" * 64,
        structure_review_id="structure-scope",
        extracted_text_sha256="c" * 64,
        candidates=[candidate],
        status="completed",
        requested_by="Pilot Operator",
        created_at=NOW,
    )


def _table_repo(*, row_status: str = "confirmed", code: str = "FRA"):
    repo = InMemoryAirRateTableReviewRepository()
    row = AirRateTableRowCandidate(
        candidate_id="scope-table-row-001",
        destination_label=code,
        destination_code=code,
        currency="USD",
        rates={"MIN": Decimal("120"), "+100": Decimal("2.50")},
        source_line_number=2,
        source_line_sha256="d" * 64,
        status=row_status,
        reviewed_by="Air Operator" if row_status != "proposed" else None,
        reviewed_at=NOW if row_status != "proposed" else None,
        review_note="Verified destination row." if row_status != "proposed" else None,
    )
    review = AirRateTableReview(
        review_id="scope-table-review",
        source_id="air-source-scope",
        source_sha256="b" * 64,
        structure_review_id="structure-scope",
        extracted_text_sha256="c" * 64,
        weight_breaks=["MIN", "+100"],
        candidates=[row],
        status="completed" if row_status != "proposed" else "pending",
        requested_by="Air Operator",
        created_at=NOW,
    )
    repo.create(review)
    return repo


def evaluate_air_rate_surcharge_applicability_scope_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    legacy = _candidate()
    check(
        legacy.applicability_scope is None and legacy.applicability_destination_code is None,
        "legacy basis-reviewed surcharge remains readable without applicability evidence",
    )

    repo = InMemoryAirRateSurchargeReviewRepository()
    candidate = _candidate()
    review, _ = repo.create(_review(candidate))
    source_wide = decide_air_rate_surcharge_applicability_scope(
        review_id=review.review_id,
        candidate_id=candidate.candidate_id,
        applicability_scope="source_wide",
        destination_code=None,
        review_note="Tariff note states this surcharge applies across destinations in this source.",
        reviewed_by="Senior Air Operator",
        repository=repo,
        table_repository=_table_repo(),
        reviewed_at=NOW,
    )
    updated = source_wide.candidates[0]
    check(
        updated.applicability_scope == "source_wide"
        and updated.applicability_destination_code is None
        and updated.applicability_reviewed_by == "Senior Air Operator"
        and updated.runtime_authoritative is False,
        "source-wide applicability review records bounded source-local evidence only",
    )

    duplicate_blocked = False
    try:
        decide_air_rate_surcharge_applicability_scope(
            review_id=review.review_id,
            candidate_id=candidate.candidate_id,
            applicability_scope="destination_specific",
            destination_code="FRA",
            review_note="Conflicting second scope.",
            reviewed_by="Senior Air Operator",
            repository=repo,
            table_repository=_table_repo(),
        )
    except AirRateSurchargeReviewTransitionError:
        duplicate_blocked = True
    check(duplicate_blocked, "reviewed applicability scope cannot be silently re-decided")

    pre_basis_repo = InMemoryAirRateSurchargeReviewRepository()
    pre_basis = _candidate(candidate_id="scope-no-basis-01", application_basis=None)
    pre_review, _ = pre_basis_repo.create(_review(pre_basis, review_id="scope-no-basis-review"))
    before_basis_blocked = False
    try:
        decide_air_rate_surcharge_applicability_scope(
            review_id=pre_review.review_id,
            candidate_id=pre_basis.candidate_id,
            applicability_scope="source_wide",
            destination_code=None,
            review_note="Too early.",
            reviewed_by="Senior Air Operator",
            repository=pre_basis_repo,
            table_repository=_table_repo(),
        )
    except AirRateSurchargeReviewTransitionError:
        before_basis_blocked = True
    check(before_basis_blocked, "applicability review waits for explicit application-basis evidence")

    specific_repo = InMemoryAirRateSurchargeReviewRepository()
    specific_candidate = _candidate(candidate_id="scope-specific-01")
    specific_review, _ = specific_repo.create(_review(specific_candidate, review_id="scope-specific-review"))
    missing_code_blocked = False
    try:
        decide_air_rate_surcharge_applicability_scope(
            review_id=specific_review.review_id,
            candidate_id=specific_candidate.candidate_id,
            applicability_scope="destination_specific",
            destination_code=None,
            review_note="Destination-specific but no code.",
            reviewed_by="Senior Air Operator",
            repository=specific_repo,
            table_repository=_table_repo(),
        )
    except AirRateSurchargeReviewTransitionError:
        missing_code_blocked = True
    check(missing_code_blocked, "destination-specific applicability requires a destination code")

    unconfirmed_code_blocked = False
    try:
        decide_air_rate_surcharge_applicability_scope(
            review_id=specific_review.review_id,
            candidate_id=specific_candidate.candidate_id,
            applicability_scope="destination_specific",
            destination_code="MUC",
            review_note="MUC is not a confirmed tariff row.",
            reviewed_by="Senior Air Operator",
            repository=specific_repo,
            table_repository=_table_repo(code="FRA"),
        )
    except AirRateSurchargeReviewTransitionError as exc:
        unconfirmed_code_blocked = str(exc) == "destination_scope_requires_confirmed_tariff_row"
    check(unconfirmed_code_blocked, "destination scope must resolve to a human-confirmed tariff row in the same source")

    specific = decide_air_rate_surcharge_applicability_scope(
        review_id=specific_review.review_id,
        candidate_id=specific_candidate.candidate_id,
        applicability_scope="destination_specific",
        destination_code="fra",
        review_note="Source explicitly limits this FSC to FRA.",
        reviewed_by="Senior Air Operator",
        repository=specific_repo,
        table_repository=_table_repo(code="FRA"),
    )
    specific_updated = specific.candidates[0]
    check(
        specific_updated.applicability_scope == "destination_specific"
        and specific_updated.applicability_destination_code == "FRA",
        "destination-specific applicability stores normalized confirmed destination identity",
    )

    source_code_repo = InMemoryAirRateSurchargeReviewRepository()
    source_code_candidate = _candidate(candidate_id="scope-source-code-01")
    source_code_review, _ = source_code_repo.create(_review(source_code_candidate, review_id="scope-source-code-review"))
    source_code_blocked = False
    try:
        decide_air_rate_surcharge_applicability_scope(
            review_id=source_code_review.review_id,
            candidate_id=source_code_candidate.candidate_id,
            applicability_scope="source_wide",
            destination_code="FRA",
            review_note="Invalid mixed scope.",
            reviewed_by="Senior Air Operator",
            repository=source_code_repo,
            table_repository=_table_repo(),
        )
    except AirRateSurchargeReviewTransitionError:
        source_code_blocked = True
    check(source_code_blocked, "source-wide applicability refuses a destination code")

    with TemporaryDirectory() as temporary:
        root = Path(temporary)
        store = SQLitePilotStore(root / "pilot.sqlite3")
        sqlite_repo = SQLiteAirRateSurchargeReviewRepository(store)
        durable_candidate = _candidate(candidate_id="scope-durable-01")
        durable_review = _review(durable_candidate, review_id="scope-durable-review")
        sqlite_repo.create(durable_review)
        decide_air_rate_surcharge_applicability_scope(
            review_id=durable_review.review_id,
            candidate_id=durable_candidate.candidate_id,
            applicability_scope="destination_specific",
            destination_code="FRA",
            review_note="Durable destination scope evidence.",
            reviewed_by="Senior Air Operator",
            repository=sqlite_repo,
            table_repository=_table_repo(),
        )
        reopened = SQLiteAirRateSurchargeReviewRepository(SQLitePilotStore(root / "pilot.sqlite3"))
        stored = reopened.get(durable_review.review_id)
        stored_candidate = None if stored is None else stored.candidates[0]
        check(
            stored_candidate is not None
            and stored_candidate.applicability_scope == "destination_specific"
            and stored_candidate.applicability_destination_code == "FRA",
            "surcharge applicability evidence survives SQLite repository reconstruction",
        )

    from src import api
    api_repo = InMemoryAirRateSurchargeReviewRepository()
    api_candidate = _candidate(candidate_id="scope-api-01")
    api_review = _review(api_candidate, review_id="scope-api-review")
    api_repo.create(api_review)
    api_tables = _table_repo()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Operator"
    originals = (api.air_rate_surcharge_review_repository, api.air_rate_table_review_repository)
    try:
        api.air_rate_surcharge_review_repository = api_repo
        api.air_rate_table_review_repository = api_tables
        response = api.decide_air_rate_surcharge_applicability_scope_endpoint(
            api_review.review_id,
            api_candidate.candidate_id,
            api.AirRateSurchargeApplicabilityScopeRequest(
                applicability_scope="destination_specific",
                destination_code="FRA",
                review_note="API operator verified FRA applicability.",
            ),
            request,
        )
        listing = api.list_air_rate_surcharge_reviews()
    finally:
        api.air_rate_surcharge_review_repository, api.air_rate_table_review_repository = originals
    api_updated = response["review"]["candidates"][0]
    check(
        api_updated["applicability_scope"] == "destination_specific"
        and api_updated["applicability_reviewed_by"] == "API Air Operator"
        and response["calculation_consumption_enabled"] is False
        and listing["applicability_scope_review_enabled"] is True
        and listing["pricing_authority_enabled"] is False,
        "controlled API records authenticated applicability review without calculation authority",
    )

    check(
        route_allowed("POST", "/air-rate-surcharge-reviews/review-1/candidates/candidate-1/applicability-scope"),
        "pilot access admits bounded surcharge applicability review route",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    preview = (root / "src" / "core" / "air_freight_calculation_preview.py").read_text(encoding="utf-8")
    check(
        "Uygulanabilirlik Kapsamını Doğrula" in js
        and "Bu PDF kaynağının kapsadığı destinasyonlar" in js
        and "Destination code (yalnız belirli destination)" in js
        and "routing ve özel-kargo koşulları ayrıca çözülmelidir" in js,
        "browser requires explicit source-local or destination-specific applicability review",
    )
    check(
        "air_rate_surcharge" not in preview and "AirRateSurcharge" not in preview,
        "freight calculation preview still does not consume surcharge applicability evidence",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_rate_surcharge_applicability_scope_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir surcharge applicability scope regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
