"""Focused road RFQ and supplier commercial safety regressions."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import os
from unittest.mock import patch

from src.ai.supplier_rfq_generator import (
    generate_supplier_rfq_drafts,
)
from src.core.missing_info import check_missing_information
from src.core.missing_info import MissingInfoResult
from src.core.models import (
    EquipmentDecision,
    Package,
    Shipment,
)
from src.core.road_rfq_readiness import (
    apply_road_rfq_readiness,
)
from src.core.supplier_commercial_safety import (
    evaluate_supplier_commercial_safety,
    parse_transit_time,
)
from src.core.supplier_quote_comparison import (
    build_supplier_quote_comparisons,
)
from src.core.supplier_quote_selection import (
    select_supplier_quote_from_comparisons,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)
from src.core.supplier_rfq_lifecycle import (
    attach_supplier_rfq_response,
    synchronize_supplier_rfq_lifecycle,
)
from src.core.supplier_rfq_repository import (
    DuplicateSupplierRFQResponseError,
    InMemorySupplierRFQRepository,
)
from src.workflow.pipeline import process_shipment


AS_OF = date(2026, 8, 15)


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Synthetic Road RFQ Safety",
        pickup_country="Türkiye",
        pickup_city="Adana",
        delivery_country="Almanya",
        delivery_city="Hamburg",
        delivery_postcode="20095",
        commodity="Tekstil",
        gross_weight_kg=20_000,
        transport_mode="road",
        service_type="FTL",
        equipment_type="Tenteli",
        cargo_ready_date="2026-08-20",
        required_delivery_date="2026-08-27",
        is_adr=False,
        is_temperature_controlled=False,
        is_high_value=False,
        packages=[
            Package(
                package_type="pallet",
                quantity=10,
                length_cm=120,
                width_cm=80,
                height_cm=160,
                weight_kg=2000,
            )
        ],
    )


def _selection() -> dict:
    return {
        "selected_suppliers": [{
            "supplier_name": "Synthetic Carrier",
            "recipient_email": "pricing@carrier.invalid",
            "priority": 1,
            "route_score": 1.0,
            "equipment_score": 1.0,
            "risk_score": 1.0,
            "price_score": 0.8,
            "speed_score": 0.8,
            "total_score": 0.9,
        }],
        "rejected_suppliers": [],
    }


def _complete_response(
    *,
    rfq_id: str,
    received_at: datetime | None = None,
) -> SupplierRFQResponse:
    return SupplierRFQResponse(
        rfq_id=rfq_id,
        supplier_name="Synthetic Carrier",
        rfq_priority=1,
        status="quoted",
        cost=1900,
        currency="EUR",
        transit_time="4-5 iş günü",
        validity_date="2026-08-31",
        vehicle_available_date="2026-08-20",
        equipment_type="Tenteli / Curtainsider",
        pricing_basis="all_in",
        included_costs=["road freight", "tolls"],
        excluded_costs=[],
        source="manual",
        received_at=(
            received_at
            or datetime(2026, 8, 15, 10, 0, 0)
        ),
    )


def evaluate_road_rfq_commercial_safety_regressions() -> dict:
    failures: list[str] = []

    # A. Customer inquiry / RFQ completeness.
    incomplete = _shipment().model_copy(
        update={
            "delivery_country": None,
            "gross_weight_kg": None,
            "required_delivery_date": None,
            "delivery_postcode": None,
            "packages": [],
        }
    )

    readiness = apply_road_rfq_readiness(
        incomplete,
        check_missing_information(incomplete),
    )

    expected = {
        "delivery country",
        "gross weight",
        "package count and dimensions",
    }

    if (
        readiness.can_continue_to_quote
        or not expected.issubset(
            set(readiness.missing_fields)
        )
    ):
        failures.append(
            "incomplete road commercial facts did not fail closed"
        )

    optional_deadline = _shipment().model_copy(
        update={"required_delivery_date": None}
    )
    optional_deadline_readiness = apply_road_rfq_readiness(
        optional_deadline,
        check_missing_information(optional_deadline),
    )

    if (
        not optional_deadline_readiness.can_continue_to_quote
        or "required delivery date"
        in optional_deadline_readiness.missing_fields
    ):
        failures.append(
            "missing customer delivery deadline incorrectly blocked road RFQ"
        )

    invalid_deadline = _shipment().model_copy(
        update={"required_delivery_date": "not-a-date"}
    )
    invalid_deadline_readiness = apply_road_rfq_readiness(
        invalid_deadline,
        check_missing_information(invalid_deadline),
    )

    if (
        invalid_deadline_readiness.can_continue_to_quote
        or "required delivery date"
        not in invalid_deadline_readiness.missing_fields
    ):
        failures.append(
            "explicit invalid customer delivery deadline did not block road RFQ"
        )

    foreign_pickup = _shipment().model_copy(
        update={
            "pickup_country": "Almanya",
            "pickup_postcode": None,
        }
    )

    foreign_readiness = apply_road_rfq_readiness(
        foreign_pickup,
        check_missing_information(foreign_pickup),
    )

    if "pickup postcode" not in foreign_readiness.missing_fields:
        failures.append(
            "foreign pickup postcode was not required"
        )

    equipment = EquipmentDecision(
        selected_equipment="Tenteli",
        reason="Synthetic regression.",
        confidence=1.0,
    )

    drafts = generate_supplier_rfq_drafts(
        shipment=_shipment(),
        equipment_decision=equipment,
        supplier_selection=_selection(),
        workflow_id="road-rfq-safety",
    )

    if len(drafts) != 1:
        failures.append(
            "complete road shipment did not generate one RFQ"
        )
    else:
        body = drafts[0].body

        for expected_text in (
            "20095",
            "10 × pallet",
            "120 × 80 × 160 cm",
            "20000 kg",
            "2026-08-27",
        ):
            if expected_text not in body:
                failures.append(
                    "RFQ omitted required fact: "
                    + expected_text
                )

    internal_and_customer_notes = _shipment().model_copy(
        update={
            "special_notes": (
                "Kapı tesliminde randevu gereklidir.\n"
                "[COMMODITY PROFILE] Internal textile review note."
            )
        }
    )
    note_boundary_drafts = generate_supplier_rfq_drafts(
        shipment=internal_and_customer_notes,
        equipment_decision=equipment,
        supplier_selection=_selection(),
        workflow_id="road-rfq-external-note-boundary",
    )
    note_boundary_body = note_boundary_drafts[0].body
    if "Kapı tesliminde randevu gereklidir." not in note_boundary_body:
        failures.append("customer special note was removed from supplier RFQ")
    if "[COMMODITY PROFILE]" in note_boundary_body:
        failures.append("internal commodity profile note leaked into supplier RFQ")

    internal_only_notes = _shipment().model_copy(
        update={
            "special_notes": "[COMMODITY PROFILE] Internal-only note."
        }
    )
    internal_only_draft = generate_supplier_rfq_drafts(
        shipment=internal_only_notes,
        equipment_decision=equipment,
        supplier_selection=_selection(),
        workflow_id="road-rfq-internal-only-note",
    )[0]
    if "Özel Notlar:" in internal_only_draft.body:
        failures.append("empty external special-note line was emitted")

    optional_deadline_drafts = generate_supplier_rfq_drafts(
        shipment=optional_deadline,
        equipment_decision=equipment,
        supplier_selection=_selection(),
        workflow_id="road-rfq-no-deadline",
    )

    if (
        len(optional_deadline_drafts) != 1
        or "Gerekli Teslim Tarihi: Belirtilmedi"
        not in optional_deadline_drafts[0].body
    ):
        failures.append(
            "road RFQ without customer deadline was not generated truthfully"
        )

    with patch.dict(
        os.environ,
        {"MINAI_PILOT_MODE": "0"},
        clear=False,
    ):
        with patch(
            "src.workflow.pipeline.select_suppliers_for_shipment",
            return_value={
                "selected_suppliers": [],
                "rejected_suppliers": [],
                "source": "synthetic-empty-selection",
            },
        ):
            empty_selection = process_shipment(
                _shipment()
            )

    if (
        empty_selection.get("result_type")
        != "supplier_selection_required"
        or empty_selection.get(
            "supplier_rfq_workflow"
        ) is not None
        or empty_selection.get("supplier_rfq_drafts")
    ):
        failures.append(
            "zero eligible suppliers created or advanced an RFQ workflow"
        )

    # B. Transit parsing must respect units and use max range.
    expectations = (
        ("48 hours", 2, "hours"),
        ("1 week", 7, "weeks"),
        ("4-5 days", 5, "calendar_days"),
        ("4-5 iş günü", 5, "business_days"),
    )

    for value, expected_days, expected_unit in expectations:
        parsed = parse_transit_time(value)

        if (
            parsed is None
            or parsed.scoring_days != expected_days
            or parsed.unit != expected_unit
        ):
            failures.append(
                f"transit parsing failed for {value}"
            )

    # C. needs_clarification keeps the same RFQ open.
    repository = InMemorySupplierRFQRepository()

    draft = SupplierRFQDraft(
        supplier_name="Synthetic Carrier",
        priority=1,
        recipient_email="pricing@carrier.invalid",
        subject="Synthetic RFQ",
        body="Synthetic RFQ",
        status="awaiting_response",
        sent_at=datetime(2026, 8, 15, 9, 0, 0),
    )

    repository.save_drafts([draft])

    clarification = SupplierRFQResponse(
        rfq_id=draft.rfq_id,
        supplier_name=draft.supplier_name,
        rfq_priority=draft.priority,
        status="needs_clarification",
        notes="Please confirm loading window.",
        source="manual",
        received_at=datetime(2026, 8, 15, 9, 30, 0),
    )

    clarification_state = attach_supplier_rfq_response(
        repository,
        clarification,
    )

    if clarification_state.status != "clarification_required":
        failures.append(
            "needs_clarification consumed the RFQ"
        )

    final_response = _complete_response(
        rfq_id=draft.rfq_id,
        received_at=(
            clarification.received_at
            + timedelta(minutes=30)
        ),
    ).model_copy(
        update={
            "recorded_by": "Synthetic Operator",
        }
    )

    final_state = attach_supplier_rfq_response(
        repository,
        final_response,
    )

    stored_responses = repository.list_responses(
        draft.rfq_id
    )

    if (
        final_state.status != "responded"
        or len(stored_responses) != 2
    ):
        failures.append(
            "final supplier quote after clarification was not accepted"
        )

    stored_final = next(
        (
            response
            for response in stored_responses
            if response.status == "quoted"
        ),
        None,
    )

    if (
        stored_final is None
        or stored_final.recorded_by
        != "Synthetic Operator"
    ):
        failures.append(
            "manual supplier response actor provenance was not preserved"
        )

    synchronized = synchronize_supplier_rfq_lifecycle(
        drafts=[clarification_state],
        responses=[
            clarification,
            final_response,
        ],
    )

    if (
        len(synchronized) != 1
        or synchronized[0].status != "responded"
        or synchronized[0].responded_at
        != final_response.received_at
    ):
        failures.append(
            "durable clarification lifecycle did not synchronize to final response"
        )

    try:
        attach_supplier_rfq_response(
            repository,
            final_response,
        )
    except DuplicateSupplierRFQResponseError:
        pass
    else:
        failures.append(
            "completed supplier RFQ accepted a duplicate final response"
        )

    # D. Complete all-in quote must meet equipment/deadline/validity.
    safety = evaluate_supplier_commercial_safety(
        response=final_response,
        shipment=_shipment(),
        expected_equipment="Tenteli",
        as_of=AS_OF,
    )

    if (
        not safety.eligible_for_customer_quote
        or safety.transit_days != 5
        or safety.delivery_deadline_met is not True
        or str(safety.projected_delivery_date)
        != "2026-08-27"
    ):
        failures.append(
            "complete supplier quote was not commercially eligible"
        )

    optional_deadline_safety = evaluate_supplier_commercial_safety(
        response=final_response,
        shipment=optional_deadline,
        expected_equipment="Tenteli",
        as_of=AS_OF,
    )

    if (
        not optional_deadline_safety.eligible_for_customer_quote
        or optional_deadline_safety.delivery_deadline_met is not None
        or str(optional_deadline_safety.projected_delivery_date)
        != "2026-08-27"
        or "required_delivery_date_missing_or_invalid"
        in optional_deadline_safety.reasons
    ):
        failures.append(
            "supplier quote without customer delivery deadline was incorrectly rejected"
        )

    comparisons = build_supplier_quote_comparisons(
        responses=[
            clarification,
            final_response,
        ],
        supplier_selection=_selection(),
        drafts=[final_state],
        shipment=_shipment(),
        expected_equipment="Tenteli",
        require_commercial_safety=True,
        as_of=AS_OF,
    )

    selected = select_supplier_quote_from_comparisons(
        comparisons=comparisons,
        responses=[
            clarification,
            final_response,
        ],
    )

    if (
        selected is None
        or selected.validity_date != "2026-08-31"
        or selected.vehicle_available_date != "2026-08-20"
        or selected.pricing_basis != "all_in"
        or selected.excluded_costs != []
    ):
        failures.append(
            "selected supplier quote lost commercial evidence"
        )

    # E. Deadline miss must remain visible but unselectable.
    late_shipment = _shipment().model_copy(
        update={
            "required_delivery_date": "2026-08-26",
        }
    )

    late_comparisons = build_supplier_quote_comparisons(
        responses=[final_response],
        supplier_selection=_selection(),
        drafts=[final_state],
        shipment=late_shipment,
        expected_equipment="Tenteli",
        require_commercial_safety=True,
        as_of=AS_OF,
    )

    if (
        len(late_comparisons) != 1
        or late_comparisons[0].commercial_eligible
        or (
            "required_delivery_date_not_achievable"
            not in late_comparisons[
                0
            ].commercial_rejection_reasons
        )
        or select_supplier_quote_from_comparisons(
            comparisons=late_comparisons,
            responses=[final_response],
        )
        is not None
    ):
        failures.append(
            "late supplier quote remained customer-quote eligible"
        )

    # F. Missing optional road metadata must not block; explicit commercial
    # contradictions still fail closed.
    minimal_road_quote = final_response.model_copy(
        update={
            "validity_date": None,
            "vehicle_available_date": None,
            "equipment_type": None,
            "pricing_basis": None,
            "included_costs": None,
            "excluded_costs": None,
        }
    )
    minimal_safety = evaluate_supplier_commercial_safety(
        response=minimal_road_quote,
        shipment=_shipment(),
        expected_equipment="Tenteli",
        as_of=AS_OF,
    )
    if (
        not minimal_safety.eligible_for_customer_quote
        or str(minimal_safety.projected_delivery_date) != "2026-08-27"
    ):
        failures.append("minimal standard road quote was incorrectly blocked")

    unsafe_updates = (
        (
            "expired quote",
            {
                "validity_date": "2026-08-14",
            },
            "supplier_quote_expired",
        ),
        (
            "equipment mismatch",
            {
                "equipment_type": "Reefer",
            },
            "supplier_equipment_mismatch",
        ),
        (
            "non-all-in price",
            {
                "pricing_basis": (
                    "base_freight_plus_extras"
                ),
                "excluded_costs": ["tolls"],
            },
            "supplier_price_has_unpriced_extras",
        ),
    )

    for label, updates, expected_reason in unsafe_updates:
        candidate = final_response.model_copy(
            update=updates
        )

        candidate_safety = (
            evaluate_supplier_commercial_safety(
                response=candidate,
                shipment=_shipment(),
                expected_equipment="Tenteli",
                as_of=AS_OF,
            )
        )

        if (
            candidate_safety.eligible_for_customer_quote
            or expected_reason
            not in candidate_safety.reasons
        ):
            failures.append(
                f"{label} did not fail closed"
            )

    indicative_shipment = _shipment().model_copy(
        update={
            "quote_mode": "indicative",
            "commodity": None,
            "gross_weight_kg": None,
            "packages": [],
            "cargo_ready_date": None,
            "required_delivery_date": None,
            "delivery_postcode": None,
        }
    )
    indicative_readiness = apply_road_rfq_readiness(
        indicative_shipment, check_missing_information(indicative_shipment)
    )
    if not indicative_readiness.can_continue_to_quote:
        failures.append("indicative route was blocked by firm quote fields")
    indicative_drafts = generate_supplier_rfq_drafts(
        shipment=indicative_shipment,
        equipment_decision=equipment,
        supplier_selection=_selection(),
        workflow_id="indicative-road",
    )
    if (
        len(indicative_drafts) != 1
        or "İNDİKATİF" not in indicative_drafts[0].body
        or "araç rezervasyonu değildir" not in indicative_drafts[0].body
    ):
        failures.append("indicative supplier RFQ was not marked non-binding")
    indicative_response = SupplierRFQResponse(
        rfq_id=indicative_drafts[0].rfq_id,
        supplier_name="Synthetic Carrier",
        rfq_priority=1,
        status="quoted",
        cost=2100,
        currency="EUR",
        source="manual",
    )
    indicative_safety = evaluate_supplier_commercial_safety(
        response=indicative_response,
        shipment=indicative_shipment,
        expected_equipment="Tenteli",
        as_of=AS_OF,
    )
    if not indicative_safety.eligible_for_customer_quote:
        failures.append("indicative price+currency response was incorrectly blocked")

    advisory_base = MissingInfoResult(
        can_continue_to_quote=True,
        missing_fields=["noncritical advisory"],
        reason="Advisory only.",
    )
    advisory_result = apply_road_rfq_readiness(_shipment(), advisory_base)
    if not advisory_result.can_continue_to_quote:
        failures.append("noncritical base missing info became road RFQ blocker")

    return {
        "name": "Road RFQ commercial safety",
        "passed": not failures,
        "failures": failures,
    }


if __name__ == "__main__":
    result = (
        evaluate_road_rfq_commercial_safety_regressions()
    )
    print(result)
    raise SystemExit(
        0 if result["passed"] else 1
    )
