from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.core.air_additional_cost_evidence_repository import InMemoryAirAdditionalCostEvidenceRepository
from src.core.air_cost_scope_coverage_preview import (
    AirCostScopeCoveragePreviewError,
    build_air_cost_scope_coverage_preview,
)
from src.core.air_cost_scope_review_repository import InMemoryAirCostScopeReviewRepository
from src.core.air_fx_rate_evidence_repository import InMemoryAirFxRateEvidenceRepository
from src.core.pilot_access import route_allowed
from src.simulation.air_additional_cost_consumption_regressions import _simple_surcharges
from src.simulation.air_additional_cost_evidence_regressions import _record as _record_additional
from src.simulation.air_cost_scope_review_regressions import _record as _record_scope, _requirements
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import _source_repo


INQUIRY = "AIR-INQ-P238-001"


def _coverage(*, scope_repo, scope_id, additional_repo, additional_ids=None, inquiry=INQUIRY, **extra):
    return build_air_cost_scope_coverage_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        cost_scope_review_id=scope_id,
        inquiry_reference=inquiry,
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_simple_surcharges(),
        source_repository=_source_repo(),
        scope_repository=scope_repo,
        additional_cost_repository=additional_repo,
        additional_cost_evidence_ids=additional_ids,
        **extra,
    )


