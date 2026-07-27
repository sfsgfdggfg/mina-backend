from __future__ import annotations

from typing import Iterable, Optional

from src.core.models import SupplierQuote
from src.core.supplier_rfq import SupplierRFQResponse


def select_supplier_quote_from_responses(
    responses: Iterable[SupplierRFQResponse],
) -> Optional[SupplierQuote]:
    usable_responses = sorted(
        (
            response
            for response in responses
            if response.is_price_usable
        ),
        key=lambda response: response.rfq_priority,
    )

    if not usable_responses:
        return None

    selected = usable_responses[0]

    return SupplierQuote(
        supplier_name=selected.supplier_name,
        cost=float(selected.cost),
        currency=selected.currency,
        transit_time=selected.transit_time,
        notes=selected.notes,
    )


def select_supplier_quote_from_comparisons(
    comparisons,
    responses: Iterable[SupplierRFQResponse],
) -> Optional[SupplierQuote]:
    response_by_rfq_id = {
        response.rfq_id: response
        for response in responses
        if response.is_price_usable
    }

    ranked_comparisons = sorted(
        comparisons,
        key=lambda comparison: (
            -comparison.total_score,
            comparison.priority,
            comparison.cost,
        ),
    )

    for comparison in ranked_comparisons:
        response = response_by_rfq_id.get(comparison.rfq_id)

        if response is None:
            continue

        return SupplierQuote(
            supplier_name=response.supplier_name,
            cost=float(response.cost),
            currency=response.currency,
            transit_time=response.transit_time,
            notes=response.notes,
        )

    return None
