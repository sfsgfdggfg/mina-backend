from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from src.core.air_rate_surcharge_review import AirRateSurchargeCandidate, AirRateSurchargeReview
from src.core.air_rate_surcharge_review_repository import InMemoryAirRateSurchargeReviewRepository
from src.core.air_reviewed_surcharge_cost_preview import (
    AirReviewedSurchargeCostPreviewError,
    build_air_reviewed_surcharge_cost_preview,
)
from src.core.air_shadow import AirRateSource
from src.core.air_shadow_repository import InMemoryAirShadowRepository
from src.core.pilot_access import route_allowed
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo


NOW = datetime(2026, 9, 13, 9, 45, tzinfo=timezone.utc)


def _source_repo(cargo_scope: str = "general_cargo") -> InMemoryAirShadowRepository:
    repo = InMemoryAirShadowRepository()
    repo.create_rate_source(AirRateSource(
        source_id="source-0001",
        entry_id="reviewed-surcharge-cost-source",
        airline_name="THY",
        document_name="reviewed-cost.pdf",
        sha256_hex="a" * 64,
        cargo_scope=cargo_scope,
        origin_airport="ADA",
        recorded_by="Air Operator",
        recorded_at=NOW,
    ))
    return repo


def _candidate(
    candidate_id: str,
    code: str,
    amount: str,
    *,
    currency: str = "USD",
    basis: str = "per_kg",
    application_basis: str = "chargeable_weight",
    applicability_scope: str = "source_wide",
    destination_code: str | None = None,
    cargo_applicability: str | None = "general_cargo",
    routing_applicability: str | None = "direct_only",
    routing_via_airport: str | None = None,
    flat_quantity_basis: str | None = None,
) -> AirRateSurchargeCandidate:
    kwargs = {
        "application_basis": application_basis,
        "application_basis_reviewed_by": "Senior Air Operator",
        "application_basis_reviewed_at": NOW,
        "application_basis_review_note": "Application basis verified.",
        "applicability_scope": applicability_scope,
        "applicability_destination_code": destination_code,
        "applicability_reviewed_by": "Senior Air Operator",
        "applicability_reviewed_at": NOW,
        "applicability_review_note": "Destination scope verified.",
    }
    if cargo_applicability is not None and routing_applicability is not None:
        kwargs.update({
            "cargo_applicability": cargo_applicability,
            "routing_applicability": routing_applicability,
            "routing_via_airport": routing_via_airport,
            "operational_conditions_reviewed_by": "Senior Air Operator",
            "operational_conditions_reviewed_at": NOW,
            "operational_conditions_review_note": "Cargo and routing conditions verified.",
        })
    if flat_quantity_basis is not None:
        kwargs.update({
            "flat_quantity_basis": flat_quantity_basis,
            "flat_quantity_basis_reviewed_by": "Senior Air Operator",
            "flat_quantity_basis_reviewed_at": NOW,
            "flat_quantity_basis_review_note": "Flat quantity basis verified.",
        })
    return AirRateSurchargeCandidate(
        candidate_id=candidate_id,
        surcharge_code=code,
        amount=amount,
        currency=currency,
        basis=basis,
        source_line_number=3,
        source_line_sha256=(candidate_id[0].lower() if candidate_id[0].lower() in "abcdef" else "a") * 64,
        status="confirmed",
        reviewed_by="Senior Air Operator",
        reviewed_at=NOW,
        review_note="Amount, currency and unit verified.",
        **kwargs,
    )


def _surcharge_repo(*candidates: AirRateSurchargeCandidate) -> InMemoryAirRateSurchargeReviewRepository:
    repo = InMemoryAirRateSurchargeReviewRepository()
    repo.create(AirRateSurchargeReview(
        review_id="surcharge-cost-review-001",
        source_id="source-0001",
        source_sha256="a" * 64,
        structure_review_id="structure-review-0001",
        extracted_text_sha256="b" * 64,
        candidates=list(candidates),
        status="completed",
        requested_by="Air Operator",
        created_at=NOW,
    ))
    return repo


def _standard_repo() -> InMemoryAirRateSurchargeReviewRepository:
    return _surcharge_repo(
        _candidate("fsc-cost-000001", "FSC", "0.50", application_basis="chargeable_weight"),
        _candidate("sec-cost-000001", "SECURITY", "0.10", application_basis="pivot_billed_weight", applicability_scope="destination_specific", destination_code="FRA"),
        _candidate("flat-cost-00001", "HANDLING", "25", basis="flat", application_basis="flat"),
        _candidate("eur-cost-000001", "SSC", "0.20", currency="EUR"),
        _candidate("muc-cost-000001", "AWB", "0.30", applicability_scope="destination_specific", destination_code="MUC"),
        _candidate("route-cost-0001", "SCREENING", "0.05", routing_applicability="connecting_only"),
    )


