from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


InboundReviewStatus = Literal["pending", "resolved", "dismissed"]
InboundReviewResolution = Literal[
    "existing_customer",
    "new_customer",
    "existing_supplier",
    "new_supplier",
    "irrelevant",
]


class InboundSenderReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str = Field(default_factory=lambda: str(uuid4()))
    provider: str = Field(min_length=1, max_length=80)
    mailbox_id: str = Field(min_length=1, max_length=320)
    external_message_id: str = Field(min_length=1, max_length=500)
    message_key_sha256: str = Field(min_length=64, max_length=64)
    sender_address: str = Field(min_length=3, max_length=320)
    sender_name: str | None = Field(default=None, max_length=300)
    subject: str | None = Field(default=None, max_length=500)
    received_at: datetime
    reason_code: str = Field(min_length=1, max_length=200)
    result_type: str = Field(min_length=1, max_length=200)
    status: InboundReviewStatus = "pending"
    created_at: datetime
    updated_at: datetime
    resolution: InboundReviewResolution | None = None
    resolved_subject_type: Literal["customer", "supplier"] | None = None
    resolved_subject_id: str | None = Field(default=None, max_length=120)
    resolved_subject_label: str | None = Field(default=None, max_length=240)
    resolved_by: str | None = Field(default=None, max_length=200)
    resolution_note: str | None = Field(default=None, max_length=1000)
    resolved_at: datetime | None = None
    reprocess_result_type: str | None = Field(default=None, max_length=200)
    reprocess_ingestion_status: str | None = Field(default=None, max_length=200)
    reprocess_reason_code: str | None = Field(default=None, max_length=200)

    @field_validator("provider", "mailbox_id", "sender_address", mode="before")
    @classmethod
    def normalize_identity(cls, value):
        return str(value or "").strip().casefold()

    @field_validator("received_at", "created_at", "updated_at", "resolved_at")
    @classmethod
    def require_aware_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Inbound sender review timestamps must be timezone-aware.")
        return value

    @field_validator("message_key_sha256")
    @classmethod
    def validate_sha256(cls, value):
        item = str(value).strip().casefold()
        if len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item):
            raise ValueError("Inbound sender review message key must be SHA-256 hex.")
        return item


def inbound_review_message_hash(message_key: str) -> str:
    return hashlib.sha256(message_key.encode("utf-8")).hexdigest()
