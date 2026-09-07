from __future__ import annotations

from typing import Protocol

from src.core.performance_settings import PerformanceSettings
from src.core.pilot_store import SQLitePilotStore


class PerformanceSettingsRepository(Protocol):
    def get(self) -> PerformanceSettings | None: ...
    def save(self, settings: PerformanceSettings) -> PerformanceSettings: ...


class InMemoryPerformanceSettingsRepository:
    def __init__(self) -> None:
        self.current: PerformanceSettings | None = None

    def get(self) -> PerformanceSettings | None:
        return None if self.current is None else self.current.model_copy(deep=True)

    def save(self, settings: PerformanceSettings) -> PerformanceSettings:
        self.current = settings.model_copy(deep=True)
        return self.current.model_copy(deep=True)


class SQLitePerformanceSettingsRepository:
    NAMESPACE = "agency_performance_settings"
    KEY = "current"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get(self) -> PerformanceSettings | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=self.KEY)
        return None if payload is None else PerformanceSettings.model_validate(payload)

    def save(self, settings: PerformanceSettings) -> PerformanceSettings:
        payload = settings.model_dump(mode="json")
        self.store.upsert(
            namespace=self.NAMESPACE, record_key=self.KEY, payload=payload,
            event_type="agency_performance_settings_saved", entity_type="agency_performance_settings",
        )
        return PerformanceSettings.model_validate(payload)
