from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.air_learning_feedback import AirLearningFeedback
from src.core.pilot_store import SQLitePilotStore


class AirLearningFeedbackConflictError(ValueError):
    pass


def _creation_payload(item: AirLearningFeedback) -> dict:
    return item.model_dump(mode="json", exclude={"feedback_id", "recorded_at"})


class AirLearningFeedbackRepository(Protocol):
    def create(self, item: AirLearningFeedback) -> tuple[AirLearningFeedback, bool]: ...
    def get(self, feedback_id: str) -> AirLearningFeedback | None: ...
    def find_by_entry(self, entry_id: str) -> AirLearningFeedback | None: ...
    def list_for_job(self, job_id: str) -> list[AirLearningFeedback]: ...
    def list_all(self) -> list[AirLearningFeedback]: ...


class InMemoryAirLearningFeedbackRepository:
    def __init__(self) -> None:
        self.items: dict[str, AirLearningFeedback] = {}
        self.by_entry: dict[str, str] = {}
        self._lock = Lock()

    def create(self, item):
        with self._lock:
            existing = self.find_by_entry(item.entry_id)
            if existing is not None:
                if _creation_payload(existing) != _creation_payload(item):
                    raise AirLearningFeedbackConflictError(
                        "Air learning feedback entry_id reused with different evidence."
                    )
                return existing, False
            self.items[item.feedback_id] = item.model_copy(deep=True)
            self.by_entry[item.entry_id] = item.feedback_id
            return item.model_copy(deep=True), True

    def get(self, feedback_id):
        item = self.items.get(feedback_id)
        return None if item is None else item.model_copy(deep=True)

    def find_by_entry(self, entry_id):
        feedback_id = self.by_entry.get(entry_id)
        return None if feedback_id is None else self.get(feedback_id)

    def list_for_job(self, job_id):
        return [item for item in self.list_all() if item.job_id == job_id]

    def list_all(self):
        return [item.model_copy(deep=True) for item in self.items.values()]


class SQLiteAirLearningFeedbackRepository:
    ITEM_NS = "air_learning_feedback"
    ENTRY_NS = "air_learning_feedback_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def create(self, item):
        existing = self.find_by_entry(item.entry_id)
        if existing is not None:
            if _creation_payload(existing) != _creation_payload(item):
                raise AirLearningFeedbackConflictError(
                    "Air learning feedback entry_id reused with different evidence."
                )
            return existing, False
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            if not self.store.insert_once(
                namespace=self.ITEM_NS, record_key=item.feedback_id,
                payload=item.model_dump(mode="json"),
                event_type="air_learning_feedback_created", entity_type="air_learning_feedback",
            ):
                raise AirLearningFeedbackConflictError("Air learning feedback identifier collision.")
            if not self.store.insert_once(
                namespace=self.ENTRY_NS, record_key=item.entry_id,
                payload={"feedback_id": item.feedback_id},
                event_type="air_learning_feedback_indexed", entity_type="air_learning_feedback_index",
            ):
                raise AirLearningFeedbackConflictError("Air learning feedback entry identity collision.")
        return AirLearningFeedback.model_validate(item.model_dump()), True

    def get(self, feedback_id):
        payload = self.store.get(namespace=self.ITEM_NS, record_key=feedback_id)
        return None if payload is None else AirLearningFeedback.model_validate(payload)

    def find_by_entry(self, entry_id):
        payload = self.store.get(namespace=self.ENTRY_NS, record_key=entry_id)
        if payload is None:
            return None
        return self.get(str(payload.get("feedback_id") or ""))

    def list_for_job(self, job_id):
        return [item for item in self.list_all() if item.job_id == job_id]

    def list_all(self):
        return [
            AirLearningFeedback.model_validate(item)
            for item in self.store.list_all(namespace=self.ITEM_NS)
        ]
