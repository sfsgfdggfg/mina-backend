from __future__ import annotations

from typing import Protocol
from threading import RLock

from src.core.operation_start import OperationStartMessage
from src.core.pilot_store import SQLitePilotStore


class OperationStartMessageRepository(Protocol):
    def save(self, message: OperationStartMessage) -> OperationStartMessage: ...
    def get(self, message_id: str) -> OperationStartMessage | None: ...
    def list_for_job(self, job_id: str) -> list[OperationStartMessage]: ...
    def list_all(self) -> list[OperationStartMessage]: ...
    def reserve_send(self, message_id: str, *, actor: str, decided_at) -> OperationStartMessage | None: ...


class InMemoryOperationStartMessageRepository:
    def __init__(self) -> None:
        self.items: dict[str, OperationStartMessage] = {}
        self._lock = RLock()

    def save(self, message: OperationStartMessage) -> OperationStartMessage:
        self.items[message.message_id] = message.model_copy(deep=True)
        return message.model_copy(deep=True)

    def get(self, message_id: str) -> OperationStartMessage | None:
        item = self.items.get(message_id)
        return None if item is None else item.model_copy(deep=True)

    def list_for_job(self, job_id: str) -> list[OperationStartMessage]:
        return [item.model_copy(deep=True) for item in self.items.values() if item.job_id == job_id]

    def list_all(self) -> list[OperationStartMessage]:
        return [item.model_copy(deep=True) for item in self.items.values()]

    def reserve_send(self, message_id: str, *, actor: str, decided_at) -> OperationStartMessage | None:
        with self._lock:
            current = self.items.get(message_id)
            if current is None or current.status not in {"approval_required", "failed"}:
                return None
            reserved = current.model_copy(update={
                "status": "sending", "decided_at": decided_at, "decided_by": actor,
                "decision_reason": "send_reserved",
            })
            self.items[message_id] = reserved.model_copy(deep=True)
            return reserved.model_copy(deep=True)


class SQLiteOperationStartMessageRepository:
    NAMESPACE = "operation_start_messages"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def save(self, message: OperationStartMessage) -> OperationStartMessage:
        payload = message.model_dump(mode="json")
        self.store.upsert(
            namespace=self.NAMESPACE, record_key=message.message_id, payload=payload,
            event_type="operation_start_message_saved", entity_type="operation_start_message",
        )
        return OperationStartMessage.model_validate(payload)

    def get(self, message_id: str) -> OperationStartMessage | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=message_id)
        return None if payload is None else OperationStartMessage.model_validate(payload)

    def list_for_job(self, job_id: str) -> list[OperationStartMessage]:
        return [item for item in self.list_all() if item.job_id == job_id]

    def list_all(self) -> list[OperationStartMessage]:
        return [
            OperationStartMessage.model_validate(payload)
            for payload in self.store.list_all(namespace=self.NAMESPACE)
        ]

    def reserve_send(self, message_id: str, *, actor: str, decided_at) -> OperationStartMessage | None:
        scope = self.store.transaction() if not self.store.transaction_active else None
        if scope is None:
            return self._reserve_send_in_transaction(message_id, actor=actor, decided_at=decided_at)
        with scope:
            return self._reserve_send_in_transaction(message_id, actor=actor, decided_at=decided_at)

    def _reserve_send_in_transaction(self, message_id: str, *, actor: str, decided_at) -> OperationStartMessage | None:
        current = self.get(message_id)
        if current is None or current.status not in {"approval_required", "failed"}:
            return None
        reserved = current.model_copy(update={
            "status": "sending", "decided_at": decided_at, "decided_by": actor,
            "decision_reason": "send_reserved",
        })
        payload = reserved.model_dump(mode="json")
        self.store.upsert(
            namespace=self.NAMESPACE, record_key=message_id, payload=payload,
            event_type="operation_start_send_reserved", entity_type="operation_start_message",
        )
        return OperationStartMessage.model_validate(payload)
