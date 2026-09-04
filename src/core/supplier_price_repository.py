from __future__ import annotations

from threading import Lock
from typing import Protocol

from src.core.pilot_store import SQLitePilotStore
from src.core.supplier_price import SupplierFixedRate, SupplierPriceOffer




class SupplierPriceIdempotencyConflictError(ValueError):
    pass


def _rate_idempotency_payload(rate: SupplierFixedRate) -> dict:
    return rate.model_dump(
        mode="json", exclude={"rate_id", "recorded_at"}
    )


def _offer_idempotency_payload(offer: SupplierPriceOffer) -> dict:
    return offer.model_dump(
        mode="json", exclude={"offer_id", "recorded_at"}
    )


class SupplierPriceRepository(Protocol):
    def create_fixed_rate(self, rate: SupplierFixedRate) -> tuple[SupplierFixedRate, bool]: ...
    def save_fixed_rate(self, rate: SupplierFixedRate) -> SupplierFixedRate: ...
    def get_fixed_rate(self, rate_id: str) -> SupplierFixedRate | None: ...
    def find_fixed_rate_by_entry_id(self, entry_id: str) -> SupplierFixedRate | None: ...
    def list_fixed_rates(self) -> list[SupplierFixedRate]: ...
    def create_offer(self, offer: SupplierPriceOffer) -> tuple[SupplierPriceOffer, bool]: ...
    def save_offer(self, offer: SupplierPriceOffer) -> SupplierPriceOffer: ...
    def get_offer(self, offer_id: str) -> SupplierPriceOffer | None: ...
    def find_offer_by_entry_id(self, entry_id: str) -> SupplierPriceOffer | None: ...
    def find_offer_for_job_fixed_rate(self, job_id: str, rate_id: str) -> SupplierPriceOffer | None: ...
    def list_offers(self, job_id: str | None = None) -> list[SupplierPriceOffer]: ...


class InMemorySupplierPriceRepository:
    def __init__(self) -> None:
        self._rates: dict[str, SupplierFixedRate] = {}
        self._rate_by_entry: dict[str, str] = {}
        self._offers: dict[str, SupplierPriceOffer] = {}
        self._offer_by_entry: dict[str, str] = {}
        self._offer_by_job_rate: dict[tuple[str, str], str] = {}
        self._lock = Lock()

    def create_fixed_rate(self, rate: SupplierFixedRate) -> tuple[SupplierFixedRate, bool]:
        with self._lock:
            existing_id = self._rate_by_entry.get(rate.entry_id)
            if existing_id is not None:
                existing = self._rates[existing_id]
                if _rate_idempotency_payload(existing) != _rate_idempotency_payload(rate):
                    raise SupplierPriceIdempotencyConflictError(
                        "Fixed-rate entry_id was reused with different commercial data."
                    )
                return existing, False
            self._rates[rate.rate_id] = rate
            self._rate_by_entry[rate.entry_id] = rate.rate_id
            return rate, True

    def save_fixed_rate(self, rate: SupplierFixedRate) -> SupplierFixedRate:
        self._rates[rate.rate_id] = rate
        self._rate_by_entry[rate.entry_id] = rate.rate_id
        return rate

    def get_fixed_rate(self, rate_id: str) -> SupplierFixedRate | None:
        return self._rates.get(rate_id)

    def find_fixed_rate_by_entry_id(self, entry_id: str) -> SupplierFixedRate | None:
        rate_id = self._rate_by_entry.get(entry_id)
        return None if rate_id is None else self._rates.get(rate_id)

    def list_fixed_rates(self) -> list[SupplierFixedRate]:
        return sorted(self._rates.values(), key=lambda item: (item.supplier_name, item.valid_from, item.rate_id))

    def create_offer(self, offer: SupplierPriceOffer) -> tuple[SupplierPriceOffer, bool]:
        with self._lock:
            existing_id = self._offer_by_entry.get(offer.entry_id)
            if existing_id is not None:
                existing = self._offers[existing_id]
                if _offer_idempotency_payload(existing) != _offer_idempotency_payload(offer):
                    raise SupplierPriceIdempotencyConflictError(
                        "Supplier-price entry_id was reused with different commercial data."
                    )
                return existing, False
            if offer.fixed_rate_id:
                key = (offer.mina_job_id, offer.fixed_rate_id)
                existing_rate_offer = self._offer_by_job_rate.get(key)
                if existing_rate_offer is not None:
                    return self._offers[existing_rate_offer], False
            self._offers[offer.offer_id] = offer
            self._offer_by_entry[offer.entry_id] = offer.offer_id
            if offer.fixed_rate_id:
                self._offer_by_job_rate[(offer.mina_job_id, offer.fixed_rate_id)] = offer.offer_id
            return offer, True

    def save_offer(self, offer: SupplierPriceOffer) -> SupplierPriceOffer:
        self._offers[offer.offer_id] = offer
        self._offer_by_entry[offer.entry_id] = offer.offer_id
        if offer.fixed_rate_id:
            self._offer_by_job_rate[(offer.mina_job_id, offer.fixed_rate_id)] = offer.offer_id
        return offer

    def get_offer(self, offer_id: str) -> SupplierPriceOffer | None:
        return self._offers.get(offer_id)

    def find_offer_by_entry_id(self, entry_id: str) -> SupplierPriceOffer | None:
        offer_id = self._offer_by_entry.get(entry_id)
        return None if offer_id is None else self._offers.get(offer_id)

    def find_offer_for_job_fixed_rate(self, job_id: str, rate_id: str) -> SupplierPriceOffer | None:
        offer_id = self._offer_by_job_rate.get((job_id, rate_id))
        return None if offer_id is None else self._offers.get(offer_id)

    def list_offers(self, job_id: str | None = None) -> list[SupplierPriceOffer]:
        offers = list(self._offers.values())
        if job_id is not None:
            offers = [item for item in offers if item.mina_job_id == job_id]
        return sorted(offers, key=lambda item: (item.recorded_at, item.offer_id))


