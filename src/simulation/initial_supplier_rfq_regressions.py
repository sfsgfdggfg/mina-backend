"""Focused regressions for initial supplier RFQ draft orchestration."""

from __future__ import annotations

import os
from unittest.mock import patch

from src.core.models import Package, Shipment
from src.core.supplier_dispatch_policy import SupplierDispatchPolicy
from src.workflow.pipeline import process_shipment


def _shipment() -> Shipment:
    return Shipment(
        customer_name="Synthetic Initial RFQ",
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


def _selection(count: int) -> dict:
    return {
        "selected_suppliers": [
            {
                "supplier_name": f"Synthetic Carrier {priority}",
                "recipient_email": f"pricing{priority}@carrier.invalid",
                "priority": priority,
                "total_score": 1 - (priority / 10),
            }
            for priority in range(1, count + 1)
        ],
        "rejected_suppliers": [],
        "source": "synthetic-ranked-selection",
    }


def evaluate_initial_supplier_rfq_regressions() -> dict:
    failures: list[str] = []

    with patch.dict(os.environ, {"MINAI_PILOT_MODE": "0"}, clear=False):
        with patch(
            "src.workflow.pipeline.select_suppliers_for_shipment",
            return_value=_selection(3),
        ):
            result = process_shipment(_shipment())

        selected = result["supplier_selection"]["selected_suppliers"]
        drafts = result["supplier_rfq_drafts"]
        workflow = result["supplier_rfq_workflow"]

        if len(selected) != 3:
            failures.append("the full three-supplier shortlist was not retained")
        if len(drafts) != 1:
            failures.append("initial workflow did not create exactly one RFQ draft")
        elif drafts[0].priority != 1 or drafts[0].supplier_name != selected[0]["supplier_name"]:
            failures.append("initial RFQ draft did not belong to priority-1 supplier")
        if workflow is None or workflow.rfq_ids != [draft.rfq_id for draft in drafts]:
            failures.append("workflow RFQ ids did not contain exactly the initial draft id")
        elif workflow.dispatch_policy.mode != "sequential":
            failures.append("default workflow did not snapshot sequential dispatch policy")

        with patch(
            "src.workflow.pipeline.select_suppliers_for_shipment",
            return_value=_selection(3),
        ):
            parallel_result = process_shipment(
                _shipment(),
                supplier_dispatch_policy=SupplierDispatchPolicy(
                    mode="parallel",
                    initial_supplier_count=2,
                ),
            )
        parallel_drafts = parallel_result["supplier_rfq_drafts"]
        if [draft.priority for draft in parallel_drafts] != [1, 2]:
            failures.append("parallel-2 did not create the first two RFQ drafts")
        parallel_workflow = parallel_result["supplier_rfq_workflow"]
        if (
            parallel_workflow is None
            or parallel_workflow.dispatch_policy.mode != "parallel"
            or parallel_workflow.dispatch_policy.initial_supplier_count != 2
            or parallel_workflow.rfq_ids != [draft.rfq_id for draft in parallel_drafts]
        ):
            failures.append("parallel dispatch policy was not snapshotted on workflow")

        with patch(
            "src.workflow.pipeline.select_suppliers_for_shipment",
            return_value=_selection(3),
        ):
            parallel_three_result = process_shipment(
                _shipment(),
                supplier_dispatch_policy=SupplierDispatchPolicy(
                    mode="parallel",
                    initial_supplier_count=3,
                ),
            )
        if [draft.priority for draft in parallel_three_result["supplier_rfq_drafts"]] != [1, 2, 3]:
            failures.append("parallel-3 did not create all three RFQ drafts")

        with patch(
            "src.workflow.pipeline.select_suppliers_for_shipment",
            return_value=_selection(0),
        ):
            empty_result = process_shipment(_shipment())

    if (
        empty_result.get("result_type") != "supplier_selection_required"
        or empty_result.get("supplier_rfq_workflow") is not None
        or empty_result.get("supplier_rfq_drafts")
    ):
        failures.append("zero-supplier behavior changed")

    return {"passed": not failures, "failures": failures}


if __name__ == "__main__":
    outcome = evaluate_initial_supplier_rfq_regressions()
    print(outcome)
    raise SystemExit(0 if outcome["passed"] else 1)
