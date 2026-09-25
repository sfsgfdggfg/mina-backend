from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.core.mail import InboundMailEnvelope
from src.core.pilot_store import SQLitePilotStore


MAX_RECENT_INBOUND_HASHES = 10_000


def inbound_message_hash(mail: InboundMailEnvelope) -> str:
    key = mail.message_deduplication_key
    if not key:
        raise ValueError("Automatic inbound polling requires a provider message identity.")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


class InboundAutoPollState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str | None = Field(default=None, max_length=80)
    mailbox_id: str | None = Field(default=None, max_length=320)
    initialized_at: datetime | None = None
    last_completed_at: datetime | None = None
    recent_message_hashes: list[str] = Field(
        default_factory=list, max_length=MAX_RECENT_INBOUND_HASHES
    )

    @field_validator("initialized_at", "last_completed_at")
    @classmethod
    def require_aware_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Inbound auto-poll state timestamps must be timezone-aware.")
        return value

    @field_validator("recent_message_hashes")
    @classmethod
    def validate_hashes(cls, values):
        normalized = []
        for value in values:
            item = str(value).strip().casefold()
            if len(item) != 64 or any(ch not in "0123456789abcdef" for ch in item):
                raise ValueError("Inbound auto-poll message hashes must be SHA-256 hex digests.")
            if item not in normalized:
                normalized.append(item)
        return normalized


class InboundAutoPollStateRepository(Protocol):
    def get(self) -> InboundAutoPollState: ...
    def save(self, state: InboundAutoPollState) -> InboundAutoPollState: ...


class InMemoryInboundAutoPollStateRepository:
    def __init__(self) -> None:
        self._state = InboundAutoPollState()

    def get(self) -> InboundAutoPollState:
        return self._state.model_copy(deep=True)

    def save(self, state: InboundAutoPollState) -> InboundAutoPollState:
        self._state = state.model_copy(deep=True)
        return self.get()


class SQLiteInboundAutoPollStateRepository:
    NAMESPACE = "inbound_auto_poll_state"
    RECORD_KEY = "current"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get(self) -> InboundAutoPollState:
        raw = self.store.get(namespace=self.NAMESPACE, record_key=self.RECORD_KEY)
        if raw is None:
            return InboundAutoPollState()
        return InboundAutoPollState.model_validate(raw)

    def save(self, state: InboundAutoPollState) -> InboundAutoPollState:
        self.store.upsert(
            namespace=self.NAMESPACE,
            record_key=self.RECORD_KEY,
            payload=state.model_dump(mode="json"),
            event_type="inbound_auto_poll_state_changed",
            entity_type="inbound_auto_poll_state",
        )
        return state


def reset_for_mailbox(
    *,
    state: InboundAutoPollState,
    provider: str,
    mailbox_id: str,
) -> InboundAutoPollState:
    if state.provider == provider and state.mailbox_id == mailbox_id:
        return state
    return InboundAutoPollState(provider=provider, mailbox_id=mailbox_id)


def initialize_baseline(
    *,
    state: InboundAutoPollState,
    messages: list[InboundMailEnvelope],
    initialized_at: datetime,
) -> InboundAutoPollState:
    hashes = [inbound_message_hash(mail) for mail in messages]
    return InboundAutoPollState(
        provider=state.provider,
        mailbox_id=state.mailbox_id,
        initialized_at=initialized_at,
        last_completed_at=initialized_at,
        recent_message_hashes=hashes[-MAX_RECENT_INBOUND_HASHES:],
    )


def unseen_messages(
    *,
    state: InboundAutoPollState,
    messages: list[InboundMailEnvelope],
) -> list[InboundMailEnvelope]:
    seen = set(state.recent_message_hashes)
    return [mail for mail in messages if inbound_message_hash(mail) not in seen]


def mark_message_seen(
    *,
    state: InboundAutoPollState,
    mail: InboundMailEnvelope,
    completed_at: datetime,
) -> InboundAutoPollState:
    digest = inbound_message_hash(mail)
    ordered = [*state.recent_message_hashes]
    if digest not in ordered:
        ordered.append(digest)
    return InboundAutoPollState(
        provider=state.provider,
        mailbox_id=state.mailbox_id,
        initialized_at=state.initialized_at,
        last_completed_at=completed_at,
        recent_message_hashes=ordered[-MAX_RECENT_INBOUND_HASHES:],
    )
