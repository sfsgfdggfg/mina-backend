from typing import Any, Optional

from src.core.models import Shipment, EquipmentDecision, SupplierQuote
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)


def _get_selected_supplier_name(supplier_selection: Optional[dict[str, Any]]) -> str:
    if not supplier_selection:
        return "Demo Transport"

    selected_suppliers = supplier_selection.get("selected_suppliers") or []

    if not selected_suppliers:
        return "Demo Transport"

    return selected_suppliers[0].get("supplier_name", "Demo Transport")


def simulate_supplier_quote(
    shipment: Shipment,
    equipment_decision: EquipmentDecision,
    supplier_selection: Optional[dict[str, Any]] = None,
) -> SupplierQuote:
    """
    Fake supplier quote engine.

    Gerçek RFQ gelmeden önce workflow test etmek için kullanılır.
    """

    base_cost = 2000.0

    # Basic adjustment by equipment
    if "Reefer" in equipment_decision.selected_equipment:
        base_cost += 600

    if "Lowbed" in equipment_decision.selected_equipment:
        base_cost += 1200

    if "Mega" in equipment_decision.selected_equipment:
        base_cost += 300

    if "Box" in equipment_decision.selected_equipment:
        base_cost += 250

    return SupplierQuote(
        supplier_name=_get_selected_supplier_name(supplier_selection),
        cost=base_cost,
        currency="EUR",
        transit_time="5-7 days",
        notes=f"Simulated supplier quote for {equipment_decision.selected_equipment}",
    )

def simulate_supplier_rfq_responses(
    shipment: Shipment,
    equipment_decision: EquipmentDecision,
    supplier_selection: Optional[dict[str, Any]] = None,
    rfq_drafts: Optional[list[SupplierRFQDraft]] = None,
) -> list[SupplierRFQResponse]:
    selected_suppliers = (
        supplier_selection.get("selected_suppliers", [])
        if supplier_selection
        else []
    )

    response_sources = (
        list(rfq_drafts[:3])
        if rfq_drafts is not None
        else selected_suppliers[:3]
    )

    responses: list[SupplierRFQResponse] = []

    for index, source_item in enumerate(response_sources, start=1):
        if isinstance(source_item, SupplierRFQDraft):
            rfq_id = source_item.rfq_id
            supplier_name = source_item.supplier_name
            rfq_priority = source_item.priority
        else:
            rfq_id = None
            supplier_name = source_item.get(
                "supplier_name",
                f"Supplier {index}",
            )
            rfq_priority = int(source_item.get("priority") or index)
        base_cost = 2000.0 + ((index - 1) * 120)

        if "Reefer" in equipment_decision.selected_equipment:
            base_cost += 600

        if "Lowbed" in equipment_decision.selected_equipment:
            base_cost += 1200

        if "Mega" in equipment_decision.selected_equipment:
            base_cost += 300

        if "Box" in equipment_decision.selected_equipment:
            base_cost += 250

        responses.append(
            SupplierRFQResponse(
                **({"rfq_id": rfq_id} if rfq_id else {}),
                supplier_name=supplier_name,
                rfq_priority=rfq_priority,
                status="quoted",
                cost=base_cost,
                currency="EUR",
                transit_time=f"{4 + index}-{6 + index} days",
                equipment_type=equipment_decision.selected_equipment,
                notes="Simulated supplier RFQ response.",
                source="simulation",
            )
        )

    return responses
