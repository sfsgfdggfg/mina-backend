from __future__ import annotations

from typing import Iterable, Optional

from pydantic import BaseModel

from src.core.models import SupplierQuote
from src.core.supplier_rfq import SupplierRFQResponse

from src.core.supplier_quote_comparison import (
    SupplierQuoteComparison,
)


class RejectedSupplierQuoteAlternative(BaseModel):
    rfq_id: str
    supplier_name: str
    cost: float
    currency: str
    total_score: float
    price_difference: Optional[float] = None
    score_difference: float
    rejection_reason: str


class SupplierQuoteSelectionDecision(BaseModel):
    selected_supplier: str
    selected_rfq_id: str
    selected_total_score: float
    selection_reason: str
    price_difference: Optional[float] = None
    score_difference: Optional[float] = None
    rejected_alternatives: list[RejectedSupplierQuoteAlternative]
    source: str = "supplier_quote_selection_engine"




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
    comparisons: Iterable[SupplierQuoteComparison],
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


def build_supplier_quote_selection_decision(
    comparisons: Iterable[SupplierQuoteComparison],
) -> Optional[SupplierQuoteSelectionDecision]:
    ranked = sorted(
        comparisons,
        key=lambda comparison: (
            -comparison.total_score,
            comparison.priority,
            comparison.cost,
        ),
    )

    if not ranked:
        return None

    selected = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None

    price_difference = None
    score_difference = None

    if runner_up is not None:
        score_difference = round(
            selected.total_score - runner_up.total_score,
            3,
        )

        if selected.currency == runner_up.currency:
            price_difference = round(
                selected.cost - runner_up.cost,
                2,
            )

    reason_parts = [
        (
            f"{selected.supplier_name}, "
            f"{selected.total_score:.3f} toplam skorla "
            "en yüksek puanı aldı."
        ),
        (
            f"Tedarikçi skoru {selected.supplier_score:.3f}, "
            f"gerçek fiyat skoru "
            f"{selected.actual_price_score:.3f} ve "
            f"transit skoru {selected.transit_score:.3f}."
        ),
    ]

    if runner_up is not None:
        reason_parts.append(
            (
                f"İkinci sıradaki {runner_up.supplier_name} ile "
                f"skor farkı {score_difference:.3f}."
            )
        )

        if price_difference is not None:
            if price_difference > 0:
                reason_parts.append(
                    (
                        f"Seçilen teklif ikinci alternatife göre "
                        f"{price_difference:.2f} "
                        f"{selected.currency} daha pahalı; "
                        "ancak toplam puanı daha yüksek."
                    )
                )
            elif price_difference < 0:
                reason_parts.append(
                    (
                        f"Seçilen teklif ikinci alternatife göre "
                        f"{abs(price_difference):.2f} "
                        f"{selected.currency} daha ucuz."
                    )
                )
            else:
                reason_parts.append(
                    "İlk iki teklifin fiyatı eşit."
                )

    rejected_alternatives = []

    for alternative in ranked[1:]:
        alternative_price_difference = None

        if alternative.currency == selected.currency:
            alternative_price_difference = round(
                alternative.cost - selected.cost,
                2,
            )

        alternative_score_difference = round(
            selected.total_score - alternative.total_score,
            3,
        )

        rejected_alternatives.append(
            RejectedSupplierQuoteAlternative(
                rfq_id=alternative.rfq_id,
                supplier_name=alternative.supplier_name,
                cost=alternative.cost,
                currency=alternative.currency,
                total_score=alternative.total_score,
                price_difference=alternative_price_difference,
                score_difference=alternative_score_difference,
                rejection_reason=(
                    "Toplam seçim skoru seçilen tekliften düşük."
                ),
            )
        )

    return SupplierQuoteSelectionDecision(
        selected_supplier=selected.supplier_name,
        selected_rfq_id=selected.rfq_id,
        selected_total_score=selected.total_score,
        selection_reason=" ".join(reason_parts),
        price_difference=price_difference,
        score_difference=score_difference,
        rejected_alternatives=rejected_alternatives,
    )