def evaluate_air_cost_scope_coverage_preview_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    scope_repo = InMemoryAirCostScopeReviewRepository()
    scope, _ = _record_scope(
        scope_repo,
        source_repo,
        entry_id="air-cost-scope-p238-main",
        inquiry_reference=INQUIRY,
        requirements=_requirements(required=("pickup", "delivery")),
    )
    additional_repo = InMemoryAirAdditionalCostEvidenceRepository()
    pickup, _ = _record_additional(
        additional_repo,
        source_repo,
        entry_id="air-cost-p238-pickup",
        inquiry_reference=INQUIRY,
        cost_category="pickup",
        amount=Decimal("80"),
        currency="USD",
        quantity_basis="per_shipment",
    )
    delivery, _ = _record_additional(
        additional_repo,
        source_repo,
        entry_id="air-cost-p238-delivery",
        inquiry_reference=INQUIRY,
        cost_category="delivery",
        amount=Decimal("120"),
        currency="USD",
        quantity_basis="per_shipment",
    )

    partial = _coverage(
        scope_repo=scope_repo,
        scope_id=scope.review_id,
        additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id],
        shipment_count=1,
    )
    check(
        partial.scope_classification_complete is True
        and partial.required_flat_cost_coverage_complete is False
        and partial.covered_required_categories == ["pickup"]
        and partial.missing_required_categories == ["delivery"]
        and partial.blockers == ["required_cost_missing:delivery"],
        "complete scope classification still exposes a missing required local-cost category",
    )
    check(
        partial.cost_preview.reviewed_additional_cost_total == Decimal("80")
        and partial.cost_preview.all_in_cost is False
        and partial.all_in_cost is False
        and partial.customer_quote_eligible is False
        and partial.pricing_authority is False
        and partial.runtime_authoritative is False,
        "coverage preview preserves P2-36 subtotal while withholding all-in and pricing authority",
    )

    complete = _coverage(
        scope_repo=scope_repo,
        scope_id=scope.review_id,
        additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id],
        shipment_count=1,
    )
    check(
        complete.required_flat_cost_coverage_complete is True
        and complete.missing_required_categories == []
        and complete.conflicting_not_applicable_categories == []
        and complete.blockers == []
        and complete.cost_preview.reviewed_additional_cost_total == Decimal("200")
        and complete.cost_preview.base_plus_reviewed_surcharges_and_additional_costs == Decimal("943.50")
        and complete.unsupported_cost_semantics_still_possible is True
        and complete.all_in_cost is False,
        "all required flat categories can be covered without making the subtotal all-in",
    )

    unselected = _coverage(
        scope_repo=scope_repo,
        scope_id=scope.review_id,
        additional_repo=additional_repo,
        additional_ids=[],
    )
    check(
        set(unselected.missing_required_categories) == {"pickup", "delivery"}
        and unselected.selected_additional_cost_categories == []
        and unselected.required_flat_cost_coverage_complete is False,
        "stored but unselected local-cost evidence never satisfies required scope coverage",
    )

    unresolved_repo = InMemoryAirCostScopeReviewRepository()
    unresolved, _ = _record_scope(
        unresolved_repo,
        source_repo,
        entry_id="air-cost-scope-p238-unresolved",
        inquiry_reference=INQUIRY,
        requirements=_requirements(unresolved="destination_terminal", required=("pickup",)),
    )
    unresolved_result = _coverage(
        scope_repo=unresolved_repo,
        scope_id=unresolved.review_id,
        additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id],
        shipment_count=1,
    )
    check(
        unresolved_result.scope_classification_complete is False
        and unresolved_result.required_flat_cost_coverage_complete is False
        and "scope_classification_incomplete" in unresolved_result.blockers
        and unresolved_result.unresolved_categories == ["destination_terminal"],
        "unresolved scope blocks required-flat-cost coverage completeness even when known required cost is selected",
    )

    conflict_repo = InMemoryAirCostScopeReviewRepository()
    conflict_scope, _ = _record_scope(
        conflict_repo,
        source_repo,
        entry_id="air-cost-scope-p238-conflict",
        inquiry_reference=INQUIRY,
        requirements=_requirements(required=("pickup",)),
    )
    conflict = _coverage(
        scope_repo=conflict_repo,
        scope_id=conflict_scope.review_id,
        additional_repo=additional_repo,
        additional_ids=[pickup.evidence_id, delivery.evidence_id],
        shipment_count=1,
    )
    check(
        conflict.conflicting_not_applicable_categories == ["delivery"]
        and "selected_cost_conflicts_with_not_applicable:delivery" in conflict.blockers
        and conflict.required_flat_cost_coverage_complete is False,
        "selected cost evidence conflicts visibly with a not-applicable scope classification",
    )

    wrong_inquiry = False
    try:
        _coverage(
            scope_repo=scope_repo,
            scope_id=scope.review_id,
            additional_repo=additional_repo,
            inquiry="AIR-INQ-P238-OTHER",
        )
    except AirCostScopeCoveragePreviewError as exc:
        wrong_inquiry = str(exc) == "air_cost_scope_review_inquiry_mismatch"
    check(wrong_inquiry, "cost-scope coverage never reuses a review across inquiries")

    wrong_scope_repo = InMemoryAirCostScopeReviewRepository()
    wrong_scope = scope.model_copy(update={
        "review_id": "p238-wrong-source-scope",
        "entry_id": "p238-wrong-source-scope",
        "source_sha256": "8" * 64,
    })
    wrong_scope_repo.create(wrong_scope)
    wrong_source = False
    try:
        _coverage(
            scope_repo=wrong_scope_repo,
            scope_id=wrong_scope.review_id,
            additional_repo=additional_repo,
        )
    except AirCostScopeCoveragePreviewError as exc:
        wrong_source = str(exc) == "air_cost_scope_review_source_mismatch"
    check(wrong_source, "cost-scope coverage never crosses immutable tariff source SHA boundaries")

    missing_scope = False
    try:
        _coverage(
            scope_repo=scope_repo,
            scope_id="missing-scope-review",
            additional_repo=additional_repo,
        )
    except AirCostScopeCoveragePreviewError as exc:
        missing_scope = str(exc) == "air_cost_scope_review_not_found"
    check(missing_scope, "coverage gate requires an explicitly selected existing scope review")

    doc, _ = _record_additional(
        additional_repo,
        source_repo,
        entry_id="air-cost-p238-doc",
        inquiry_reference=INQUIRY,
        cost_category="documentation",
        amount=Decimal("30"),
        currency="USD",
        quantity_basis="per_awb",
    )
    count_blocked = False
    try:
        _coverage(
            scope_repo=scope_repo,
            scope_id=scope.review_id,
            additional_repo=additional_repo,
            additional_ids=[doc.evidence_id],
        )
    except AirCostScopeCoveragePreviewError as exc:
        count_blocked = str(exc).startswith("additional_cost_count_required:per_awb:")
    check(
        count_blocked,
        "coverage counts only evidence that P2-36 can actually consume with matching quantity context",
    )

    from src import api
    originals = (
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_shadow_repository,
        api.air_cost_scope_review_repository,
        api.air_additional_cost_evidence_repository,
        api.air_fx_rate_evidence_repository,
    )
    try:
        api.air_rate_table_review_repository = _table_repo()
        api.air_rate_structure_review_repository = _structure_repo()
        api.air_rate_surcharge_review_repository = _simple_surcharges()
        api.air_shadow_repository = source_repo
        api.air_cost_scope_review_repository = scope_repo
        api.air_additional_cost_evidence_repository = additional_repo
        api.air_fx_rate_evidence_repository = InMemoryAirFxRateEvidenceRepository()
        response = api.preview_air_cost_scope_coverage(
            "table-review-0001",
            "table-row-fra-0001",
            api.AirCostScopeCoveragePreviewRequest(
                cost_scope_review_id=scope.review_id,
                inquiry_reference=INQUIRY,
                actual_weight_kg=287,
                volumetric_weight_kg=250,
                cargo_context="general_cargo",
                routing_context="direct",
                additional_cost_evidence_ids=[pickup.evidence_id, delivery.evidence_id],
                shipment_count=1,
            ),
        )
    finally:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
            api.air_cost_scope_review_repository,
            api.air_additional_cost_evidence_repository,
            api.air_fx_rate_evidence_repository,
        ) = originals
    check(
        response["required_flat_cost_coverage_complete"] is True
        and response["missing_required_categories"] == []
        and response["all_in_cost"] is False
        and response["customer_quote_eligible"] is False
        and response["pricing_authority"] is False
        and response["runtime_authoritative"] is False,
        "controlled API exposes bounded flat-cost coverage without customer-pricing authority",
    )

    check(
        route_allowed(
            "POST",
            "/air-rate-table-reviews/review-1/rows/row-1/cost-scope-coverage-preview",
        ),
        "pilot access admits the bounded cost-scope coverage preview route",
    )

    root = Path(__file__).resolve().parents[2]
    ui = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_cost_scope_coverage_preview.py").read_text(encoding="utf-8")
    check(
        "Required Flat Local-Cost Coverage" in ui
        and "Required Local-Cost Coverage Kontrol Et" in ui
        and "Explicit scope review seç" in ui
        and "ALL-IN DEĞİL" in ui
        and "required_flat_cost_coverage_complete" in ui,
        "browser makes explicit scope selection and non-all-in coverage semantics visible",
    )
    check(
        "insert_once" not in service
        and ".create(" not in service
        and "save(" not in service
        and "openai" not in service.casefold(),
        "cost-scope coverage remains deterministic ephemeral calculation with no persistence or AI path",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_cost_scope_coverage_preview_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir cost-scope coverage preview regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
