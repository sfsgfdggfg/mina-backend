from __future__ import annotations

from threading import Lock
from typing import Protocol

from src.core.automation_policy import AgencyAutomationPolicy
from src.core.pilot_store import SQLitePilotStore


class AgencyAutomationPolicyRepository(Protocol):
    def get(self) -> AgencyAutomationPolicy | None: ...
    def save(self, policy: AgencyAutomationPolicy) -> AgencyAutomationPolicy: ...


class InMemoryAgencyAutomationPolicyRepository:
    def __init__(self) -> None:
        self._policy: AgencyAutomationPolicy | None = None
        self._lock = Lock()

    def get(self) -> AgencyAutomationPolicy | None:
        return self._policy

    def save(self, policy: AgencyAutomationPolicy) -> AgencyAutomationPolicy:
        with self._lock:
            self._policy = policy
            return policy


class SQLiteAgencyAutomationPolicyRepository:
    NAMESPACE = "agency_automation_policy"
    RECORD_KEY = "current"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get(self) -> AgencyAutomationPolicy | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=self.RECORD_KEY)
        return None if payload is None else AgencyAutomationPolicy.model_validate(payload)

    def save(self, policy: AgencyAutomationPolicy) -> AgencyAutomationPolicy:
        self.store.upsert(
            namespace=self.NAMESPACE,
            record_key=self.RECORD_KEY,
            payload=policy.model_dump(mode="json"),
            event_type="agency_automation_policy_saved",
            entity_type="agency_automation_policy",
        )
        stored = self.store.get(namespace=self.NAMESPACE, record_key=self.RECORD_KEY)
        return AgencyAutomationPolicy.model_validate(stored)
