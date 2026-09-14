from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_cost_scope_review import AIR_COST_SCOPE_CATEGORIES
from src.core.air_cost_scope_review_repository import (
    InMemoryAirCostScopeReviewRepository,
    SQLiteAirCostScopeReviewRepository,
)
from src.core.air_cost_scope_review_service import (
    AirCostScopeReviewTransitionError,
    build_air_cost_scope_review_view,
    record_air_cost_scope_review,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_additional_cost_evidence_regressions import _partial_cost_preview
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import _source_repo


NOW = datetime(2026, 9, 14, 9, 45, tzinfo=timezone.utc)


def _requirements(*, unresolved: str | None = None, required: tuple[str, ...] = ("pickup", "delivery")):
    result = []
    for category in AIR_COST_SCOPE_CATEGORIES:
        status = "required" if category in required else "not_applicable"
        if category == unresolved:
            status = "unresolved"
        result.append({
            "category": category,
            "status": status,
            "rationale": f"{category} scope explicitly reviewed for this inquiry.",
        })
    return result


def _record(repo, source_repo, **overrides):
    payload = {
        "source_id": "source-0001",
        "entry_id": "air-cost-scope-0001",
        "inquiry_reference": "AIR-INQ-20260914-SCOPE-1",
        "requirements": _requirements(),
        "review_note": "Service scope and known local-cost responsibility reviewed item by item.",
        "reviewed_by": "Senior Air Operator",
        "reviewed_at": NOW,
        "source_repository": source_repo,
        "repository": repo,
    }
    payload.update(overrides)
    return record_air_cost_scope_review(**payload)


def evaluate_air_cost_scope_review_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    repo = InMemoryAirCostScopeReviewRepository()
    review, created = _record(repo, source_repo)
    check(
        created is True
        and review.source_sha256 == source_repo.get_rate_source("source-0001").sha256_hex
        and review.scope_classification_complete is True
        and review.required_categories == ["pickup", "delivery"]
        and review.unresolved_categories == []
        and review.runtime_authoritative is False
        and review.pricing_authority is False
        and review.cost_completeness_authority is False,
        "complete scope classification preserves exact source inquiry provenance without cost or pricing authority",
    )

    same, created_again = _record(repo, source_repo)
    check(
        created_again is False and same.review_id == review.review_id,
        "cost-scope review entry identity is idempotent for identical evidence",
    )

    conflict_blocked = False
    try:
        _record(repo, source_repo, requirements=_requirements(required=("pickup",)))
    except AirCostScopeReviewTransitionError:
        conflict_blocked = True
    check(
        conflict_blocked,
        "cost-scope entry identity fails closed when reused with different scope evidence",
    )

    unresolved_repo = InMemoryAirCostScopeReviewRepository()
    unresolved, _ = _record(
        unresolved_repo,
        source_repo,
        entry_id="air-cost-scope-unresolved",
        requirements=_requirements(unresolved="destination_terminal"),
    )
    check(
        unresolved.scope_classification_complete is False
        and unresolved.unresolved_categories == ["destination_terminal"],
        "an unresolved category remains visible and prevents scope-classification completeness",
    )

    missing_category_blocked = False
    try:
        _record(
            InMemoryAirCostScopeReviewRepository(),
            source_repo,
            entry_id="air-cost-scope-missing",
            requirements=_requirements()[:-1],
        )
    except AirCostScopeReviewTransitionError:
        missing_category_blocked = True
    check(
        missing_category_blocked,
        "scope review cannot omit a supported local-cost category",
    )

    duplicate_category_blocked = False
    duplicated = _requirements()
    duplicated[-1] = dict(duplicated[0])
    try:
        _record(
            InMemoryAirCostScopeReviewRepository(),
            source_repo,
            entry_id="air-cost-scope-duplicate",
            requirements=duplicated,
        )
    except AirCostScopeReviewTransitionError:
        duplicate_category_blocked = True
    check(
        duplicate_category_blocked,
        "scope review cannot duplicate one category while silently dropping another",
    )

    view = build_air_cost_scope_review_view(repository=unresolved_repo)
    check(
        view["reviews"][0]["scope_classification_complete"] is False
        and view["reviews"][0]["unresolved_categories"] == ["destination_terminal"]
        and view["cost_completeness_authority_enabled"] is False
        and view["cost_preview_consumption_enabled"] is False
        and view["customer_quote_eligible"] is False,
        "scope review view exposes classification state while explicitly withholding completeness and quote authority",
    )

    before = _partial_cost_preview()
    _record(
        InMemoryAirCostScopeReviewRepository(),
        source_repo,
        entry_id="air-cost-scope-no-consumption",
        inquiry_reference="AIR-INQ-NO-CONSUMPTION",
    )
    after = _partial_cost_preview()
    check(
        before.base_plus_reviewed_surcharges == after.base_plus_reviewed_surcharges
        and before.all_in_cost is False
        and after.all_in_cost is False
        and after.customer_quote_eligible is False,
        "stored scope classification has zero automatic effect on reviewed cost preview",
    )

    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "pilot.sqlite3"
        sqlite_repo = SQLiteAirCostScopeReviewRepository(SQLitePilotStore(db_path))
        persisted, _ = _record(
            sqlite_repo,
            source_repo,
            entry_id="air-cost-scope-sqlite",
            inquiry_reference="AIR-INQ-SQLITE-SCOPE",
        )
        restored = SQLiteAirCostScopeReviewRepository(SQLitePilotStore(db_path)).get(
            persisted.review_id
        )
        check(
            restored is not None
            and restored.inquiry_reference == "AIR-INQ-SQLITE-SCOPE"
            and restored.required_categories == ["pickup", "delivery"]
            and restored.scope_classification_complete is True,
            "cost-scope review survives SQLite repository reconstruction",
        )

    check(
        "air_cost_scope_reviews" in PERSISTENT_STATE_NAMESPACES
        and "air_cost_scope_review_by_entry" in PERSISTENT_STATE_NAMESPACES,
        "cost-scope review evidence is protected from ordinary retention purge",
    )

    from src import api
    api_repo = InMemoryAirCostScopeReviewRepository()
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Air Scope Operator"
    originals = (api.air_shadow_repository, api.air_cost_scope_review_repository)
    try:
        api.air_shadow_repository = source_repo
        api.air_cost_scope_review_repository = api_repo
        response = api.create_air_cost_scope_review(
            "source-0001",
            api.AirCostScopeReviewRequest(
                entry_id="air-cost-scope-api",
                inquiry_reference="AIR-INQ-API-SCOPE",
                requirements=[api.AirCostScopeRequirementRequest(**item) for item in _requirements()],
                review_note="API review covers every supported cost-scope category explicitly.",
            ),
            request,
        )
    finally:
        api.air_shadow_repository, api.air_cost_scope_review_repository = originals
    check(
        response["created"] is True
        and response["scope_classification_complete"] is True
        and response["review"]["reviewed_by"] == "API Air Scope Operator"
        and response["cost_completeness_authority_enabled"] is False
        and response["cost_preview_consumption_enabled"] is False
        and response["customer_quote_eligible"] is False,
        "controlled API captures authenticated scope evidence without cost-completeness or quote authority",
    )

    check(
        route_allowed("GET", "/air-cost-scope-reviews")
        and route_allowed("POST", "/air-rate-sources/source-1/cost-scope-reviews"),
        "pilot access admits only bounded air cost-scope review surfaces",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_cost_scope_review_service.py").read_text(encoding="utf-8")
    check(
        "Air Cost Scope Requirements Review" in js
        and "Cost Scope Review Kaydet" in js
        and '"unresolved","Unresolved"' in js
        and "Her dokuz kategori tam olarak bir kez sınıflandırılır" in js
        and "cost completeness" in js.casefold()
        and "openai" not in service.casefold(),
        "browser defaults scope to unresolved and explains that classification is not cost completeness",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_cost_scope_review_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir cost-scope review regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