def _payload(model):
    return model.model_dump(mode="json")


class SQLiteSupplierPriceRepository:
    FIXED_RATE_NAMESPACE = "supplier_fixed_rates"
    FIXED_RATE_ENTRY_INDEX_NAMESPACE = "supplier_fixed_rate_by_entry"
    OFFER_NAMESPACE = "supplier_price_offers"
    OFFER_ENTRY_INDEX_NAMESPACE = "supplier_price_offer_by_entry"
    JOB_RATE_INDEX_NAMESPACE = "supplier_price_offer_by_job_fixed_rate"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def _get_indexed(self, namespace: str, key: str, *, rate: bool):
        payload = self.store.get(namespace=namespace, record_key=key)
        if payload is None:
            return None
        record_id = str(payload.get("record_id") or "")
        return self.get_fixed_rate(record_id) if rate else self.get_offer(record_id)

    def create_fixed_rate(self, rate: SupplierFixedRate) -> tuple[SupplierFixedRate, bool]:
        existing = self.find_fixed_rate_by_entry_id(rate.entry_id)
        if existing is not None:
            if _rate_idempotency_payload(existing) != _rate_idempotency_payload(rate):
                raise SupplierPriceIdempotencyConflictError(
                    "Fixed-rate entry_id was reused with different commercial data."
                )
            return existing, False
        if not self.store.insert_once(
            namespace=self.FIXED_RATE_NAMESPACE, record_key=rate.rate_id, payload=_payload(rate),
            event_type="supplier_fixed_rate_created", entity_type="supplier_fixed_rate",
        ):
            raise RuntimeError("Supplier fixed rate identifier collision.")
        if not self.store.insert_once(
            namespace=self.FIXED_RATE_ENTRY_INDEX_NAMESPACE, record_key=rate.entry_id,
            payload={"record_id": rate.rate_id}, event_type="supplier_fixed_rate_indexed",
            entity_type="supplier_fixed_rate_index",
        ):
            raise RuntimeError("Supplier fixed rate entry identity collision.")
        return rate, True

    def save_fixed_rate(self, rate: SupplierFixedRate) -> SupplierFixedRate:
        self.store.upsert(
            namespace=self.FIXED_RATE_NAMESPACE, record_key=rate.rate_id, payload=_payload(rate),
            event_type="supplier_fixed_rate_saved", entity_type="supplier_fixed_rate",
        )
        return SupplierFixedRate.model_validate(
            self.store.get(namespace=self.FIXED_RATE_NAMESPACE, record_key=rate.rate_id)
        )

    def get_fixed_rate(self, rate_id: str) -> SupplierFixedRate | None:
        payload = self.store.get(namespace=self.FIXED_RATE_NAMESPACE, record_key=rate_id)
        return None if payload is None else SupplierFixedRate.model_validate(payload)

    def find_fixed_rate_by_entry_id(self, entry_id: str) -> SupplierFixedRate | None:
        return self._get_indexed(self.FIXED_RATE_ENTRY_INDEX_NAMESPACE, entry_id, rate=True)

    def list_fixed_rates(self) -> list[SupplierFixedRate]:
        return [SupplierFixedRate.model_validate(p) for p in self.store.list_all(namespace=self.FIXED_RATE_NAMESPACE)]

    def create_offer(self, offer: SupplierPriceOffer) -> tuple[SupplierPriceOffer, bool]:
        existing = self.find_offer_by_entry_id(offer.entry_id)
        if existing is not None:
            if _offer_idempotency_payload(existing) != _offer_idempotency_payload(offer):
                raise SupplierPriceIdempotencyConflictError(
                    "Supplier-price entry_id was reused with different commercial data."
                )
            return existing, False
        if offer.fixed_rate_id:
            existing = self.find_offer_for_job_fixed_rate(offer.mina_job_id, offer.fixed_rate_id)
            if existing is not None:
                return existing, False
        if not self.store.insert_once(
            namespace=self.OFFER_NAMESPACE, record_key=offer.offer_id, payload=_payload(offer),
            event_type="supplier_price_offer_created", entity_type="supplier_price_offer",
        ):
            raise RuntimeError("Supplier price offer identifier collision.")
        if not self.store.insert_once(
            namespace=self.OFFER_ENTRY_INDEX_NAMESPACE, record_key=offer.entry_id,
            payload={"record_id": offer.offer_id}, event_type="supplier_price_offer_indexed",
            entity_type="supplier_price_offer_index",
        ):
            raise RuntimeError("Supplier price offer entry identity collision.")
        if offer.fixed_rate_id:
            key = f"{offer.mina_job_id}:{offer.fixed_rate_id}"
            if not self.store.insert_once(
                namespace=self.JOB_RATE_INDEX_NAMESPACE, record_key=key,
                payload={"record_id": offer.offer_id}, event_type="supplier_price_fixed_rate_used",
                entity_type="supplier_price_offer_index",
            ):
                raise RuntimeError("Supplier fixed rate already materialized for this job.")
        return offer, True

    def save_offer(self, offer: SupplierPriceOffer) -> SupplierPriceOffer:
        self.store.upsert(
            namespace=self.OFFER_NAMESPACE, record_key=offer.offer_id, payload=_payload(offer),
            event_type="supplier_price_offer_saved", entity_type="supplier_price_offer",
        )
        return SupplierPriceOffer.model_validate(
            self.store.get(namespace=self.OFFER_NAMESPACE, record_key=offer.offer_id)
        )

    def get_offer(self, offer_id: str) -> SupplierPriceOffer | None:
        payload = self.store.get(namespace=self.OFFER_NAMESPACE, record_key=offer_id)
        return None if payload is None else SupplierPriceOffer.model_validate(payload)

    def find_offer_by_entry_id(self, entry_id: str) -> SupplierPriceOffer | None:
        return self._get_indexed(self.OFFER_ENTRY_INDEX_NAMESPACE, entry_id, rate=False)

    def find_offer_for_job_fixed_rate(self, job_id: str, rate_id: str) -> SupplierPriceOffer | None:
        return self._get_indexed(
            self.JOB_RATE_INDEX_NAMESPACE, f"{job_id}:{rate_id}", rate=False
        )

    def list_offers(self, job_id: str | None = None) -> list[SupplierPriceOffer]:
        offers = [SupplierPriceOffer.model_validate(p) for p in self.store.list_all(namespace=self.OFFER_NAMESPACE)]
        return offers if job_id is None else [item for item in offers if item.mina_job_id == job_id]
