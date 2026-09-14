from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.core.air_quote_readiness_preview import (
    AirQuoteReadinessPreviewError,
    build_air_quote_readiness_preview,
)
from src.core.air_rate_validity_review_repository import InMemoryAirRateValidityReviewRepository
from src.core.air_service_availability_repository import InMemoryAirServiceAvailabilityRepository
from src.core.master_data import CustomerMasterProfile
from src.core.master_data_repository import InMemoryMasterDataRepository
from src.core.models import Package, Shipment
from src.core.pilot_access import route_allowed
from src.core.pricing_policy import PricingFormula
from src.simulation.air_additional_cost_consumption_regressions import _simple_surcharges
from src.simulation.air_cost_completeness_preview_regressions import INQUIRY, _rounding_repo, _setup
from src.simulation.air_freight_calculation_preview_regressions import _structure_repo, _table_repo
from src.simulation.air_rate_validity_review_regressions import _review as _record_validity
from src.simulation.air_service_availability_regressions import _record as _record_availability


NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 9, 16)


def _customer_repo(*, formula: PricingFormula | None = None):
    repo = InMemoryMasterDataRepository()
    customer = CustomerMasterProfile(
        entry_id="p241-air-customer",
        customer_name="Air Quote Customer",
        aliases=["Air Customer Alias"],
        active=True,
        pricing_policy=formula or PricingFormula(method="fixed_profit", value=100),
        created_at=NOW,
        updated_at=NOW,
        updated_by="Pricing Admin",
    )
    repo.create_customer(customer)
    return repo, customer


def _shipment(customer_name="Air Quote Customer", **overrides):
    payload = dict(
        customer_name=customer_name,
        pickup_address="Adana OSB, Saricam, Adana, Turkiye",
        delivery_address="Frankfurt Cargo City, Frankfurt, Germany",
        commodity="Textile samples",
        gross_weight_kg=287,
        transport_mode="air",
        cargo_ready_date="2026-09-15",
        required_delivery_date=None,
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[Package(package_type="pallet", quantity=2, length_cm=100, width_cm=80, height_cm=60)],
    )
    payload.update(overrides)
    return Shipment(**payload)


def _validity_repo(source_repo):
    repo = InMemoryAirRateValidityReviewRepository()
    _record_validity(repo, source_repo)
    return repo


def _availability_repo(source_repo, *, expected_delivery_date=None, **overrides):
    repo = InMemoryAirServiceAvailabilityRepository()
    payload = dict(
        entry_id="p241-availability",
        inquiry_reference=INQUIRY,
        service_date=SERVICE_DATE,
        expected_delivery_date=expected_delivery_date,
    )
    payload.update(overrides)
    _record_availability(repo, source_repo, **payload)
    return repo


def _preview(*, setup, customer_repo, customer_id, shipment, availability_repo, validity_repo, **overrides):
    source_repo, scope_repo, scope, semantics_repo, semantics, additional_repo, pickup, delivery = setup
    payload = dict(
        review_id="table-review-0001",
        candidate_id="table-row-fra-0001",
        cost_scope_review_id=scope.review_id,
        unsupported_cost_semantics_review_id=semantics.review_id,
        inquiry_reference=INQUIRY,
        customer_id=customer_id,
        service_date=SERVICE_DATE,
        shipment=shipment,
        cargo_context="general_cargo",
        routing_context="direct",
        shipment_count=1,
        additional_cost_evidence_ids=[pickup.evidence_id, delivery.evidence_id],
        table_repository=_table_repo(),
        structure_repository=_structure_repo(),
        surcharge_repository=_simple_surcharges(),
        source_repository=source_repo,
        scope_repository=scope_repo,
        unsupported_semantics_repository=semantics_repo,
        additional_cost_repository=additional_repo,
        rounding_repository=_rounding_repo(),
        validity_repository=validity_repo,
        availability_repository=availability_repo,
        master_data_repository=customer_repo,
        environ={},
    )
    payload.update(overrides)
    return build_air_quote_readiness_preview(**payload)


