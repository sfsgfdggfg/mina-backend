from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from src.core.models import CustomerQuote, QuoteDraft


class QuoteRevision(BaseModel):
    revision_id: str = Field(
        default_factory=lambda: str(uuid4())
    )
    revision_number: int = Field(ge=1)

    previous_approval_id: str
    new_approval_id: str

    previous_quote_draft: QuoteDraft
    revised_quote_draft: QuoteDraft

    previous_customer_quote: CustomerQuote
    revised_customer_quote: CustomerQuote

    changed_fields: list[str] = Field(
        default_factory=list
    )
    consistency_warnings: list[str] = Field(
        default_factory=list
    )

    operator_note: Optional[str] = None
    edited_by: str
    edited_at: datetime

    source: str = "operator_quote_revision"
