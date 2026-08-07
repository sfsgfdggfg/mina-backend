from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.models import (
    CustomerQuote,
    QuoteDraft,
    Shipment,
    SupplierQuote,
)
from src.core.quote_approval import QuoteApproval
from src.core.quote_send_safety import QuoteSendSafetyDecision
from src.core.supplier_quote_selection import (
    SupplierQuoteSelectionDecision,
)


class QuoteCase(BaseModel):
    case_id: str = Field(
        default_factory=lambda: str(uuid4())
    )

    shipment: Shipment

    supplier_quote_selection_decision: Optional[
        SupplierQuoteSelectionDecision
    ] = None

    supplier_quote: Optional[SupplierQuote] = None
    customer_quote: Optional[CustomerQuote] = None
    quote_draft: Optional[QuoteDraft] = None

    quote_approval: Optional[QuoteApproval] = None
    quote_send_safety: Optional[QuoteSendSafetyDecision] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    source: str = "quote_case"
