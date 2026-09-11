from __future__ import annotations

from typing import Any

from src.core.supplier_context import shipment_context_keys


def _slug(value: Any) -> str | None:
    if value is None:
        return None
    import re
    import unicodedata
    text = str(value).strip().casefold()
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or None


def customer_quote_context_key(
    shipment: Any, *, currency: str, markup_type: str | None = None,
) -> str | None:
    base = shipment_context_keys(shipment)
    if not base:
        return None
    normalized_currency = _slug(currency)
    if not normalized_currency:
        return None
    key = f"quote|{base[0]}|currency={normalized_currency}"
    normalized_markup = _slug(markup_type)
    if normalized_markup:
        key += f"|markup={normalized_markup}"
    return key