def evaluate_air_reviewed_surcharge_cost_preview_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    tables = _table_repo()
    structures = _structure_repo()
    sources = _source_repo()
    surcharges = _standard_repo()
    preview = build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=tables,
        structure_repository=structures,
        surcharge_repository=surcharges,
        source_repository=sources,
    )
    included = {item.surcharge_code: item for item in preview.included_surcharges}
    reasons = {(item.surcharge_code, item.reason) for item in preview.excluded_surcharges}
    check(
        preview.freight.recommended_base_freight == Decimal("600.00")
        and included["FSC"].applied_weight_kg == Decimal("287")
        and included["FSC"].surcharge_cost == Decimal("143.50")
        and included["SECURITY"].applied_weight_kg == Decimal("300")
        and included["SECURITY"].surcharge_cost == Decimal("30.00")
        and preview.reviewed_per_kg_surcharge_total == Decimal("173.50")
        and preview.base_plus_reviewed_per_kg_surcharges == Decimal("773.50"),
        "reviewed per-kg surcharge preview applies chargeable and pivot bases independently",
    )
    check(
        ("HANDLING", "flat_quantity_basis_unreviewed") in reasons
        and ("SSC", "currency_mismatch_no_fx") in reasons
        and ("AWB", "destination_not_applicable") in reasons
        and ("SCREENING", "routing_not_applicable") in reasons,
        "unreviewed flat cross-currency destination and routing exclusions stay explicit instead of being guessed",
    )
    check(
        preview.all_in_cost is False
        and preview.flat_surcharges_included is False
        and preview.fx_applied is False
        and preview.surcharge_rounding_applied is False
        and preview.capacity_confirmed is False
        and preview.tariff_validity_confirmed is False
        and preview.customer_quote_eligible is False
        and preview.runtime_authoritative is False,
        "reviewed surcharge cost preview remains partial reference evidence with no quote authority",
    )

    incomplete = _candidate(
        "incomplete-0001", "FSC", "0.50",
        cargo_applicability=None, routing_applicability=None,
    )
    incomplete_blocked = False
    try:
        build_air_reviewed_surcharge_cost_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=287, volumetric_weight_kg=250,
            cargo_context="general_cargo", routing_context="direct",
            table_repository=tables, structure_repository=structures,
            surcharge_repository=_surcharge_repo(incomplete), source_repository=sources,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        incomplete_blocked = str(exc) == "applicable_per_kg_surcharge_operational_conditions_incomplete"
    check(incomplete_blocked, "potentially applicable same-currency per-kg surcharge fails closed when review evidence is incomplete")

    via_candidate = _candidate(
        "via-cost-0000001", "FSC", "0.50",
        routing_applicability="via_airport", routing_via_airport="IST",
    )
    missing_via_blocked = False
    try:
        build_air_reviewed_surcharge_cost_preview(
            review_id="table-review-0001", candidate_id="table-row-fra-0001",
            actual_weight_kg=287, volumetric_weight_kg=250,
            cargo_context="general_cargo", routing_context="connecting",
            table_repository=tables, structure_repository=structures,
            surcharge_repository=_surcharge_repo(via_candidate), source_repository=sources,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_via_blocked = str(exc) == "via_airport_context_required_for_reviewed_surcharge"
    check(missing_via_blocked, "via-specific surcharge requires explicit connecting via context before calculation")

    from src import api
    originals = (
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_shadow_repository,
    )
    try:
        api.air_rate_table_review_repository = tables
        api.air_rate_structure_review_repository = structures
        api.air_rate_surcharge_review_repository = surcharges
        api.air_shadow_repository = sources
        response = api.preview_air_reviewed_surcharge_cost(
            "table-review-0001",
            "table-row-fra-0001",
            api.AirReviewedSurchargeCostPreviewRequest(
                actual_weight_kg=287,
                volumetric_weight_kg=250,
                cargo_context="general_cargo",
                routing_context="direct",
            ),
        )
    finally:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
        ) = originals
    check(
        Decimal(response["base_plus_reviewed_per_kg_surcharges"]) == Decimal("773.50")
        and response["all_in_cost"] is False
        and response["customer_quote_eligible"] is False,
        "controlled API exposes reviewed per-kg cost preview without all-in or customer-quote authority",
    )
    check(
        route_allowed("POST", "/air-rate-table-reviews/review-1/rows/row-1/reviewed-surcharge-cost-preview"),
        "pilot access admits bounded reviewed surcharge cost-preview route",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    service = (root / "src" / "core" / "air_reviewed_surcharge_cost_preview.py").read_text(encoding="utf-8")
    check(
        "Reviewed Surcharge Cost Preview" in js
        and "ALL-IN DEĞİL" in js
        and "ters veya otomatik FX yok" in js
        and "openai" not in service.casefold(),
        "browser labels reviewed surcharge preview as partial non-quote cost and service has no OpenAI dependency",
    )
    check(
        "save(" not in service and ".create(" not in service and "upsert" not in service,
        "reviewed surcharge cost preview remains ephemeral and introduces no persistence write path",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_reviewed_surcharge_cost_preview_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir reviewed surcharge cost preview regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
