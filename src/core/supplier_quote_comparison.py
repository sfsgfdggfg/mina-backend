from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.core.models import Shipment
from src.core.supplier_commercial_safety import (
    evaluate_supplier_commercial_safety,
    parse_transit_time,
)
from src.core.supplier_rfq import (
    SupplierRFQDraft,
    SupplierRFQResponse,
)


class SupplierQuoteComparison(BaseModel):
    rfq_id: str
    supplier_name: str
    priority: int

    cost: float
    currency: str
    transit_time: Optional[str] = None
    transit_days: Optional[int] = None

    commercial_eligible: bool = True
    commercial_rejection_reasons: list[str] = Field(
        default_factory=list
    )
    projected_delivery_date: Optional[date] = None
    delivery_deadline_met: Optional[bool] = None

    supplier_score: float
    commercial_score: float
    operational_score: float
    actual_price_score: float
    transit_score: float
    total_score: float

    source: str = "supplier_quote_comparison_engine"


def _extract_transit_days(
    transit_time: Optional[str],
) -> Optional[int]:
    parsed = parse_transit_time(transit_time)

    return (
        parsed.scoring_days
        if parsed is not None
        else None
    )


def build_supplier_quote_comparisons(
    responses: Iterable[SupplierRFQResponse],
    supplier_selection: dict[str, Any],
    drafts: Iterable[SupplierRFQDraft] | None = None,
    *,
    shipment: Shipment | None = None,
    expected_equipment: str | None = None,
    require_commercial_safety: bool = False,
    as_of: date | None = None,
) -> list[SupplierQuoteComparison]:
    selected_suppliers = {
        supplier.get("supplier_name"): supplier
        for supplier in supplier_selection.get(
            "selected_suppliers",
            [],
        )
        if supplier.get("supplier_name")
    }

    responded_rfq_ids = (
        {
            draft.rfq_id
            for draft in drafts
            if draft.status == "responded"
        }
        if drafts is not None
        else None
    )

    usable_responses = [
        response
        for response in responses
        if response.is_price_usable
        and response.supplier_name in selected_suppliers
        and (
            responded_rfq_ids is None
            or response.rfq_id in responded_rfq_ids
        )
    ]

    commercial_safety = {}

    for response in usable_responses:
        if require_commercial_safety:
            if shipment is None:
                safety = None
            else:
                safety = evaluate_supplier_commercial_safety(
                    response=response,
                    shipment=shipment,
                    expected_equipment=expected_equipment,
                    as_of=as_of,
                )

            commercial_safety[response.rfq_id] = safety
        else:
            commercial_safety[response.rfq_id] = None

    eligible_responses = [
        response
        for response in usable_responses
        if (
            not require_commercial_safety
            or (
                commercial_safety.get(response.rfq_id)
                is not None
                and commercial_safety[
                    response.rfq_id
                ].eligible_for_customer_quote
            )
        )
    ]

    minimum_cost_by_currency: dict[str, float] = {}

    for response in eligible_responses:
        current_minimum = minimum_cost_by_currency.get(
            response.currency
        )
        response_cost = float(response.cost)

        if (
            current_minimum is None
            or response_cost < current_minimum
        ):
            minimum_cost_by_currency[
                response.currency
            ] = response_cost

    transit_days = {
        response.rfq_id: _extract_transit_days(
            response.transit_time
        )
        for response in eligible_responses
    }

    known_transit_days = [
        days
        for days in transit_days.values()
        if days is not None and days > 0
    ]

    minimum_transit_days = (
        min(known_transit_days)
        if known_transit_days
        else None
    )

    comparisons: list[SupplierQuoteComparison] = []

    for response in usable_responses:
        supplier = selected_suppliers.get(
            response.supplier_name
        )

        if supplier is None:
            continue

        safety = commercial_safety.get(
            response.rfq_id
        )

        commercial_eligible = (
            True
            if not require_commercial_safety
            else bool(
                safety is not None
                and safety.eligible_for_customer_quote
            )
        )

        route_score = float(
            supplier.get("route_score", 0.0)
        )
        equipment_score = float(
            supplier.get("equipment_score", 0.0)
        )
        risk_score = float(
            supplier.get("risk_score", 0.0)
        )
        price_score = float(
            supplier.get("price_score", 0.0)
        )
        speed_score = float(
            supplier.get("speed_score", 0.0)
        )
        supplier_score = float(
            supplier.get("total_score", 0.0)
        )

        operational_score = (
            route_score
            + equipment_score
            + risk_score
        ) / 3

        commercial_score = (
            price_score
            + speed_score
        ) / 2

        response_transit_days = (
            safety.transit_days
            if safety is not None
            else _extract_transit_days(
                response.transit_time
            )
        )

        if commercial_eligible:
            minimum_cost = minimum_cost_by_currency[
                response.currency
            ]

            actual_price_score = (
                minimum_cost
                / float(response.cost)
            )

            if (
                minimum_transit_days is None
                or response_transit_days is None
                or response_transit_days <= 0
            ):
                transit_score = 0.5
            else:
                transit_score = (
                    minimum_transit_days
                    / response_transit_days
                )

            total_score = (
                supplier_score * 0.70
                + actual_price_score * 0.20
                + transit_score * 0.10
            )
        else:
            actual_price_score = 0.0
            transit_score = 0.0
            total_score = 0.0

        comparisons.append(
            SupplierQuoteComparison(
                rfq_id=response.rfq_id,
                supplier_name=response.supplier_name,
                priority=response.rfq_priority,
                cost=float(response.cost),
                currency=response.currency,
                transit_time=response.transit_time,
                transit_days=response_transit_days,
                commercial_eligible=commercial_eligible,
                commercial_rejection_reasons=(
                    list(safety.reasons)
                    if safety is not None
                    else []
                ),
                projected_delivery_date=(
                    safety.projected_delivery_date
                    if safety is not None
                    else None
                ),
                delivery_deadline_met=(
                    safety.delivery_deadline_met
                    if safety is not None
                    else None
                ),
                supplier_score=round(
                    supplier_score,
                    3,
                ),
                commercial_score=round(
                    commercial_score,
                    3,
                ),
                operational_score=round(
                    operational_score,
                    3,
                ),
                actual_price_score=round(
                    actual_price_score,
                    3,
                ),
                transit_score=round(
                    transit_score,
                    3,
                ),
                total_score=round(
                    total_score,
                    3,
                ),
            )
        )

    return comparisons
