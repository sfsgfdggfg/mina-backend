from src.core.models import SupplierQuote, CustomerQuote


def calculate_customer_quote(
    supplier_quote: SupplierQuote,
    margin_type: str = "percentage",
    margin_value: float = 15.0,
) -> CustomerQuote:
    """
    Customer Quote Calculator v1.

    Default:
    supplier cost + %15 margin
    """

    if margin_type == "percentage":
        final_price = supplier_quote.cost * (1 + margin_value / 100)

    elif margin_type == "fixed":
        final_price = supplier_quote.cost + margin_value

    elif margin_type == "manual":
        final_price = margin_value

    else:
        raise ValueError(f"Unsupported margin type: {margin_type}")

    # Round upward to nearest 10 EUR for commercial readability
    final_price = ((int(final_price) + 9) // 10) * 10

    return CustomerQuote(
        supplier_cost=supplier_quote.cost,
        margin_type=margin_type,
        margin_value=margin_value,
        final_price=final_price,
        currency=supplier_quote.currency,
    )