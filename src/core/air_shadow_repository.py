from __future__ import annotations

from contextlib import nullcontext
from threading import Lock
from typing import Protocol

from src.core.air_shadow import AirModeObservation, AirRateSource
from src.core.pilot_store import SQLitePilotStore


class AirShadowConflictError(ValueError):
    pass


def _creation_payload(model, *, exclude: set[str]) -> dict:
    return model.model_dump(mode="json", exclude=exclude)


class AirShadowRepository(Protocol):
    def create_rate_source(self, source: AirRateSource) -> tuple[AirRateSource, bool]: ...
    def get_rate_source(self, source_id: str) -> AirRateSource | None: ...
    def find_rate_source_by_entry(self, entry_id: str) -> AirRateSource | None: ...
    def list_rate_sources(self) -> list[AirRateSource]: ...
    def create_mode_observation(self, observation: AirModeObservation) -> tuple[AirModeObservation, bool]: ...
    def get_mode_observation(self, observation_id: str) -> AirModeObservation | None: ...
    def find_mode_observation_by_entry(self, entry_id: str) -> AirModeObservation | None: ...
    def list_mode_observations(self) -> list[AirModeObservation]: ...


class InMemoryAirShadowRepository:
    def __init__(self) -> None:
        self.rate_sources: dict[str, AirRateSource] = {}
        self.rate_by_entry: dict[str, str] = {}
        self.mode_observations: dict[str, AirModeObservation] = {}
        self.mode_by_entry: dict[str, str] = {}
        self._lock = Lock()

    def create_rate_source(self, source):
        with self._lock:
            existing = self.find_rate_source_by_entry(source.entry_id)
            if existing is not None:
                if _creation_payload(existing, exclude={"source_id", "recorded_at"}) != _creation_payload(source, exclude={"source_id", "recorded_at"}):
                    raise AirShadowConflictError("Air rate source entry_id reused with different evidence.")
                return existing, False
            self.rate_sources[source.source_id] = source.model_copy(deep=True)
            self.rate_by_entry[source.entry_id] = source.source_id
            return source.model_copy(deep=True), True

    def get_rate_source(self, source_id):
        item = self.rate_sources.get(source_id)
        return None if item is None else item.model_copy(deep=True)

    def find_rate_source_by_entry(self, entry_id):
        source_id = self.rate_by_entry.get(entry_id)
        return None if source_id is None else self.get_rate_source(source_id)

    def list_rate_sources(self):
        return [item.model_copy(deep=True) for item in self.rate_sources.values()]

    def create_mode_observation(self, observation):
        with self._lock:
            existing = self.find_mode_observation_by_entry(observation.entry_id)
            if existing is not None:
                if _creation_payload(existing, exclude={"observation_id", "observed_at"}) != _creation_payload(observation, exclude={"observation_id", "observed_at"}):
                    raise AirShadowConflictError("Air mode observation entry_id reused with different evidence.")
                return existing, False
            self.mode_observations[observation.observation_id] = observation.model_copy(deep=True)
            self.mode_by_entry[observation.entry_id] = observation.observation_id
            return observation.model_copy(deep=True), True

    def get_mode_observation(self, observation_id):
        item = self.mode_observations.get(observation_id)
        return None if item is None else item.model_copy(deep=True)

    def find_mode_observation_by_entry(self, entry_id):
        observation_id = self.mode_by_entry.get(entry_id)
        return None if observation_id is None else self.get_mode_observation(observation_id)

    def list_mode_observations(self):
        return [item.model_copy(deep=True) for item in self.mode_observations.values()]


