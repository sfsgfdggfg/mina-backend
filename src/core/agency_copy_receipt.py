from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.pilot_store import SQLitePilotStore


class AgencyCopyMailReceipt(BaseModel):
    """Privacy-minimal durable receipt for one agency-authored copied message."""

    model_config = ConfigDict(extra="forbid")

    message_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    body_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sender_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result_type: str = Field(min_length=1, max_length=120)
    ingestion_status: str = Field(min_length=1, max_length=120)
    reason_code: str = Field(min_length=1, max_length=180)
    observed_at: datetime
    job_id: str | None = Field(default=None, max_length=120)
    mina_code: str | None = Field(default=None, max_length=80)
    proposal_id: str | None = Field(default=None, max_length=120)
    counterparty_type: str | None = Field(default=None, max_length=40)

    @field_validator("observed_at")
    @classmethod
    def aware_observed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Agency copy receipt timestamp must be timezone-aware.")
        return value


class AgencyCopyReceiptRepository(Protocol):
    def get(self, message_key_sha256: str) -> AgencyCopyMailReceipt | None: ...
    def save_once(self, receipt: AgencyCopyMailReceipt) -> AgencyCopyMailReceipt: ...


class DuplicateAgencyCopyReceiptError(ValueError):
    pass


class InMemoryAgencyCopyReceiptRepository:
    def __init__(self) -> None:
        self._items: dict[str, AgencyCopyMailReceipt] = {}
        self._lock = Lock()

    def get(self, message_key_sha256: str) -> AgencyCopyMailReceipt | None:
        return self._items.get(message_key_sha256)

    def save_once(self, receipt: AgencyCopyMailReceipt) -> AgencyCopyMailReceipt:
        with self._lock:
            existing = self._items.get(receipt.message_key_sha256)
            if existing is not None:
                if (
                    existing.body_sha256 != receipt.body_sha256
                    or existing.sender_sha256 != receipt.sender_sha256
                ):
                    raise DuplicateAgencyCopyReceiptError(
                        "Agency copy message identity was reused with different evidence."
                    )
                return existing
            self._items[receipt.message_key_sha256] = receipt
            return receipt


class SQLiteAgencyCopyReceiptRepository:
    NAMESPACE = "agency_copy_mail_receipts"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get(self, message_key_sha256: str) -> AgencyCopyMailReceipt | None:
        raw = self.store.get(
            namespace=self.NAMESPACE,
            record_key=message_key_sha256,
        )
        return None if raw is None else AgencyCopyMailReceipt.model_validate(raw)

    def save_once(self, receipt: AgencyCopyMailReceipt) -> AgencyCopyMailReceipt:
        inserted = self.store.insert_once(
            namespace=self.NAMESPACE,
            record_key=receipt.message_key_sha256,
            payload=receipt.model_dump(mode="json"),
            event_type="agency_copy_mail_observed",
            entity_type="agency_copy_mail_receipt",
        )
        if inserted:
            return receipt
        existing = self.get(receipt.message_key_sha256)
        if existing is None:
            raise RuntimeError("Agency copy receipt insert conflict could not be recovered.")
        if (
            existing.body_sha256 != receipt.body_sha256
            or existing.sender_sha256 != receipt.sender_sha256
        ):
            raise DuplicateAgencyCopyReceiptError(
                "Agency copy message identity was reused with different evidence."
            )
        return existing
