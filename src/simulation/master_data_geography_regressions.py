from __future__ import annotations

import json
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from starlette.requests import Request

from src.core.customer_memory import CustomerMemoryProfile
from src.core.master_data import MasterContact, SupplierGeographyCapability
from src.core.master_data_repository import (
    InMemoryMasterDataRepository,
    MasterDataConflictError,
    SQLiteMasterDataRepository,
)
from src.core.master_data_service import (
    bootstrap_legacy_master_data,
    create_customer_master,
    create_supplier_master,
    customer_to_legacy_memory,
    supplier_geography_view,
    supplier_to_legacy_capability,
    update_customer_master,
)
from src.core.pilot_access import route_allowed
from src.core.pilot_store import SQLitePilotStore
from src.core.pricing_policy import PricingFormula
from src.core.supplier_capability_validator import validate_supplier_capabilities_file

NOW = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)


def _contact(email: str) -> MasterContact:
    return MasterContact(contact_name="Pricing", email=email, roles=["pricing"], is_primary=True)


def _supplier_fields(email: str = "pricing@example.invalid") -> dict:
    return {
        "role": "primary",
        "contacts": [_contact(email)],
        "geographies": [
            SupplierGeographyCapability(
                scope_type="country", scope_name="Almanya",
                strength="main_market", source="manual",
            ),
            SupplierGeographyCapability(
                scope_type="region", scope_name="DACH",
                countries=["Almanya", "Avusturya", "İsviçre"],
                strength="strong", source="manual",
            ),
        ],
        "service_types": ["FTL"],
        "equipment_types": ["Tenteli / Curtainsider"],
        "priority_routes": ["Türkiye-Almanya"],
        "reliability_score": 0.9,
        "price_score": 0.8,
        "speed_score": 0.85,
        "notes": "Germany and DACH supplier.",
    }


