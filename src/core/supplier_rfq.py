from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


SupplierRFQStatus = Literal[
    "draft",
    "approved",
    "sent",
    "awaiting_response",
    "responded",
    "expired",
    "cancelled",
]


class SupplierContact(BaseModel):
    contact_name: Optional[str] = None
    email: str
    role: str = "pricing"
    is_primary: bool = False
    active: bool = True


class SupplierRFQDraft(BaseModel):
    supplier_name: str
    priority: int
    recipient_email: Optional[str] = None
    subject: str
    body: str
    status: SupplierRFQStatus = "draft"
    created_at: datetime = Field(default_factory=datetime.utcnow)
    sent_at: Optional[datetime] = None
    responded_at: Optional[datetime] = None
    source: str = "supplier_rfq_generator"

    @property
    def has_recipient(self) -> bool:
        return bool(self.recipient_email)
