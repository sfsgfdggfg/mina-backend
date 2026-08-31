from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from src.core.models import CustomerQuote, SupplierQuote
from src.core.pricing_policy import PricingPolicyResolution


def _apply_rounding(
    amount: Decimal,
    *,
    mode: str,
    increment: float | None,
) -> Decimal:
    if mode == "none" or increment is None:
        return amount

    step = Decimal(str(increment))
    units = amount / step
    if mode == "up":
        rounded_units = units.to_integral_value(rounding=ROUND_CEILING)
    elif mode == "nearest":
        rounded_units = units.to_integral_value(rounding=ROUND_HALF_UP)
    else:
        raise ValueError(f"Unsupported rounding mode: {mode}")
    return rounded_units * step


def calculate_customer_quote(
    supplier_quote: SupplierQuote,
    pricing_policy: PricingPolicyResolution,
) -> CustomerQuote:
    """Calculate a customer quote from an explicitly resolved pricing policy."""

    if not pricing_policy.resolved or pricing_policy.formula is None:
        raise ValueError("A resolved pricing policy is required.")

    supplier_cost = Decimal(str(supplier_quote.cost))
    method = pricing_policy.formula.method
    value = Decimal(str(pricing_policy.formula.value))

    if method == "cost_markup_percentage":
        final_price = supplier_cost * (Decimal("1") + value / Decimal("100"))
    elif method == "gross_margin_percentage":
        final_price = supplier_cost / (Decimal("1") - value / Decimal("100"))
    elif method == "fixed_profit":
        final_price = supplier_cost + value
    elif method == "manual_sell_price":
        final_price = value
    else:
        raise ValueError(f"Unsupported pricing method: {method}")

    if method != "manual_sell_price":
        final_price = _apply_rounding(
            final_price,
            mode=pricing_policy.rounding.mode,
            increment=pricing_policy.rounding.increment,
        )

    return CustomerQuote(
        supplier_cost=supplier_quote.cost,
        markup_type=method,
        markup_value=float(value),
        final_price=float(final_price),
        currency=supplier_quote.currency,
        pricing_policy=pricing_policy,
    )
