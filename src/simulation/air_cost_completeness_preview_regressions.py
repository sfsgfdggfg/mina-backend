from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from starlette.requests import Request

from src.core.air_additional_cost_evidence_repository import InMemoryAirAdditionalCostEvidenceRepository
from src.core.air_cost_completeness_preview import AirCostCompletenessPreviewError, build_air_cost_completeness_preview
from src.core.air_cost_scope_review_repository import InMemoryAirCostScopeReviewRepository
from src.core.air_rate_weight_rounding_review import AirRateWeightRoundingReview
from src.core.air_rate_weight_rounding_review_repository import InMemoryAirRateWeightRoundingReviewRepository
from src.core.air_unsupported_cost_semantics_review import AIR_UNSUPPORTED_COST_SEMANTICS
from src.core.air_unsupported_cost_semantics_review_repository import (
    InMemoryAirUnsupportedCostSemanticsReviewRepository,
    SQLiteAirUnsupportedCostSemanticsReviewRepository,
)
from src.core.air_unsupported_cost_semantics_review_service import (
    AirUnsupportedCostSemanticsReviewTransitionError,
    record_air_unsupported_cost_semantics_review,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import PERSISTENT_STATE_NAMESPACES, SQLitePilotStore
from src.simulation.air_additional_cost_consumption_regressions import _simple_surcharges
from src.simulation.air_additional_cost_evidence_regressions import _record as _record_additional
from src.simulation.air_cost_scope_review_regressions import _record as _record_scope, _requirements as _scope_requirements
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import _candidate, _source_repo, _surcharge_repo


NOW = datetime(2026, 9, 14, 10, 30, tzinfo=timezone.utc)
INQUIRY = "AIR-INQ-P239-001"


def _semantic_requirements(*, applicable: str | None = None, unresolved: str | None = None):
    result = []
    for semantic in AIR_UNSUPPORTED_COST_SEMANTICS:
        status = "not_applicable"
        if semantic == applicable:
            status = "applicable_unresolved"
        if semantic == unresolved:
            status = "unresolved"
        result.append({"semantic": semantic, "status": status, "rationale": f"{semantic} explicitly reviewed for this inquiry."})
    return result


def _record_semantics(repo, source_repo, **overrides):
    payload = {
        "source_id": "source-0001",
        "entry_id": "air-unsupported-cost-p239",
        "inquiry_reference": INQUIRY,
        "requirements": _semantic_requirements(),
        "review_note": "All non-flat/unmodeled commercial cost semantics reviewed explicitly.",
        "reviewed_by": "Senior Air Operator",
        "reviewed_at": NOW,
        "source_repository": source_repo,
        "repository": repo,
    }
    payload.update(overrides)
    return record_air_unsupported_cost_semantics_review(**payload)


def _rounding_repo():
    repo = InMemoryAirRateWeightRoundingReviewRepository()
    repo.create(AirRateWeightRoundingReview(
        source_id="source-0001",
        source_sha256="a" * 64,
        rounding_mode="none",
        increment_kg=None,
        reviewed_by="Senior Air Operator",
        reviewed_at=NOW,
        review_note="Exact source confirms no chargeable-weight rounding.",
    ))
    return repo


def _setup(required=("pickup", "delivery")):
    source_repo = _source_repo()
    scope_repo = InMemoryAirCostScopeReviewRepository()
    scope, _ = _record_scope(
        scope_repo, source_repo, entry_id="air-scope-p239", inquiry_reference=INQUIRY,
        requirements=_scope_requirements(required=required),
    )
    semantics_repo = InMemoryAirUnsupportedCostSemanticsReviewRepository()
    semantics, _ = _record_semantics(semantics_repo, source_repo)
    additional_repo = InMemoryAirAdditionalCostEvidenceRepository()
    pickup, _ = _record_additional(
        additional_repo, source_repo, entry_id="air-p239-pickup", inquiry_reference=INQUIRY,
        cost_category="pickup", amount=Decimal("80"), currency="USD", quantity_basis="per_shipment",
    )
    delivery, _ = _record_additional(
        additional_repo, source_repo, entry_id="air-p239-delivery", inquiry_reference=INQUIRY,
        cost_category="delivery", amount=Decimal("120"), currency="USD", quantity_basis="per_shipment",
    )
    return source_repo, scope_repo, scope, semantics_repo, semantics, additional_repo, pickup, delivery


def _preview(*, source_repo, scope_repo, scope, semantics_repo, semantics, additional_repo,
             additional_ids, rounding_repo=None, surcharge_repo=None, inquiry=INQUIRY):
    return build_air_cost_completeness_preview(
        review_id="table-review-0001", candidate_id="table-row-fra-0001",
        cost_scope_review_id=scope.review_id,
        unsupported_cost_semantics_review_id=semantics.review_id,
        inquiry_reference=inquiry, actual_weight_kg=287, volumetric_weight_kg=250,
        cargo_context="general_cargo", routing_context="direct", shipment_count=1,
        table_repository=_table_repo(), structure_repository=_structure_repo(),
        surcharge_repository=surcharge_repo or _simple_surcharges(), source_repository=source_repo,
        scope_repository=scope_repo, unsupported_semantics_repository=semantics_repo,
        additional_cost_repository=additional_repo, additional_cost_evidence_ids=additional_ids,
        rounding_repository=rounding_repo or _rounding_repo(),
    )


def evaluate_air_cost_completeness_preview_regressions() -> dict:
    passes, failures = [], []
    def check(condition, label): (passes if condition else failures).append(label)

    source_repo, scope_repo, scope, semantics_repo, semantics, additional_repo, pickup, delivery = _setup()

    complete = _preview(
        source_repo=source_repo, scope_repo=scope_repo, scope=scope,
        semantics_repo=semantics_repo, semantics=semantics, additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id],
    )
    check(
        complete.cost_completeness_confirmed is True
        and complete.coverage_preview.required_flat_cost_coverage_complete is True
        and complete.unsupported_semantics_cleared is True
        and complete.blocking_surcharge_exclusions == []
        and complete.airline_weight_rounding_reviewed is True
        and complete.blockers == []
        and complete.confirmed_cost_basis_amount == Decimal("943.50")
        and complete.confirmed_cost_basis_currency == "USD",
        "flat coverage plus cleared unsupported semantics and reviewed rounding can confirm bounded cost completeness",
    )
    check(
        complete.all_in_cost is False and complete.customer_quote_eligible is False
        and complete.pricing_authority is False and complete.quote_send_authority is False
        and complete.booking_authority is False and complete.outbound_authority is False
        and complete.runtime_authoritative is False,
        "cost completeness confirmation creates no customer-pricing quote-send booking or runtime authority",
    )

    partial = _preview(
        source_repo=source_repo, scope_repo=scope_repo, scope=scope,
        semantics_repo=semantics_repo, semantics=semantics, additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id],
    )
    check(
        partial.cost_completeness_confirmed is False
        and "required_cost_missing:delivery" in partial.blockers
        and partial.confirmed_cost_basis_amount is None,
        "missing required flat coverage blocks cost completeness",
    )

    no_rounding = _preview(
        source_repo=source_repo, scope_repo=scope_repo, scope=scope,
        semantics_repo=semantics_repo, semantics=semantics, additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id],
        rounding_repo=InMemoryAirRateWeightRoundingReviewRepository(),
    )
    check(
        no_rounding.cost_completeness_confirmed is False
        and no_rounding.airline_weight_rounding_reviewed is False
        and "airline_weight_rounding_unreviewed" in no_rounding.blockers,
        "missing exact-source airline weight-rounding review blocks cost completeness",
    )

    applicable_repo = InMemoryAirUnsupportedCostSemanticsReviewRepository()
    applicable, _ = _record_semantics(
        applicable_repo, source_repo, entry_id="air-unsupported-cost-applicable",
        requirements=_semantic_requirements(applicable="customs_duties_taxes"),
    )
    applicable_result = _preview(
        source_repo=source_repo, scope_repo=scope_repo, scope=scope,
        semantics_repo=applicable_repo, semantics=applicable, additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id],
    )
    check(
        applicable_result.cost_completeness_confirmed is False
        and applicable_result.applicable_unresolved_semantics == ["customs_duties_taxes"]
        and "unsupported_cost_semantic_applicable_unresolved:customs_duties_taxes" in applicable_result.blockers,
        "applicable unresolved duty-tax or other unmodeled cost semantics block completeness",
    )

    unresolved_repo = InMemoryAirUnsupportedCostSemanticsReviewRepository()
    unresolved, _ = _record_semantics(
        unresolved_repo, source_repo, entry_id="air-unsupported-cost-unresolved",
        requirements=_semantic_requirements(unresolved="percentage_additional_cost"),
    )
    unresolved_result = _preview(
        source_repo=source_repo, scope_repo=scope_repo, scope=scope,
        semantics_repo=unresolved_repo, semantics=unresolved, additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id],
    )
    check(
        unresolved_result.semantics_classification_complete is False
        and unresolved_result.cost_completeness_confirmed is False
        and "unsupported_cost_semantics_classification_incomplete" in unresolved_result.blockers,
        "unresolved unsupported-cost semantic classification blocks completeness",
    )

    cross_currency_surcharge = _surcharge_repo(
        _candidate("fx-p239-000001", "XCC", "0.25", currency="EUR", application_basis="chargeable_weight")
    )
    surcharge_blocked = _preview(
        source_repo=source_repo, scope_repo=scope_repo, scope=scope,
        semantics_repo=semantics_repo, semantics=semantics, additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id], surcharge_repo=cross_currency_surcharge,
    )
    check(
        surcharge_blocked.cost_completeness_confirmed is False
        and len(surcharge_blocked.blocking_surcharge_exclusions) == 1
        and surcharge_blocked.blocking_surcharge_exclusions[0].reason == "currency_mismatch_no_fx"
        and any(item.startswith("surcharge_cost_unresolved:") for item in surcharge_blocked.blockers),
        "unresolved surcharge exclusion such as missing FX blocks cost completeness",
    )

    non_applicable_surcharge = _surcharge_repo(
        _candidate(
            "dest-p239-00001", "DEST", "0.25", applicability_scope="destination_specific",
            destination_code="MUC", application_basis="chargeable_weight",
        )
    )
    non_applicable_ok = _preview(
        source_repo=source_repo, scope_repo=scope_repo, scope=scope,
        semantics_repo=semantics_repo, semantics=semantics, additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id], surcharge_repo=non_applicable_surcharge,
    )
    check(
        non_applicable_ok.cost_completeness_confirmed is True
        and len(non_applicable_ok.non_applicable_surcharge_exclusions) == 1
        and non_applicable_ok.blocking_surcharge_exclusions == [],
        "destination cargo or routing non-applicable surcharge exclusions do not block completeness",
    )

    wrong_inquiry = False
    try:
        _preview(
            source_repo=source_repo, scope_repo=scope_repo, scope=scope,
            semantics_repo=semantics_repo, semantics=semantics, additional_repo=additional_repo,
            additional_ids=[], inquiry="AIR-INQ-P239-OTHER",
        )
    except AirCostCompletenessPreviewError as exc:
        wrong_inquiry = str(exc) in {"air_cost_scope_review_inquiry_mismatch", "air_unsupported_cost_semantics_review_inquiry_mismatch"}
    check(wrong_inquiry, "cost completeness never reuses scope or semantic review across inquiries")

    identical, created_again = _record_semantics(semantics_repo, source_repo)
    check(created_again is False and identical.review_id == semantics.review_id,
          "unsupported-cost review entry identity is idempotent for identical evidence")
    conflict = False
    try:
        _record_semantics(semantics_repo, source_repo, requirements=_semantic_requirements(applicable="other_unmodeled_cost"))
    except AirUnsupportedCostSemanticsReviewTransitionError:
        conflict = True
    check(conflict, "unsupported-cost review entry identity fails closed when evidence changes")

    with TemporaryDirectory() as tmp:
        repo = SQLiteAirUnsupportedCostSemanticsReviewRepository(SQLitePilotStore(Path(tmp)/"pilot.sqlite3"))
        persisted, _ = _record_semantics(repo, source_repo, entry_id="air-unsupported-cost-sqlite")
        restored = SQLiteAirUnsupportedCostSemanticsReviewRepository(repo.store).get(persisted.review_id)
        check(restored is not None and restored.unsupported_semantics_cleared is True,
              "unsupported-cost semantics review survives SQLite reconstruction")
    check(
        "air_unsupported_cost_semantics_reviews" in PERSISTENT_STATE_NAMESPACES
        and "air_unsupported_cost_semantics_review_by_entry" in PERSISTENT_STATE_NAMESPACES,
        "unsupported-cost semantics review is protected from ordinary retention purge",
    )

    from src import api
    request = Request({"type":"http","method":"POST","path":"/","headers":[]});request.state.pilot_operator="API Air Cost Operator"
    api_sem_repo = InMemoryAirUnsupportedCostSemanticsReviewRepository()
    originals=(api.air_shadow_repository,api.air_unsupported_cost_semantics_review_repository)
    try:
        api.air_shadow_repository=source_repo;api.air_unsupported_cost_semantics_review_repository=api_sem_repo
        response=api.create_air_unsupported_cost_semantics_review(
            "source-0001",
            api.AirUnsupportedCostSemanticsReviewRequest(
                entry_id="air-unsupported-api", inquiry_reference=INQUIRY,
                requirements=[api.AirUnsupportedCostSemanticRequirementRequest(**x) for x in _semantic_requirements()],
                review_note="API review checks all unsupported cost semantics explicitly.",
            ),request,
        )
    finally:
        api.air_shadow_repository,api.air_unsupported_cost_semantics_review_repository=originals
    check(
        response["created"] is True and response["unsupported_semantics_cleared"] is True
        and response["pricing_authority_enabled"] is False and response["customer_quote_eligible"] is False,
        "controlled API captures authenticated unsupported-cost review without pricing authority",
    )

    api_originals = (
        api.air_rate_table_review_repository, api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository, api.air_shadow_repository,
        api.air_cost_scope_review_repository, api.air_unsupported_cost_semantics_review_repository,
        api.air_additional_cost_evidence_repository, api.air_rate_weight_rounding_review_repository,
    )
    try:
        api.air_rate_table_review_repository=_table_repo()
        api.air_rate_structure_review_repository=_structure_repo()
        api.air_rate_surcharge_review_repository=_simple_surcharges()
        api.air_shadow_repository=source_repo
        api.air_cost_scope_review_repository=scope_repo
        api.air_unsupported_cost_semantics_review_repository=semantics_repo
        api.air_additional_cost_evidence_repository=additional_repo
        api.air_rate_weight_rounding_review_repository=_rounding_repo()
        completeness_response=api.preview_air_cost_completeness(
            "table-review-0001", "table-row-fra-0001",
            api.AirCostCompletenessPreviewRequest(
                cost_scope_review_id=scope.review_id,
                unsupported_cost_semantics_review_id=semantics.review_id,
                inquiry_reference=INQUIRY, actual_weight_kg=287, volumetric_weight_kg=250,
                cargo_context="general_cargo", routing_context="direct", shipment_count=1,
                additional_cost_evidence_ids=[pickup.evidence_id,delivery.evidence_id],
            ),
        )
    finally:
        (api.air_rate_table_review_repository,api.air_rate_structure_review_repository,
         api.air_rate_surcharge_review_repository,api.air_shadow_repository,
         api.air_cost_scope_review_repository,api.air_unsupported_cost_semantics_review_repository,
         api.air_additional_cost_evidence_repository,api.air_rate_weight_rounding_review_repository)=api_originals
    check(
        completeness_response["cost_completeness_confirmed"] is True
        and completeness_response["confirmed_cost_basis_amount"] == "943.500"
        and completeness_response["customer_quote_eligible"] is False
        and completeness_response["all_in_cost"] is False,
        "controlled API confirms bounded cost basis without customer-price or all-in authority",
    )

    check(
        route_allowed("GET","/air-unsupported-cost-semantics-reviews")
        and route_allowed("POST","/air-rate-sources/source-1/unsupported-cost-semantics-reviews")
        and route_allowed("POST","/air-rate-table-reviews/review-1/rows/row-1/cost-completeness-preview"),
        "pilot access admits only bounded P2-39 review and completeness surfaces",
    )

    root=Path(__file__).resolve().parents[2]
    ui=(root/"ui/web_shell/app.js").read_text(encoding="utf-8")
    service=(root/"src/core/air_cost_completeness_preview.py").read_text(encoding="utf-8")
    check(
        "Unsupported Cost Semantics Review" in ui and "Cost Completeness Kontrol Et" in ui
        and "Applicable / unresolved" in ui and "Customer price authority YOK" in ui,
        "browser exposes explicit unsupported-cost review and bounded completeness confirmation",
    )
    check(
        "insert_once" not in service and ".create(" not in service and "save(" not in service
        and "openai" not in service.casefold(),
        "cost completeness confirmation remains deterministic ephemeral calculation without writes or AI",
    )

    return {"passed":not failures,"passes":passes,"failures":failures}


if __name__ == "__main__":
    result=evaluate_air_cost_completeness_preview_regressions()
    for label in result["passes"]: print(f"PASS {label}")
    for label in result["failures"]: print(f"FAIL {label}")
    print("\nAir cost completeness preview regressions: "+("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