class SQLiteAirShadowRepository:
    RATE_NS = "air_rate_sources"
    RATE_ENTRY_NS = "air_rate_source_by_entry"
    MODE_NS = "air_mode_observations"
    MODE_ENTRY_NS = "air_mode_observation_by_entry"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def _create_once(self, *, item, item_namespace, entry_namespace, item_id, entry_id, item_event, item_entity):
        scope = nullcontext() if self.store.transaction_active else self.store.transaction()
        with scope:
            existing_index = self.store.get(namespace=entry_namespace, record_key=entry_id)
            if existing_index is not None:
                return str(existing_index.get("record_id") or ""), False
            if not self.store.insert_once(
                namespace=item_namespace, record_key=item_id, payload=item.model_dump(mode="json"),
                event_type=item_event, entity_type=item_entity,
            ):
                raise AirShadowConflictError(f"{item_entity} identifier collision.")
            if not self.store.insert_once(
                namespace=entry_namespace, record_key=entry_id, payload={"record_id": item_id},
                event_type=f"{item_entity}_indexed", entity_type=f"{item_entity}_index",
            ):
                raise AirShadowConflictError(f"{item_entity} entry identity collision.")
            return item_id, True

    def create_rate_source(self, source):
        existing = self.find_rate_source_by_entry(source.entry_id)
        if existing is not None:
            if _creation_payload(existing, exclude={"source_id", "recorded_at"}) != _creation_payload(source, exclude={"source_id", "recorded_at"}):
                raise AirShadowConflictError("Air rate source entry_id reused with different evidence.")
            return existing, False
        record_id, created = self._create_once(
            item=source, item_namespace=self.RATE_NS, entry_namespace=self.RATE_ENTRY_NS,
            item_id=source.source_id, entry_id=source.entry_id,
            item_event="air_rate_source_created", item_entity="air_rate_source",
        )
        stored = self.get_rate_source(record_id)
        if stored is None:
            raise AirShadowConflictError("Air rate source persistence failed.")
        if not created and _creation_payload(stored, exclude={"source_id", "recorded_at"}) != _creation_payload(source, exclude={"source_id", "recorded_at"}):
            raise AirShadowConflictError("Air rate source entry_id reused with different evidence.")
        return stored, created

    def get_rate_source(self, source_id):
        payload = self.store.get(namespace=self.RATE_NS, record_key=source_id)
        return None if payload is None else AirRateSource.model_validate(payload)

    def find_rate_source_by_entry(self, entry_id):
        payload = self.store.get(namespace=self.RATE_ENTRY_NS, record_key=entry_id)
        return None if payload is None else self.get_rate_source(str(payload.get("record_id") or ""))

    def list_rate_sources(self):
        return [AirRateSource.model_validate(item) for item in self.store.list_all(namespace=self.RATE_NS)]

    def create_mode_observation(self, observation):
        existing = self.find_mode_observation_by_entry(observation.entry_id)
        if existing is not None:
            if _creation_payload(existing, exclude={"observation_id", "observed_at"}) != _creation_payload(observation, exclude={"observation_id", "observed_at"}):
                raise AirShadowConflictError("Air mode observation entry_id reused with different evidence.")
            return existing, False
        record_id, created = self._create_once(
            item=observation, item_namespace=self.MODE_NS, entry_namespace=self.MODE_ENTRY_NS,
            item_id=observation.observation_id, entry_id=observation.entry_id,
            item_event="air_mode_observation_created", item_entity="air_mode_observation",
        )
        stored = self.get_mode_observation(record_id)
        if stored is None:
            raise AirShadowConflictError("Air mode observation persistence failed.")
        if not created and _creation_payload(stored, exclude={"observation_id", "observed_at"}) != _creation_payload(observation, exclude={"observation_id", "observed_at"}):
            raise AirShadowConflictError("Air mode observation entry_id reused with different evidence.")
        return stored, created

    def get_mode_observation(self, observation_id):
        payload = self.store.get(namespace=self.MODE_NS, record_key=observation_id)
        return None if payload is None else AirModeObservation.model_validate(payload)

    def find_mode_observation_by_entry(self, entry_id):
        payload = self.store.get(namespace=self.MODE_ENTRY_NS, record_key=entry_id)
        return None if payload is None else self.get_mode_observation(str(payload.get("record_id") or ""))

    def list_mode_observations(self):
        return [AirModeObservation.model_validate(item) for item in self.store.list_all(namespace=self.MODE_NS)]
