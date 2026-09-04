from __future__ import annotations

from threading import Lock
from typing import Protocol

from src.core.master_data import CustomerMasterProfile, SupplierMasterProfile, normalize_master_text
from src.core.pilot_store import SQLitePilotStore


class MasterDataConflictError(ValueError):
    pass


class MasterDataRepository(Protocol):
    def create_customer(self, profile: CustomerMasterProfile) -> tuple[CustomerMasterProfile, bool]: ...
    def save_customer(self, profile: CustomerMasterProfile) -> CustomerMasterProfile: ...
    def get_customer(self, customer_id: str) -> CustomerMasterProfile | None: ...
    def find_customer_by_entry_id(self, entry_id: str) -> CustomerMasterProfile | None: ...
    def find_customer_by_name(self, name: str) -> CustomerMasterProfile | None: ...
    def list_customers(self) -> list[CustomerMasterProfile]: ...
    def create_supplier(self, profile: SupplierMasterProfile) -> tuple[SupplierMasterProfile, bool]: ...
    def save_supplier(self, profile: SupplierMasterProfile) -> SupplierMasterProfile: ...
    def get_supplier(self, supplier_id: str) -> SupplierMasterProfile | None: ...
    def find_supplier_by_entry_id(self, entry_id: str) -> SupplierMasterProfile | None: ...
    def find_supplier_by_name(self, name: str) -> SupplierMasterProfile | None: ...
    def list_suppliers(self) -> list[SupplierMasterProfile]: ...


def _commercial_payload(model):
    return model.model_dump(mode="json", exclude={"customer_id", "supplier_id", "created_at", "updated_at"})


class InMemoryMasterDataRepository:
    def __init__(self) -> None:
        self.customers = {}
        self.customer_by_entry = {}
        self.customer_by_name = {}
        self.suppliers = {}
        self.supplier_by_entry = {}
        self.supplier_by_name = {}
        self._lock = Lock()

    def create_customer(self, profile):
        with self._lock:
            existing = self.find_customer_by_entry_id(profile.entry_id)
            if existing:
                if _commercial_payload(existing) != _commercial_payload(profile):
                    raise MasterDataConflictError("Customer entry_id reused with different master data.")
                return existing, False
            key = normalize_master_text(profile.customer_name)
            owner = self.customer_by_name.get(key)
            if owner:
                raise MasterDataConflictError("Customer name already exists in master data.")
            self.customers[profile.customer_id] = profile
            self.customer_by_entry[profile.entry_id] = profile.customer_id
            self.customer_by_name[key] = profile.customer_id
            return profile, True

    def save_customer(self, profile):
        current = self.customers.get(profile.customer_id)
        if current is None:
            raise KeyError(profile.customer_id)
        old_key = normalize_master_text(current.customer_name)
        new_key = normalize_master_text(profile.customer_name)
        if old_key != new_key:
            raise MasterDataConflictError("Customer rename is not allowed in P2-03; use a future controlled rename/merge flow.")
        self.customers[profile.customer_id] = profile
        return profile

    def get_customer(self, customer_id): return self.customers.get(customer_id)
    def find_customer_by_entry_id(self, entry_id):
        key = self.customer_by_entry.get(entry_id); return None if key is None else self.customers.get(key)
    def find_customer_by_name(self, name):
        key = self.customer_by_name.get(normalize_master_text(name)); return None if key is None else self.customers.get(key)
    def list_customers(self): return sorted(self.customers.values(), key=lambda x: normalize_master_text(x.customer_name))

    def create_supplier(self, profile):
        with self._lock:
            existing = self.find_supplier_by_entry_id(profile.entry_id)
            if existing:
                if _commercial_payload(existing) != _commercial_payload(profile):
                    raise MasterDataConflictError("Supplier entry_id reused with different master data.")
                return existing, False
            key = normalize_master_text(profile.supplier_name)
            if self.supplier_by_name.get(key):
                raise MasterDataConflictError("Supplier name already exists in master data.")
            self.suppliers[profile.supplier_id] = profile
            self.supplier_by_entry[profile.entry_id] = profile.supplier_id
            self.supplier_by_name[key] = profile.supplier_id
            return profile, True

    def save_supplier(self, profile):
        current = self.suppliers.get(profile.supplier_id)
        if current is None: raise KeyError(profile.supplier_id)
        old_key = normalize_master_text(current.supplier_name); new_key = normalize_master_text(profile.supplier_name)
        if old_key != new_key:
            raise MasterDataConflictError("Supplier rename is not allowed in P2-03; use a future controlled rename/merge flow.")
        self.suppliers[profile.supplier_id] = profile
        return profile

    def get_supplier(self, supplier_id): return self.suppliers.get(supplier_id)
    def find_supplier_by_entry_id(self, entry_id):
        key = self.supplier_by_entry.get(entry_id); return None if key is None else self.suppliers.get(key)
    def find_supplier_by_name(self, name):
        key = self.supplier_by_name.get(normalize_master_text(name)); return None if key is None else self.suppliers.get(key)
    def list_suppliers(self): return sorted(self.suppliers.values(), key=lambda x: normalize_master_text(x.supplier_name))


