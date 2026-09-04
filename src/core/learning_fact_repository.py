from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.learning_fact import LearningFact
from src.core.pilot_store import SQLitePilotStore


class LearningFactConflictError(ValueError):
    pass


class LearningFactRepository(Protocol):
    def create(self, fact: LearningFact) -> tuple[LearningFact, bool]: ...
    def get(self, fact_id: str) -> LearningFact | None: ...
    def find_by_entry_id(self, entry_id: str) -> LearningFact | None: ...
    def save(self, fact: LearningFact) -> LearningFact: ...
    def list_all(self) -> list[LearningFact]: ...


def _creation_payload(fact: LearningFact) -> dict:
    return fact.model_dump(
        mode="json",
        exclude={
            "fact_id", "created_at", "created_by", "updated_at", "reviewed_at", "reviewed_by",
            "review_note", "status", "superseded_by_fact_id", "superseded_at",
            "superseded_by", "supersession_note",
        },
        exclude_computed_fields=True,
    )


class InMemoryLearningFactRepository:
    def __init__(self) -> None:
        self.items: dict[str, LearningFact] = {}
        self.by_entry: dict[str, str] = {}
        self._lock = Lock()

    def create(self, fact):
        with self._lock:
            existing = self.find_by_entry_id(fact.entry_id)
            if existing is not None:
                if _creation_payload(existing) != _creation_payload(fact):
                    raise LearningFactConflictError("Learning fact entry_id reused with different evidence or value.")
                return existing, False
            self.items[fact.fact_id] = fact
            self.by_entry[fact.entry_id] = fact.fact_id
            return fact, True

    def get(self, fact_id): return self.items.get(fact_id)
    def find_by_entry_id(self, entry_id):
        fact_id = self.by_entry.get(entry_id)
        return None if fact_id is None else self.items.get(fact_id)
    def save(self, fact):
        if fact.fact_id not in self.items:
            raise KeyError(fact.fact_id)
        self.items[fact.fact_id] = fact
        return fact
    def list_all(self): return list(self.items.values())


class SQLiteLearningFactRepository:
    FACT_NS = "learning_facts"
    ENTRY_NS = "learning_fact_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, fact):
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            existing = self.find_by_entry_id(fact.entry_id)
            if existing is not None:
                if _creation_payload(existing) != _creation_payload(fact):
                    raise LearningFactConflictError("Learning fact entry_id reused with different evidence or value.")
                return existing, False
            if not self.store.insert_once(
                namespace=self.FACT_NS, record_key=fact.fact_id, payload=fact.model_dump(mode="json"),
                event_type="learning_fact_created", entity_type="learning_fact",
            ):
                raise LearningFactConflictError("Learning fact identifier collision.")
            if not self.store.insert_once(
                namespace=self.ENTRY_NS, record_key=fact.entry_id, payload={"record_id": fact.fact_id},
                event_type="learning_fact_indexed", entity_type="learning_fact_index",
            ):
                raise LearningFactConflictError("Learning fact entry identity collision.")
            return fact, True

    def get(self, fact_id):
        payload = self.store.get(namespace=self.FACT_NS, record_key=fact_id)
        return None if payload is None else LearningFact.model_validate(payload)

    def find_by_entry_id(self, entry_id):
        payload = self.store.get(namespace=self.ENTRY_NS, record_key=entry_id)
        return None if payload is None else self.get(str(payload.get("record_id") or ""))

    def save(self, fact):
        if self.get(fact.fact_id) is None:
            raise KeyError(fact.fact_id)
        self.store.upsert(
            namespace=self.FACT_NS, record_key=fact.fact_id, payload=fact.model_dump(mode="json"),
            event_type="learning_fact_saved", entity_type="learning_fact",
        )
        return self.get(fact.fact_id)

    def list_all(self):
        return [LearningFact.model_validate(p) for p in self.store.list_all(namespace=self.FACT_NS)]
