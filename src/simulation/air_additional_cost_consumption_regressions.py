from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from src.core.air_additional_cost_evidence_repository import InMemoryAirAdditionalCostEvidenceRepository
from src.core.air_fx_rate_evidence_repository import InMemoryAirFxRateEvidenceRepository
from src.core.air_operational_readiness_preview import build_air_operational_readiness_preview
from src.core.air_service_availability_repository import InMemoryAirServiceAvailabilityRepository
from src.core.air_reviewed_surcharge_cost_preview import (
    AirReviewedSurchargeCostPreviewError,
    build_air_reviewed_surcharge_cost_preview,
)
from src.simulation.air_additional_cost_evidence_regressions import _record as _record_additional
from src.simulation.air_fx_rate_evidence_regressions import _record as _record_fx
from src.simulation.air_operational_readiness_preview_regressions import INQUIRY, SERVICE_DATE, _validity_repo
from src.simulation.air_service_availability_regressions import _record as _record_availability
from src.simulation.air_reviewed_surcharge_cost_preview_regressions import (
    _candidate,
    _source_repo,
    _surcharge_repo,
)
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo


def _simple_surcharges():
    return _surcharge_repo(
        _candidate(
            "fsc-local-cost-01",
            "FSC",
            "0.50",
            currency="USD",
            application_basis="chargeable_weight",
        )
    )


def _preview(*, additional_repo=None, additional_ids=None, fx_repo=None, fx_ids=None,
             inquiry=None, fx_reference_at=None, **extra):
    return build_air_reviewed_surcharge_cost_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_simple_surcharges(),
        source_repository=_source_repo(),
        additional_cost_repository=additional_repo,
        additional_cost_evidence_ids=additional_ids,
        fx_repository=fx_repo,
        fx_evidence_ids=fx_ids,
        inquiry_reference=inquiry,
        fx_reference_at=fx_reference_at,
        **extra,
    )


