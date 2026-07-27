from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Optional

from pydantic import BaseModel

from src.core.supplier_rfq import SupplierRFQResponse


class SupplierQuoteComparison(BaseModel):
    rfq_id: str
    supplier_name: str
    priority: int

    cost: float
    currency: str
    transit_time: Optional[str] = None

    supplier_score: float
    commercial_score: float
    operational_score: float
    total_score: float

    source: str = "supplier_quote_comparison_engine"


def build_supplier_quote_comparisons(
    responses: Iterable[SupplierRFQResponse],
    supplier_selection: dict[str, Any],
) -> list[SupplierQuoteComparison]:
    selected_suppliers = {
        supplier.get("supplier_name"): supplier
        for supplier in supplier_selection.get(
            "selected_suppliers",
            [],
        )
        if supplier.get("supplier_name")
    }

    comparisons: list[SupplierQuoteComparison] = []

    for response in responses:
        if not response.is_price_usable:
            continue

        supplier = selected_suppliers.get(response.supplier_name)

        if supplier is None:
            continue

        route_score = float(supplier.get("route_score", 0.0))
        equipment_score = float(
            supplier.get("equipment_score", 0.0)
        )
        risk_score = float(supplier.get("risk_score", 0.0))
        price_score = float(supplier.get("price_score", 0.0))
        speed_score = float(supplier.get("speed_score", 0.0))
        supplier_score = float(supplier.get("total_score", 0.0))

        operational_score = (
            route_score
            + equipment_score
            + risk_score
        ) / 3

        commercial_score = (
            price_score
            + speed_score
        ) / 2

        comparisons.append(
            SupplierQuoteComparison(
                rfq_id=response.rfq_id,
                supplier_name=response.supplier_name,
                priority=response.rfq_priority,
                cost=float(response.cost),
                currency=response.currency,
                transit_time=response.transit_time,
                supplier_score=round(supplier_score, 3),
                commercial_score=round(commercial_score, 3),
                operational_score=round(operational_score, 3),
                total_score=round(supplier_score, 3),
            )
        )

    return comparisons
