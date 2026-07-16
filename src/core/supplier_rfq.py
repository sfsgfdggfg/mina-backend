from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import uuid4

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
    rfq_id: str = Field(default_factory=lambda: str(uuid4()))
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


SupplierRFQResponseStatus = Literal[
    "quoted",
    "no_capacity",
    "declined",
    "needs_clarification",
]


class SupplierRFQResponse(BaseModel):
    rfq_id: str = Field(default_factory=lambda: str(uuid4()))
    supplier_name: str
    rfq_priority: int
    status: SupplierRFQResponseStatus

    cost: Optional[float] = None
    currency: str = "EUR"
    transit_time: Optional[str] = None
    validity_date: Optional[str] = None
    equipment_type: Optional[str] = None
    notes: Optional[str] = None

    source: Literal["simulation", "email", "portal", "api", "manual"] = "manual"
    received_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def is_price_usable(self) -> bool:
        return (
            self.status == "quoted"
            and self.cost is not None
            and self.cost > 0
        )
