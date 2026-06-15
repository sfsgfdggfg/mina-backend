from typing import Any, Optional

from src.core.models import Shipment, EquipmentDecision, SupplierQuote


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