def evaluate_air_additional_cost_consumption_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    source_repo = _source_repo()
    additional_repo = InMemoryAirAdditionalCostEvidenceRepository()
    usd, _ = _record_additional(
        additional_repo,
        source_repo,
        entry_id="local-usd-001",
        inquiry_reference="AIR-INQ-LOCAL-001",
        cost_category="pickup",
        amount=Decimal("85.50"),
        currency="USD",
        quantity_basis="per_shipment",
    )

    unselected = _preview(additional_repo=additional_repo)
    check(
        unselected.reviewed_additional_cost_total == Decimal("0")
        and unselected.included_additional_costs == []
        and unselected.additional_cost_evidence_ids_used == []
        and unselected.base_plus_reviewed_surcharges_and_additional_costs
        == unselected.base_plus_reviewed_surcharges,
        "stored local-cost evidence is never auto-consumed by the reviewed cost preview",
    )

    selected = _preview(
        additional_repo=additional_repo,
        additional_ids=[usd.evidence_id],
        inquiry=usd.inquiry_reference,
        shipment_count=1,
    )
    component = selected.included_additional_costs[0]
    check(
        selected.additional_costs_included is True
        and selected.additional_cost_evidence_ids_used == [usd.evidence_id]
        and selected.reviewed_additional_cost_total == Decimal("85.50")
        and component.cost_category == "pickup"
        and component.provider_name == usd.provider_name
        and component.amount_per_unit == Decimal("85.50")
        and component.applied_count == 1
        and component.additional_cost == Decimal("85.50")
        and component.fx_evidence_id is None,
        "explicit same-currency local-cost evidence consumes only its reviewed flat quantity context",
    )
    check(
        selected.base_plus_reviewed_surcharges == Decimal("743.50")
        and selected.base_plus_reviewed_surcharges_and_additional_costs == Decimal("829.00")
        and selected.all_in_cost is False
        and selected.customer_quote_eligible is False
        and selected.runtime_authoritative is False,
        "selected local cost extends the partial subtotal without creating all-in or customer-pricing authority",
    )

    missing_inquiry = False
    try:
        _preview(
            additional_repo=additional_repo,
            additional_ids=[usd.evidence_id],
            shipment_count=1,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_inquiry = str(exc) == "inquiry_reference_required_for_additional_costs"
    check(missing_inquiry, "explicit local-cost selection requires inquiry context")

    wrong_inquiry = False
    try:
        _preview(
            additional_repo=additional_repo,
            additional_ids=[usd.evidence_id],
            inquiry="AIR-INQ-OTHER",
            shipment_count=1,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        wrong_inquiry = str(exc).startswith("air_additional_cost_evidence_inquiry_mismatch:")
    check(wrong_inquiry, "local-cost evidence cannot cross inquiry boundaries")

    wrong_source_repo = InMemoryAirAdditionalCostEvidenceRepository()
    wrong_source = usd.model_copy(update={
        "evidence_id": "wrong-source-local-cost",
        "entry_id": "wrong-source-local-cost",
        "source_sha256": "8" * 64,
    })
    wrong_source_repo.create(wrong_source)
    source_mismatch = False
    try:
        _preview(
            additional_repo=wrong_source_repo,
            additional_ids=[wrong_source.evidence_id],
            inquiry=wrong_source.inquiry_reference,
            shipment_count=1,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        source_mismatch = str(exc).startswith("air_additional_cost_evidence_source_mismatch:")
    check(source_mismatch, "local-cost evidence cannot cross immutable tariff source SHA boundaries")

    duplicate = False
    try:
        _preview(
            additional_repo=additional_repo,
            additional_ids=[usd.evidence_id, usd.evidence_id],
            inquiry=usd.inquiry_reference,
            shipment_count=1,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        duplicate = str(exc) == "duplicate_additional_cost_evidence_id"
    check(duplicate, "duplicate local-cost evidence ids fail closed")

    awb, _ = _record_additional(
        additional_repo,
        source_repo,
        entry_id="local-awb-001",
        inquiry_reference="AIR-INQ-AWB-001",
        cost_category="documentation",
        amount=Decimal("30"),
        currency="USD",
        quantity_basis="per_awb",
    )
    missing_count = False
    try:
        _preview(
            additional_repo=additional_repo,
            additional_ids=[awb.evidence_id],
            inquiry=awb.inquiry_reference,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_count = str(exc).startswith("additional_cost_count_required:per_awb:")
    check(missing_count, "selected local-cost quantity basis requires the matching explicit count")

    fx_repo = InMemoryAirFxRateEvidenceRepository()
    fx, _ = _record_fx(
        fx_repo,
        source_repo,
        entry_id="local-fx-eur-usd-001",
        inquiry_reference="AIR-INQ-FX-LOCAL-001",
        base_currency="EUR",
        quote_currency="USD",
        rate=Decimal("1.10"),
    )
    eur, _ = _record_additional(
        additional_repo,
        source_repo,
        entry_id="local-eur-001",
        inquiry_reference=fx.inquiry_reference,
        cost_category="destination_handling",
        provider_name="Destination Handler",
        amount=Decimal("40"),
        currency="EUR",
        quantity_basis="per_shipment",
    )
    missing_fx = False
    try:
        _preview(
            additional_repo=additional_repo,
            additional_ids=[eur.evidence_id],
            inquiry=eur.inquiry_reference,
            shipment_count=1,
        )
    except AirReviewedSurchargeCostPreviewError as exc:
        missing_fx = str(exc).startswith("additional_cost_currency_mismatch_no_fx:")
    check(missing_fx, "cross-currency selected local cost fails closed without explicit matching FX")

    converted = _preview(
        additional_repo=additional_repo,
        additional_ids=[eur.evidence_id],
        inquiry=eur.inquiry_reference,
        shipment_count=2,
        fx_repo=fx_repo,
        fx_ids=[fx.evidence_id],
        fx_reference_at=fx.effective_at,
    )
    converted_component = converted.included_additional_costs[0]
    check(
        converted.fx_applied is True
        and converted.fx_evidence_ids_used == [fx.evidence_id]
        and converted_component.source_currency == "EUR"
        and converted_component.source_amount_per_unit == Decimal("40")
        and converted_component.source_additional_cost == Decimal("80")
        and converted_component.fx_rate == Decimal("1.10")
        and converted_component.amount_per_unit == Decimal("44.00")
        and converted_component.additional_cost == Decimal("88.00")
        and converted.reviewed_additional_cost_total == Decimal("88.00"),
        "explicit matching FX converts selected local cost while preserving source-currency provenance",
    )

    operational_additional_repo = InMemoryAirAdditionalCostEvidenceRepository()
    operational_local, _ = _record_additional(
        operational_additional_repo,
        source_repo,
        entry_id="local-operational-001",
        inquiry_reference=INQUIRY,
        cost_category="origin_handling",
        amount=Decimal("25"),
        currency="USD",
        quantity_basis="per_shipment",
    )
    availability_repo = InMemoryAirServiceAvailabilityRepository()
    _record_availability(availability_repo, source_repo)
    operational = build_air_operational_readiness_preview(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        inquiry_reference=INQUIRY,
        service_date=SERVICE_DATE,
        actual_weight_kg=287,
        volumetric_weight_kg=250,
        cargo_context="general_cargo",
        routing_context="direct",
        shipment_count=1,
        additional_cost_evidence_ids=[operational_local.evidence_id],
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_simple_surcharges(),
        source_repository=source_repo,
        validity_repository=_validity_repo(source_repo),
        availability_repository=availability_repo,
        additional_cost_repository=operational_additional_repo,
    )
    check(
        operational.operational_evidence_complete is True
        and operational.cost_preview.reviewed_additional_cost_total == Decimal("25")
        and operational.cost_preview.additional_cost_evidence_ids_used == [operational_local.evidence_id]
        and operational.cost_preview.all_in_cost is False
        and operational.partial_cost_only is True
        and operational.customer_quote_ready is False
        and operational.booking_ready is False,
        "operational readiness can carry selected local-cost subtotal without becoming quote or booking authority",
    )

    from src import api
    originals = (
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_shadow_repository,
        api.air_additional_cost_evidence_repository,
        api.air_fx_rate_evidence_repository,
    )
    try:
        api.air_rate_table_review_repository = _table_repo()
        api.air_rate_structure_review_repository = _structure_repo()
        api.air_rate_surcharge_review_repository = _simple_surcharges()
        api.air_shadow_repository = source_repo
        api.air_additional_cost_evidence_repository = additional_repo
        api.air_fx_rate_evidence_repository = fx_repo
        response = api.preview_air_reviewed_surcharge_cost(
            "table-review-0001",
            "table-row-fra-0001",
            api.AirReviewedSurchargeCostPreviewRequest(
                actual_weight_kg=287,
                volumetric_weight_kg=250,
                cargo_context="general_cargo",
                routing_context="direct",
                inquiry_reference=usd.inquiry_reference,
                additional_cost_evidence_ids=[usd.evidence_id],
                shipment_count=1,
            ),
        )
    finally:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
            api.air_additional_cost_evidence_repository,
            api.air_fx_rate_evidence_repository,
        ) = originals
    check(
        response["additional_cost_evidence_ids_used"] == [usd.evidence_id]
        and response["reviewed_additional_cost_total"] == "85.50"
        and response["all_in_cost"] is False
        and response["customer_quote_eligible"] is False,
        "controlled API consumes only explicitly selected local-cost evidence without quote authority",
    )

    root = Path(__file__).resolve().parents[2]
    service_text = (root / "src" / "core" / "air_reviewed_surcharge_cost_preview.py").read_text(encoding="utf-8")
    ui_text = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "additional_cost_evidence_ids" in ui_text
        and "Kullanılacak additional/local cost evidence" in ui_text
        and "otomatik seçilmez" in ui_text
        and "ALL-IN DEĞİL" in ui_text,
        "browser exposes explicit local-cost selection and keeps non-all-in boundary visible",
    )
    check(
        "insert_once" not in service_text
        and ".create(" not in service_text
        and "save(" not in service_text,
        "local-cost consumption remains ephemeral and adds no persistence write path",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_additional_cost_consumption_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir additional-cost consumption regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
