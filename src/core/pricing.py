from decimal import Decimal, ROUND_CEILING

from src.core.models import SupplierQuote, CustomerQuote


def calculate_customer_quote(
    supplier_quote: SupplierQuote,
    markup_type: str = "percentage",
    markup_value: float = 15.0,
    *,
    margin_type: str | None = None,
    margin_value: float | None = None,
) -> CustomerQuote:
    """
    Customer Quote Calculator v1.

    Default:
    supplier cost + %15 markup on cost

    margin_type and margin_value remain accepted as deprecated keyword aliases.
    """

    if margin_type is not None:
        markup_type = margin_type

    if margin_value is not None:
        markup_value = margin_value

    supplier_cost = Decimal(str(supplier_quote.cost))
    markup_amount = Decimal(str(markup_value))

    if markup_type == "percentage":
        final_price = supplier_cost * (
            Decimal("1") + markup_amount / Decimal("100")
        )

    elif markup_type == "fixed":
        final_price = supplier_cost + markup_amount

    elif markup_type == "manual":
        final_price = markup_amount

    else:
        raise ValueError(f"Unsupported markup type: {markup_type}")

    # Round upward to nearest 10 EUR for commercial readability
    final_price = (
        final_price / Decimal("10")
    ).to_integral_value(rounding=ROUND_CEILING) * Decimal("10")

    return CustomerQuote(
        supplier_cost=supplier_quote.cost,
        markup_type=markup_type,
        markup_value=markup_value,
        final_price=float(final_price),
        currency=supplier_quote.currency,
    )