class SQLiteMasterDataRepository:
    CUSTOMER_NS = "customer_master_profiles"
    CUSTOMER_ENTRY_NS = "customer_master_by_entry"
    CUSTOMER_NAME_NS = "customer_master_by_name"
    SUPPLIER_NS = "supplier_master_profiles"
    SUPPLIER_ENTRY_NS = "supplier_master_by_entry"
    SUPPLIER_NAME_NS = "supplier_master_by_name"

    def __init__(self, store: SQLitePilotStore) -> None:
        self.store = store

    def _get_index(self, namespace, key):
        payload = self.store.get(namespace=namespace, record_key=key)
        return None if payload is None else str(payload.get("record_id") or "")

    def create_customer(self, profile):
        name_key = normalize_master_text(profile.customer_name)
        with self.store.transaction():
            existing = self.find_customer_by_entry_id(profile.entry_id)
            if existing:
                if _commercial_payload(existing) != _commercial_payload(profile):
                    raise MasterDataConflictError("Customer entry_id reused with different master data.")
                return existing, False
            if self.find_customer_by_name(profile.customer_name):
                raise MasterDataConflictError("Customer name already exists in master data.")
            if not self.store.insert_once(namespace=self.CUSTOMER_NS, record_key=profile.customer_id, payload=profile.model_dump(mode="json"), event_type="customer_master_created", entity_type="customer_master"):
                raise MasterDataConflictError("Customer master identifier collision.")
            if not self.store.insert_once(namespace=self.CUSTOMER_ENTRY_NS, record_key=profile.entry_id, payload={"record_id": profile.customer_id}, event_type="customer_master_indexed", entity_type="customer_master_index"):
                raise MasterDataConflictError("Customer master entry identity collision.")
            if not self.store.insert_once(namespace=self.CUSTOMER_NAME_NS, record_key=name_key, payload={"record_id": profile.customer_id}, event_type="customer_master_name_indexed", entity_type="customer_master_index"):
                raise MasterDataConflictError("Customer master name collision.")
        return profile, True

    def save_customer(self, profile):
        current = self.get_customer(profile.customer_id)
        if current is None: raise KeyError(profile.customer_id)
        old_key = normalize_master_text(current.customer_name); new_key = normalize_master_text(profile.customer_name)
        if old_key != new_key:
            raise MasterDataConflictError("Customer rename is not allowed in P2-03; use a future controlled rename/merge flow.")
        with self.store.transaction():
            self.store.upsert(namespace=self.CUSTOMER_NS, record_key=profile.customer_id, payload=profile.model_dump(mode="json"), event_type="customer_master_saved", entity_type="customer_master")
        return self.get_customer(profile.customer_id)

    def get_customer(self, customer_id):
        p=self.store.get(namespace=self.CUSTOMER_NS, record_key=customer_id); return None if p is None else CustomerMasterProfile.model_validate(p)
    def find_customer_by_entry_id(self, entry_id):
        rid=self._get_index(self.CUSTOMER_ENTRY_NS, entry_id); return None if not rid else self.get_customer(rid)
    def find_customer_by_name(self, name):
        rid=self._get_index(self.CUSTOMER_NAME_NS, normalize_master_text(name)); return None if not rid else self.get_customer(rid)
    def list_customers(self): return [CustomerMasterProfile.model_validate(p) for p in self.store.list_all(namespace=self.CUSTOMER_NS)]

    def create_supplier(self, profile):
        name_key=normalize_master_text(profile.supplier_name)
        with self.store.transaction():
            existing = self.find_supplier_by_entry_id(profile.entry_id)
            if existing:
                if _commercial_payload(existing) != _commercial_payload(profile):
                    raise MasterDataConflictError("Supplier entry_id reused with different master data.")
                return existing, False
            if self.find_supplier_by_name(profile.supplier_name):
                raise MasterDataConflictError("Supplier name already exists in master data.")
            if not self.store.insert_once(namespace=self.SUPPLIER_NS, record_key=profile.supplier_id, payload=profile.model_dump(mode="json"), event_type="supplier_master_created", entity_type="supplier_master"):
                raise MasterDataConflictError("Supplier master identifier collision.")
            if not self.store.insert_once(namespace=self.SUPPLIER_ENTRY_NS, record_key=profile.entry_id, payload={"record_id": profile.supplier_id}, event_type="supplier_master_indexed", entity_type="supplier_master_index"):
                raise MasterDataConflictError("Supplier master entry identity collision.")
            if not self.store.insert_once(namespace=self.SUPPLIER_NAME_NS, record_key=name_key, payload={"record_id": profile.supplier_id}, event_type="supplier_master_name_indexed", entity_type="supplier_master_index"):
                raise MasterDataConflictError("Supplier master name collision.")
        return profile, True

    def save_supplier(self, profile):
        current=self.get_supplier(profile.supplier_id)
        if current is None: raise KeyError(profile.supplier_id)
        old_key=normalize_master_text(current.supplier_name); new_key=normalize_master_text(profile.supplier_name)
        if old_key != new_key:
            raise MasterDataConflictError("Supplier rename is not allowed in P2-03; use a future controlled rename/merge flow.")
        with self.store.transaction():
            self.store.upsert(namespace=self.SUPPLIER_NS, record_key=profile.supplier_id, payload=profile.model_dump(mode="json"), event_type="supplier_master_saved", entity_type="supplier_master")
        return self.get_supplier(profile.supplier_id)

    def get_supplier(self, supplier_id):
        p=self.store.get(namespace=self.SUPPLIER_NS, record_key=supplier_id); return None if p is None else SupplierMasterProfile.model_validate(p)
    def find_supplier_by_entry_id(self, entry_id):
        rid=self._get_index(self.SUPPLIER_ENTRY_NS, entry_id); return None if not rid else self.get_supplier(rid)
    def find_supplier_by_name(self, name):
        rid=self._get_index(self.SUPPLIER_NAME_NS, normalize_master_text(name)); return None if not rid else self.get_supplier(rid)
    def list_suppliers(self): return [SupplierMasterProfile.model_validate(p) for p in self.store.list_all(namespace=self.SUPPLIER_NS)]
