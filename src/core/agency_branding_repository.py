from __future__ import annotations

from threading import Lock
from typing import Protocol

from src.core.agency_branding import AgencyBrandingSettings
from src.core.pilot_store import SQLitePilotStore


class AgencyBrandingRepository(Protocol):
    def get(self) -> AgencyBrandingSettings | None: ...
    def save(self, settings: AgencyBrandingSettings) -> AgencyBrandingSettings: ...


class InMemoryAgencyBrandingRepository:
    def __init__(self) -> None:
        self._settings: AgencyBrandingSettings | None = None
        self._lock = Lock()

    def get(self) -> AgencyBrandingSettings | None:
        return None if self._settings is None else self._settings.model_copy(deep=True)

    def save(self, settings: AgencyBrandingSettings) -> AgencyBrandingSettings:
        with self._lock:
            self._settings = settings.model_copy(deep=True)
            return self._settings.model_copy(deep=True)


class SQLiteAgencyBrandingRepository:
    NAMESPACE = "agency_branding_settings"
    RECORD_KEY = "current"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def get(self) -> AgencyBrandingSettings | None:
        payload = self.store.get(namespace=self.NAMESPACE, record_key=self.RECORD_KEY)
        return None if payload is None else AgencyBrandingSettings.model_validate(payload)

    def save(self, settings: AgencyBrandingSettings) -> AgencyBrandingSettings:
        self.store.upsert(
            namespace=self.NAMESPACE,
            record_key=self.RECORD_KEY,
            payload=settings.model_dump(mode="json"),
            event_type="agency_branding_settings_saved",
            entity_type="agency_branding_settings",
        )
        stored = self.store.get(namespace=self.NAMESPACE, record_key=self.RECORD_KEY)
        return AgencyBrandingSettings.model_validate(stored)
