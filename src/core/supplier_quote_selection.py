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