def evaluate_air_quote_readiness_preview_regressions() -> dict:
    passes: list[str] = []
    failures: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    setup = _setup()
    source_repo = setup[0]
    customer_repo, customer = _customer_repo()
    validity_repo = _validity_repo(source_repo)

    no_deadline_availability = _availability_repo(source_repo)
    ready = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(),
        availability_repo=no_deadline_availability,
        validity_repo=validity_repo,
    )
    check(
        ready.quote_ready is True
        and ready.shipment_inputs_complete is True
        and ready.pricing_complete is True
        and ready.operational_evidence_complete is True
        and ready.regulatory_compliance_clear is True
        and ready.regulatory_compliance.status == "clear"
        and ready.delivery_deadline_status == "not_provided"
        and ready.blockers == []
        and ready.package_piece_count == 2
        and ready.total_volume_cm3 is not None
        and ready.pricing_preview.customer_price_preview is not None
        and ready.pricing_preview.customer_price_preview.final_price == 1043.5,
        "air quote readiness can become READY when shipment pricing and operational evidence are complete",
    )
    check(
        ready.quote_creation_authority is False
        and ready.quote_created is False
        and ready.quote_send_authority is False
        and ready.booking_authority is False
        and ready.outbound_authority is False
        and ready.runtime_authoritative is False,
        "quote-ready preview never creates QuoteCase send booking outbound or runtime authority",
    )
    check(
        ready.delivery_deadline_status == "not_provided" and ready.customer_required_delivery_date is None,
        "missing customer delivery deadline does not create a clarification or readiness blocker",
    )

    deadline_availability = _availability_repo(
        source_repo,
        expected_delivery_date=date(2026, 9, 18),
        entry_id="p241-availability-deadline-ok",
    )
    deadline_ok = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(required_delivery_date="2026-09-18"),
        availability_repo=deadline_availability,
        validity_repo=validity_repo,
    )
    check(
        deadline_ok.quote_ready is True
        and deadline_ok.delivery_deadline_status == "confirmed"
        and deadline_ok.expected_delivery_date == date(2026, 9, 18),
        "explicit customer delivery deadline is accepted only with matching expected-delivery evidence",
    )

    no_eta_for_deadline = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(required_delivery_date="2026-09-18"),
        availability_repo=no_deadline_availability,
        validity_repo=validity_repo,
    )
    check(
        no_eta_for_deadline.quote_ready is False
        and no_eta_for_deadline.delivery_deadline_status == "evidence_missing"
        and "expected_delivery_date_evidence_required_for_customer_deadline" in no_eta_for_deadline.blockers,
        "customer delivery deadline blocks quote readiness when expected-delivery evidence is missing",
    )

    late_availability = _availability_repo(
        source_repo,
        expected_delivery_date=date(2026, 9, 19),
        entry_id="p241-availability-deadline-late",
    )
    late = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(required_delivery_date="2026-09-18"),
        availability_repo=late_availability,
        validity_repo=validity_repo,
    )
    check(
        late.quote_ready is False
        and late.delivery_deadline_status == "not_met"
        and "customer_delivery_deadline_not_met" in late.blockers,
        "air service expected delivery later than customer deadline fails closed",
    )

    missing_availability = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(),
        availability_repo=InMemoryAirServiceAvailabilityRepository(),
        validity_repo=validity_repo,
    )
    check(
        missing_availability.quote_ready is False
        and missing_availability.operational_evidence_complete is False
        and "operational:availability_evidence_missing" in missing_availability.blockers,
        "missing capacity schedule evidence blocks quote readiness even when customer price exists",
    )

    unsafe_unknown = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(is_adr=None, is_temperature_controlled=None, is_high_value=None),
        availability_repo=no_deadline_availability,
        validity_repo=validity_repo,
    )
    check(
        unsafe_unknown.quote_ready is False
        and set(unsafe_unknown.shipment_input_blockers) >= {
            "adr_status_required", "temperature_control_status_required", "high_value_status_required"
        },
        "unknown ADR temperature-control or high-value state cannot silently pass quote readiness",
    )

    service_before_ready = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(cargo_ready_date="2026-09-17"),
        availability_repo=no_deadline_availability,
        validity_repo=validity_repo,
    )
    check(
        service_before_ready.quote_ready is False
        and "service_date_before_cargo_ready_date" in service_before_ready.blockers,
        "air service date before cargo-ready date blocks quote readiness",
    )

    missing_exact_address = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(pickup_address=None, pickup_city="Adana"),
        availability_repo=no_deadline_availability,
        validity_repo=validity_repo,
    )
    check(
        missing_exact_address.quote_ready is False
        and "pickup_address_required_for_required_pickup_cost" in missing_exact_address.blockers,
        "required pickup local-cost scope requires an exact pickup address at quote readiness",
    )

    wrong_customer = _preview(
        setup=setup,
        customer_repo=customer_repo,
        customer_id=customer.customer_id,
        shipment=_shipment(customer_name="Different Customer"),
        availability_repo=no_deadline_availability,
        validity_repo=validity_repo,
    )
    check(
        wrong_customer.quote_ready is False
        and "shipment_customer_mismatch" in wrong_customer.blockers,
        "shipment identity cannot silently cross the selected customer master profile",
    )

    missing_dimensions_blocked = False
    try:
        _preview(
            setup=setup,
            customer_repo=customer_repo,
            customer_id=customer.customer_id,
            shipment=_shipment(packages=[Package(quantity=1, length_cm=None, width_cm=80, height_cm=60)]),
            availability_repo=no_deadline_availability,
            validity_repo=validity_repo,
        )
    except AirQuoteReadinessPreviewError as exc:
        missing_dimensions_blocked = str(exc) == "air_quote_readiness_package_dimensions_required:1"
    check(
        missing_dimensions_blocked,
        "missing package dimensions fail before chargeable-weight or customer-price calculation instead of using a fabricated value",
    )

    missing_weight_blocked = False
    try:
        _preview(
            setup=setup,
            customer_repo=customer_repo,
            customer_id=customer.customer_id,
            shipment=_shipment(gross_weight_kg=None),
            availability_repo=no_deadline_availability,
            validity_repo=validity_repo,
        )
    except AirQuoteReadinessPreviewError as exc:
        missing_weight_blocked = str(exc) == "air_quote_readiness_gross_weight_required"
    check(
        missing_weight_blocked,
        "missing gross weight fails closed before air pricing instead of inventing an approximate weight",
    )

    no_policy_repo, no_policy_customer = _customer_repo(formula=PricingFormula(method="fixed_profit", value=100))
    no_policy_customer = no_policy_customer.model_copy(update={"pricing_policy": None})
    no_policy_repo.save_customer(no_policy_customer)
    pricing_blocked = _preview(
        setup=setup,
        customer_repo=no_policy_repo,
        customer_id=no_policy_customer.customer_id,
        shipment=_shipment(customer_name=no_policy_customer.customer_name),
        availability_repo=no_deadline_availability,
        validity_repo=validity_repo,
        environ={},
    )
    check(
        pricing_blocked.quote_ready is False
        and pricing_blocked.pricing_complete is False
        and any(item.startswith("pricing:") for item in pricing_blocked.blockers),
        "missing customer and agency pricing policy blocks quote readiness",
    )

    invalid_expected_delivery = False
    try:
        _availability_repo(
            source_repo,
            expected_delivery_date=date(2026, 9, 15),
            entry_id="p241-invalid-eta",
        )
    except ValueError as exc:
        invalid_expected_delivery = "Expected delivery date cannot be before air service date" in str(exc)
    check(
        invalid_expected_delivery,
        "availability evidence cannot claim expected delivery before the selected air service date",
    )

    from src import api
    originals = (
        api.air_rate_table_review_repository,
        api.air_rate_structure_review_repository,
        api.air_rate_surcharge_review_repository,
        api.air_shadow_repository,
        api.air_cost_scope_review_repository,
        api.air_unsupported_cost_semantics_review_repository,
        api.air_additional_cost_evidence_repository,
        api.air_rate_weight_rounding_review_repository,
        api.air_rate_validity_review_repository,
        api.air_service_availability_repository,
        api.master_data_repository,
    )
    try:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
            api.air_cost_scope_review_repository,
            api.air_unsupported_cost_semantics_review_repository,
            api.air_additional_cost_evidence_repository,
            api.air_rate_weight_rounding_review_repository,
            api.air_rate_validity_review_repository,
            api.air_service_availability_repository,
            api.master_data_repository,
        ) = (
            _table_repo(), _structure_repo(), _simple_surcharges(), setup[0], setup[1], setup[3],
            setup[5], _rounding_repo(), validity_repo, no_deadline_availability, customer_repo,
        )
        request = api.AirQuoteReadinessPreviewRequest(
            cost_scope_review_id=setup[2].review_id,
            unsupported_cost_semantics_review_id=setup[4].review_id,
            inquiry_reference=INQUIRY,
            customer_id=customer.customer_id,
            service_date=SERVICE_DATE,
            shipment=_shipment(),
            cargo_context="general_cargo",
            routing_context="direct",
            shipment_count=1,
            additional_cost_evidence_ids=[setup[-2].evidence_id, setup[-1].evidence_id],
        )
        with patch.dict("os.environ", {}, clear=True):
            response = api.preview_air_quote_readiness(
                "table-review-0001", "table-row-fra-0001", request
            )
    finally:
        (
            api.air_rate_table_review_repository,
            api.air_rate_structure_review_repository,
            api.air_rate_surcharge_review_repository,
            api.air_shadow_repository,
            api.air_cost_scope_review_repository,
            api.air_unsupported_cost_semantics_review_repository,
            api.air_additional_cost_evidence_repository,
            api.air_rate_weight_rounding_review_repository,
            api.air_rate_validity_review_repository,
            api.air_service_availability_repository,
            api.master_data_repository,
        ) = originals
    check(
        response["quote_ready"] is True
        and response["quote_created"] is False
        and response["quote_creation_authority"] is False
        and response["quote_send_authority"] is False
        and response["booking_authority"] is False,
        "controlled API exposes quote readiness without creating or sending a quote",
    )

    check(
        route_allowed("POST", "/air-rate-table-reviews/r1/rows/c1/quote-readiness-preview"),
        "pilot access admits the bounded air quote-readiness preview route",
    )

    root = Path(__file__).resolve().parents[2]
    service = (root / "src" / "core" / "air_quote_readiness_preview.py").read_text(encoding="utf-8")
    ui = (root / "ui" / "web_shell" / "app.js").read_text(encoding="utf-8")
    check(
        "insert_once" not in service
        and ".create(" not in service
        and "upsert" not in service
        and "save(" not in service
        and "openai" not in service.casefold(),
        "air quote-readiness gate remains deterministic ephemeral orchestration with no persistence or AI path",
    )
    check(
        "Air Quote Readiness Gate" in ui
        and "Air Quote Readiness Kontrol Et" in ui
        and "Customer delivery deadline yoksa süreç devam eder" in ui
        and "QUOTE HENÜZ OLUŞMADI" in ui
        and "SEND AUTHORITY YOK" in ui
        and "BOOKING AUTHORITY YOK" in ui,
        "browser makes shipment deadline and non-execution quote-readiness boundaries visible",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_air_quote_readiness_preview_regressions()
    for label in result["passes"]:
        print(f"PASS {label}")
    for label in result["failures"]:
        print(f"FAIL {label}")
    print("\nAir quote readiness preview regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
