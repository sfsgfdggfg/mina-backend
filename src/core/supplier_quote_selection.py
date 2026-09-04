from __future__ import annotations

from typing import Iterable, Optional

from pydantic import BaseModel

from src.core.models import SupplierQuote
from src.core.supplier_rfq import SupplierRFQResponse
from src.core.supplier_price import SupplierPriceOffer

from src.core.supplier_quote_comparison import (
    SupplierQuoteComparison,
)


class RejectedSupplierQuoteAlternative(BaseModel):
    rfq_id: Optional[str] = None
    price_offer_id: Optional[str] = None
    price_source: Optional[str] = None
    supplier_name: str
    cost: float
    currency: str
    total_score: float
    price_difference: Optional[float] = None
    score_difference: float
    rejection_reason: str


class SupplierQuoteSelectionDecision(BaseModel):
    selected_supplier: str
    selected_rfq_id: Optional[str] = None
    selected_price_offer_id: Optional[str] = None
    selected_price_source: Optional[str] = None
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
        validity_date=selected.validity_date,
        vehicle_available_date=selected.vehicle_available_date,
        equipment_type=selected.equipment_type,
        pricing_basis=selected.pricing_basis,
        included_costs=selected.included_costs,
        excluded_costs=selected.excluded_costs,
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
        (
            comparison
            for comparison in comparisons
            if comparison.commercial_eligible
        ),
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
            validity_date=response.validity_date,
            vehicle_available_date=response.vehicle_available_date,
            equipment_type=response.equipment_type,
            pricing_basis=response.pricing_basis,
            included_costs=response.included_costs,
            excluded_costs=response.excluded_costs,
            notes=response.notes,
        )

    return None


def build_supplier_quote_selection_decision(
    comparisons: Iterable[SupplierQuoteComparison],
) -> Optional[SupplierQuoteSelectionDecision]:
    ranked = sorted(
        (
            comparison
            for comparison in comparisons
            if comparison.commercial_eligible
        ),
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
                price_offer_id=alternative.price_offer_id,
                price_source=alternative.price_source,
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
        selected_price_offer_id=selected.price_offer_id,
        selected_price_source=selected.price_source,
        selected_total_score=selected.total_score,
        selection_reason=" ".join(reason_parts),
        price_difference=price_difference,
        score_difference=score_difference,
        rejected_alternatives=rejected_alternatives,
    )


def select_supplier_quote_from_price_offers(
    comparisons: Iterable[SupplierQuoteComparison],
    offers: Iterable[SupplierPriceOffer],
) -> Optional[SupplierQuote]:
    offer_by_id = {offer.offer_id: offer for offer in offers if offer.is_price_usable}
    ranked = sorted(
        (item for item in comparisons if item.commercial_eligible and item.price_offer_id),
        key=lambda item: (-item.total_score, item.priority, item.cost),
    )
    for comparison in ranked:
        offer = offer_by_id.get(str(comparison.price_offer_id))
        if offer is None:
            continue
        return SupplierQuote(
            supplier_name=offer.supplier_name, cost=offer.cost, currency=offer.currency,
            transit_time=offer.transit_time, validity_date=offer.validity_date,
            vehicle_available_date=offer.vehicle_available_date,
            equipment_type=offer.equipment_type, pricing_basis=offer.pricing_basis,
            included_costs=offer.included_costs, excluded_costs=offer.excluded_costs,
            notes=offer.notes, price_offer_id=offer.offer_id,
            price_source=offer.source_type, price_source_reference=offer.source_reference_id,
        )
    return None