def evaluate_master_data_geography_regressions() -> dict:
    failures: list[str] = []
    passes: list[str] = []

    def check(condition: bool, label: str) -> None:
        (passes if condition else failures).append(label)

    repo = InMemoryMasterDataRepository()
    customer = create_customer_master(
        repository=repo, entry_id="customer-1", customer_name="Beta Enerji",
        aliases=["Beta Energy"], sales_owner="Sales One",
        trusted_sender_domains=["beta.example"], updated_by="Operator One", created_at=NOW,
    )
    repeated = create_customer_master(
        repository=repo, entry_id="customer-1", customer_name="Beta Enerji",
        aliases=["Beta Energy"], sales_owner="Sales One",
        trusted_sender_domains=["beta.example"], updated_by="Operator One", created_at=NOW,
    )
    check(
        customer.customer_id == repeated.customer_id
        and repo.find_customer_by_name("beta enerji").customer_id == customer.customer_id,
        "customer master creation is idempotent and name indexed",
    )

    try:
        create_customer_master(
            repository=repo, entry_id="customer-2", customer_name="Beta Energy",
            updated_by="Operator One", created_at=NOW,
        )
        alias_blocked = False
    except MasterDataConflictError:
        alias_blocked = True
    check(alias_blocked, "customer master protects names and aliases across profiles")

    updated_customer = update_customer_master(
        repository=repo, customer_id=customer.customer_id, updated_by="Manager One",
        occurred_at=NOW + timedelta(minutes=1), sales_owner="Sales Two",
    )
    try:
        update_customer_master(
            repository=repo, customer_id=customer.customer_id, updated_by="Manager One",
            occurred_at=NOW + timedelta(minutes=2), customer_name="Renamed Customer",
        )
        rename_blocked = False
    except MasterDataConflictError:
        rename_blocked = True
    check(
        updated_customer.sales_owner == "Sales Two" and rename_blocked,
        "customer ownership updates persist while uncontrolled rename is blocked",
    )

    supplier = create_supplier_master(
        repository=repo, entry_id="supplier-1", supplier_name="Anatolia Road",
        updated_by="Operator One", created_at=NOW, **_supplier_fields(),
    )
    germany = supplier_geography_view(supplier, "DE")
    austria = supplier_geography_view(supplier, "Avusturya")
    france = supplier_geography_view(supplier, "Fransa")
    check(
        germany["matched"] and germany["best_strength"] == "main_market"
        and austria["matched"] and austria["best_strength"] == "strong"
        and not france["matched"],
        "supplier geography resolves explicit country aliases and bounded region membership",
    )

    try:
        create_supplier_master(
            repository=repo, entry_id="supplier-2", supplier_name="Other Carrier",
            updated_by="Operator One", created_at=NOW,
            **_supplier_fields(email="pricing@example.invalid"),
        )
        contact_blocked = False
    except MasterDataConflictError:
        contact_blocked = True
    check(contact_blocked, "active supplier contact email cannot belong to two suppliers")

    legacy_customer = CustomerMemoryProfile(
        customer_name="Oğuz Gıda", aliases=["oguz gida"], active=True,
        default_commodity="Meşrubat", default_pickup_country="Türkiye",
        pricing_policy=PricingFormula(method="cost_markup_percentage", value=12),
        operational_notes=["Legacy note"],
    )
    legacy_supplier = {
        "supplier_name": "EuroBridge Logistics", "active": True, "role": "backup",
        "route_regions": ["western_europe"],
        "countries": ["Almanya", "Fransa"], "service_types": ["FTL"],
        "equipment_types": ["Tenteli / Curtainsider"], "special_capabilities": [],
        "priority_routes": ["Türkiye-Almanya"], "reliability_score": 0.8,
        "price_score": 0.9, "speed_score": 0.78,
        "notes": "Legacy supplier.",
        "contacts": [{"contact_name": "RFQ", "email": "rfq@eurobridge.invalid",
                      "role": "pricing", "is_primary": True, "active": True}],
    }
    legacy_repo = InMemoryMasterDataRepository()
    first_bootstrap = bootstrap_legacy_master_data(
        repository=legacy_repo, customer_profiles=[legacy_customer],
        supplier_profiles=[legacy_supplier], updated_by="Importer", occurred_at=NOW,
    )
    second_bootstrap = bootstrap_legacy_master_data(
        repository=legacy_repo, customer_profiles=[legacy_customer],
        supplier_profiles=[legacy_supplier], updated_by="Importer", occurred_at=NOW,
    )
    boot_supplier = legacy_repo.list_suppliers()[0]
    germany_geo = supplier_geography_view(boot_supplier, "Almanya")
    france_geo = supplier_geography_view(boot_supplier, "Fransa")
    check(
        first_bootstrap == {"customer_added": 1, "customer_existing": 0,
                            "supplier_added": 1, "supplier_existing": 0}
        and second_bootstrap == {"customer_added": 0, "customer_existing": 1,
                                 "supplier_added": 0, "supplier_existing": 1}
        and germany_geo["best_strength"] == "main_market"
        and france_geo["best_strength"] == "works"
        and boot_supplier.legacy_region_tags == ["western_europe"],
        "legacy bootstrap is idempotent preserves region tags and derives only explicit route strength",
    )

    drift_customer = legacy_customer.model_copy(
        update={"default_commodity": "Changed Commodity"}
    )
    try:
        bootstrap_legacy_master_data(
            repository=legacy_repo, customer_profiles=[drift_customer],
            supplier_profiles=[legacy_supplier], updated_by="Importer", occurred_at=NOW,
        )
        drift_blocked = False
    except MasterDataConflictError:
        drift_blocked = True
    check(drift_blocked, "legacy bootstrap fails closed when imported master source drifts")

    legacy_customer_projection = customer_to_legacy_memory(legacy_repo.list_customers()[0])
    legacy_supplier_projection = supplier_to_legacy_capability(boot_supplier)
    with tempfile.TemporaryDirectory() as temp_dir:
        supplier_path = Path(temp_dir) / "supplier_capabilities.json"
        supplier_path.write_text(
            json.dumps([legacy_supplier_projection], ensure_ascii=False), encoding="utf-8"
        )
        supplier_validation = validate_supplier_capabilities_file(supplier_path)
    check(
        legacy_customer_projection.customer_name == "Oğuz Gıda"
        and legacy_customer_projection.pricing_policy is not None
        and legacy_customer_projection.pricing_policy.value == 12
        and supplier_validation["valid"]
        and legacy_supplier_projection["countries"] == ["Almanya", "Fransa"],
        "master profiles project back into current customer and supplier pilot contracts",
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "master.sqlite3", retention_days=30)
        sqlite_repo = SQLiteMasterDataRepository(store)
        durable_customer = create_customer_master(
            repository=sqlite_repo, entry_id="durable-customer", customer_name="Durable Customer",
            updated_by="Operator", created_at=NOW,
        )
        durable_supplier = create_supplier_master(
            repository=sqlite_repo, entry_id="durable-supplier", supplier_name="Durable Supplier",
            updated_by="Operator", created_at=NOW, **_supplier_fields(email="durable@example.invalid"),
        )
        store.purge_expired(now=NOW + timedelta(days=60))
        reopened = SQLiteMasterDataRepository(store)
        check(
            reopened.find_customer_by_entry_id("durable-customer").customer_id == durable_customer.customer_id
            and reopened.find_supplier_by_entry_id("durable-supplier").supplier_id == durable_supplier.supplier_id,
            "customer and supplier master records and identity indexes survive ordinary retention purge",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = SQLitePilotStore(Path(temp_dir) / "concurrent-master.sqlite3", retention_days=30)
        sqlite_repo = SQLiteMasterDataRepository(store)
        barrier = threading.Barrier(2)
        ids: list[str] = []
        errors: list[str] = []

        def create_same_customer():
            try:
                barrier.wait()
                item = create_customer_master(
                    repository=sqlite_repo, entry_id="same-entry", customer_name="Concurrent Customer",
                    updated_by="Operator", created_at=NOW,
                )
                ids.append(item.customer_id)
            except Exception as exc:  # pragma: no cover - regression evidence
                errors.append(type(exc).__name__)

        threads = [threading.Thread(target=create_same_customer) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        check(
            not errors and len(ids) == 2 and len(set(ids)) == 1
            and len(sqlite_repo.list_customers()) == 1,
            "concurrent master creation shares one idempotent durable identity",
        )

    import src.api as api
    original_repo = api.master_data_repository
    api_repo = InMemoryMasterDataRepository()
    api.master_data_repository = api_repo
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": []})
    request.state.pilot_operator = "API Operator"
    try:
        api_customer = api.create_customer_master_profile(
            api.CustomerMasterCreateRequest(
                entry_id="api-customer", customer_name="API Customer", sales_owner="Sales API"
            ), request,
        )
        api_supplier = api.create_supplier_master_profile(
            api.SupplierMasterCreateRequest(
                entry_id="api-supplier", supplier_name="API Supplier",
                contacts=[_contact("api-supplier@example.invalid")],
                geographies=[SupplierGeographyCapability(
                    scope_type="region", scope_name="Benelux",
                    countries=["Belçika", "Hollanda", "Lüksemburg"], strength="strong",
                )],
                service_types=["FTL"], equipment_types=["Tenteli / Curtainsider"],
                notes="API supplier.",
            ), request,
        )
        api_geo = api.get_supplier_master_geography(api_supplier["supplier_id"], "NL")
        api_customers = api.list_customer_master_profiles()
        api_suppliers = api.list_supplier_master_profiles()
    finally:
        api.master_data_repository = original_repo
    check(
        api_customer["sales_owner"] == "Sales API"
        and api_geo["matched"] and api_geo["best_strength"] == "strong"
        and len(api_customers["customers"]) == 1 and len(api_suppliers["suppliers"]) == 1,
        "master-data API exposes authenticated customer supplier and geography surfaces",
    )

    from src.core.operational_data import OperationalDataSources
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        customer_path = temp / "customer_memory.json"
        supplier_path = temp / "supplier_capabilities.json"
        customer_path.write_text(
            json.dumps([legacy_customer.model_dump(mode="json")], ensure_ascii=False), encoding="utf-8"
        )
        supplier_path.write_text(
            json.dumps([legacy_supplier], ensure_ascii=False), encoding="utf-8"
        )
        original_repo = api.master_data_repository
        original_sources = api.operational_data_sources
        api.master_data_repository = InMemoryMasterDataRepository()
        api.operational_data_sources = OperationalDataSources(
            provenance_registry_path=temp / "provenance_registry.json",
            customer_memory_path=customer_path, supplier_capabilities_path=supplier_path,
        )
        try:
            api_bootstrap_first = api.bootstrap_master_data_from_legacy(request)
            api_bootstrap_second = api.bootstrap_master_data_from_legacy(request)
        finally:
            api.master_data_repository = original_repo
            api.operational_data_sources = original_sources
    check(
        api_bootstrap_first["customer_added"] == 1
        and api_bootstrap_first["supplier_added"] == 1
        and api_bootstrap_second["customer_existing"] == 1
        and api_bootstrap_second["supplier_existing"] == 1,
        "legacy bootstrap API validates source files and remains idempotent",
    )

    check(
        route_allowed("GET", "/master-data/customers")
        and route_allowed("POST", "/master-data/customers")
        and route_allowed("POST", "/master-data/customers/customer-1")
        and route_allowed("GET", "/master-data/suppliers")
        and route_allowed("POST", "/master-data/suppliers/supplier-1")
        and route_allowed("GET", "/master-data/suppliers/supplier-1/geography")
        and route_allowed("POST", "/master-data/bootstrap/legacy"),
        "pilot access explicitly allows controlled master-data surfaces",
    )

    return {"passed": not failures, "passes": passes, "failures": failures}


if __name__ == "__main__":
    result = evaluate_master_data_geography_regressions()
    for label in result["passes"]: print(f"PASS {label}")
    for label in result["failures"]: print(f"FAIL {label}")
    print("\nMaster data & geography regressions: " + ("PASS" if result["passed"] else "FAIL"))
    raise SystemExit(0 if result["passed"] else 1)
