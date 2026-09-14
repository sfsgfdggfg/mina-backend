from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from starlette.requests import Request

from src.core.air_fx_rate_evidence import AirFxRateEvidence
from src.core.air_fx_rate_evidence_repository import InMemoryAirFxRateEvidenceRepository
from src.core.air_reviewed_surcharge_cost_preview import (
    AirReviewedSurchargeCostPreviewError,
    build_air_reviewed_surcharge_cost_preview,
)
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo
from src.simulation.air_fx_rate_evidence_regressions import EFFECTIVE, _record
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import (
    _candidate,
    _source_repo,
    _standard_repo,
    _surcharge_repo,
)

NOW = datetime(2026, 9, 13, 12, 30, tzinfo=timezone.utc)

def _preview(*, fx_repo=None, fx_ids=None, inquiry=None, fx_reference_at=None, surcharges=None, **extra):
    return build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=surcharges or _standard_repo(),
        source_repository=_source_repo(),
        fx_repository=fx_repo,
        fx_evidence_ids=fx_ids,
        inquiry_reference=inquiry,
        fx_reference_at=fx_reference_at,
        **extra,
    )


def evaluate_air_fx_consumption_preview_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    fx_repo = InMemoryAirFxRateEvidenceRepository()
    fx, _ = _record(fx_repo, source_repo)

    unselected = _preview(fx_repo=fx_repo)
    reasons = {(x.surcharge_code, x.reason) for x in unselected.excluded_surcharges}
    check(
        ("SSC", "currency_mismatch_no_fx") in reasons
        and unselected.fx_applied is False
        and unselected.fx_evidence_ids_used == [],
        "stored FX evidence is never auto-selected by the reviewed surcharge preview",
    )

    converted = _preview(
        fx_repo=fx_repo,
        fx_ids=[fx.evidence_id],
        inquiry=fx.inquiry_reference,
        fx_reference_at=fx.effective_at,
    )
    ssc = next(x for x in converted.included_surcharges if x.surcharge_code == "SSC")
    check(
        converted.fx_applied is True
        and converted.fx_evidence_ids_used == [fx.evidence_id]
        and ssc.source_currency == "EUR"
        and ssc.currency == "USD",
        "explicit matching directional FX evidence converts only the selected cross-currency surcharge",
    )
    check(
        ssc.source_rate_per_kg == Decimal("0.20")
        and ssc.source_surcharge_cost == Decimal("57.40")
        and ssc.fx_rate == Decimal("1.10")
        and ssc.rate_per_kg == Decimal("0.220")
        and ssc.surcharge_cost == Decimal("63.1400")
        and converted.reviewed_per_kg_surcharge_total == Decimal("236.6400")
        and converted.base_plus_reviewed_per_kg_surcharges == Decimal("836.6400")
        and converted.surcharge_rounding_applied is False,
        "FX conversion preserves source values and applies no hidden surcharge rounding",
    )

    missing_context_blocked = False
    try:
        _preview(fx_repo=fx_repo, fx_ids=[fx.evidence_id])
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_context_blocked = str(exc) == "inquiry_reference_required_for_fx"
    check(
        missing_context_blocked,
        "explicit FX selection requires inquiry reference instead of borrowing shipment context",
    )

    wrong_inquiry_blocked = False
    try:
        _preview(
            fx_repo=fx_repo, fx_ids=[fx.evidence_id], inquiry="MINA2026/OTHER",
            fx_reference_at=fx.effective_at,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        wrong_inquiry_blocked = str(exc).startswith("air_fx_evidence_inquiry_mismatch:")
    check(wrong_inquiry_blocked, "FX evidence cannot cross inquiry boundaries")

    wrong_time_blocked = False
    try:
        _preview(
            fx_repo=fx_repo, fx_ids=[fx.evidence_id], inquiry=fx.inquiry_reference,
            fx_reference_at=fx.effective_at + timedelta(minutes=1),
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        wrong_time_blocked = str(exc).startswith("air_fx_evidence_timestamp_mismatch:")
    check(wrong_time_blocked, "FX evidence effective timestamp must match the explicit preview reference instant")

    inverse_repo = InMemoryAirFxRateEvidenceRepository()
    inverse, _ = _record(
        inverse_repo, source_repo,
        entry_id="fx-inverse-0001",
        base_currency="USD", quote_currency="EUR", rate=Decimal("0.91"),
    )
    inverse_blocked = False
    try:
        _preview(
            fx_repo=inverse_repo, fx_ids=[inverse.evidence_id], inquiry=inverse.inquiry_reference,
            fx_reference_at=inverse.effective_at,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        inverse_blocked = str(exc).startswith("unused_fx_evidence:")
    check(inverse_blocked, "inverse FX evidence is never inverted or silently substituted")

    missing_time_blocked = False
    try:
        _preview(
            fx_repo=fx_repo,
            fx_ids=[fx.evidence_id],
            inquiry=fx.inquiry_reference,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_time_blocked = str(exc) == "fx_reference_at_required"
    check(
        missing_time_blocked,
        "explicit FX selection requires an explicit reference timestamp",
    )

    duplicate_blocked = False
    try:
        _preview(
            fx_repo=fx_repo,
            fx_ids=[fx.evidence_id, fx.evidence_id],
            inquiry=fx.inquiry_reference,
            fx_reference_at=fx.effective_at,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        duplicate_blocked = str(exc) == "duplicate_fx_evidence_id"
    check(duplicate_blocked, "duplicate FX evidence ids fail closed")

    from src import api
    originals = (
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_shadow_repository,
        api.air_fx_rate_evidence_repository,
    )
    try:
        api.air_rate_table_review_repository = _table_repo()
        api.air_rate_structure_review_repository = _structure_repo()
        api.air_rate_surcharge_review_repository = _standard_repo()
        api.air_shadow_repository = source_repo
        api.air_fx_rate_evidence_repository = fx_repo
        response = api.preview_air_reviewed_surcharge_cost(
            "table-review-0001",
            "table-row-fra-0001",
            api.AirReviewedSurchargeCostPreviewRequest(
                actual_weight_kg=287,
                volumetric_weight_kg=250,
                cargo_context="general_cargo",
                routing_context="direct",
                inquiry_reference=fx.inquiry_reference,
                fx_evidence_ids=[fx.evidence_id],
                fx_reference_at=fx.effective_at,
            ),
        )
    finally:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
            api.air_fx_rate_evidence_repository,
        ) = originals
    check(
        response["fx_applied"] is True
        and response["fx_evidence_ids_used"] == [fx.evidence_id]
        and response["all_in_cost"] is False
        and response["customer_quote_eligible"] is False,
        "controlled API consumes only explicit selected FX evidence without quote authority",
    )

    root = Path(__file__).resolve().parents[2]
    js = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "Kullanılacak FX evidence" in js
        and "FX inquiry reference" in js
        and "FX reference timestamp" in js
        and "currency_mismatch_no_fx" in js,
        "browser exposes explicit FX evidence selection and reference context",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_fx_consumption_preview_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir FX consumption preview regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
