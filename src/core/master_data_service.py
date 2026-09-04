from __future__ import annotations

from datetime import datetime, timezone

from src.core.customer_memory import CustomerMemoryProfile
from src.core.master_data import (
    CustomerMasterProfile,
    MasterContact,
    SupplierGeographyCapability,
    SupplierMasterProfile,
    match_supplier_geography,
    normalize_country,
    normalize_master_text,
)
from src.core.master_data_repository import MasterDataConflictError, MasterDataRepository


def aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Master-data timestamps must be timezone-aware.")
    return current.astimezone(timezone.utc)


def actor_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Operator identity is required.")
    return normalized


def _customer_terms(profile: CustomerMasterProfile) -> set[str]:
    return {
        normalize_master_text(item)
        for item in [profile.customer_name, *profile.aliases]
        if item and normalize_master_text(item)
    }


def _validate_customer_identity_uniqueness(
    repository: MasterDataRepository,
    profile: CustomerMasterProfile,
    *,
    excluding_customer_id: str | None = None,
) -> None:
    new_terms = _customer_terms(profile)
    if len(new_terms) != 1 + len({normalize_master_text(a) for a in profile.aliases if a.strip()}):
        raise MasterDataConflictError("Customer name/aliases contain duplicates.")
    for existing in repository.list_customers():
        if existing.customer_id == excluding_customer_id:
            continue
        overlap = new_terms & _customer_terms(existing)
        if overlap:
            raise MasterDataConflictError(
                f"Customer identity term already belongs to {existing.customer_name}: {sorted(overlap)[0]}"
            )


def _validate_supplier_contact_uniqueness(
    repository: MasterDataRepository,
    profile: SupplierMasterProfile,
    *,
    excluding_supplier_id: str | None = None,
) -> None:
    own = {
        c.email.strip().casefold()
        for c in profile.contacts
        if c.active and c.email and c.email.strip()
    }
    if len(own) != len([
        c for c in profile.contacts if c.active and c.email and c.email.strip()
    ]):
        raise MasterDataConflictError("Supplier profile contains duplicate active contact email.")
    for existing in repository.list_suppliers():
        if existing.supplier_id == excluding_supplier_id:
            continue
        other = {
            c.email.strip().casefold()
            for c in existing.contacts
            if c.active and c.email and c.email.strip()
        }
        overlap = own & other
        if overlap:
            raise MasterDataConflictError(
                f"Supplier contact email already belongs to {existing.supplier_name}: {sorted(overlap)[0]}"
            )


def create_customer_master(
    *, repository: MasterDataRepository, entry_id: str, customer_name: str,
    updated_by: str, created_at: datetime | None = None, **fields,
) -> CustomerMasterProfile:
    timestamp = aware_utc(created_at)
    profile = CustomerMasterProfile(
        entry_id=entry_id.strip(), customer_name=customer_name.strip(),
        created_at=timestamp, updated_at=timestamp, updated_by=actor_text(updated_by),
        **fields,
    )
    if repository.find_customer_by_entry_id(profile.entry_id) is not None:
        saved, _ = repository.create_customer(profile)
        return saved
    _validate_customer_identity_uniqueness(repository, profile)
    saved, _ = repository.create_customer(profile)
    return saved


def update_customer_master(
    *, repository: MasterDataRepository, customer_id: str, updated_by: str,
    occurred_at: datetime | None = None, **fields,
) -> CustomerMasterProfile:
    current = repository.get_customer(customer_id)
    if current is None:
        raise KeyError(customer_id)
    timestamp = aware_utc(occurred_at)
    payload = current.model_dump()
    payload.update(fields)
    payload.update({"customer_id": current.customer_id, "entry_id": current.entry_id,
                    "created_at": current.created_at, "updated_at": timestamp,
                    "updated_by": actor_text(updated_by)})
    updated = CustomerMasterProfile.model_validate(payload)
    _validate_customer_identity_uniqueness(repository, updated, excluding_customer_id=customer_id)
    return repository.save_customer(updated)


def create_supplier_master(
    *, repository: MasterDataRepository, entry_id: str, supplier_name: str,
    updated_by: str, created_at: datetime | None = None, **fields,
) -> SupplierMasterProfile:
    timestamp = aware_utc(created_at)
    profile = SupplierMasterProfile(
        entry_id=entry_id.strip(), supplier_name=supplier_name.strip(),
        created_at=timestamp, updated_at=timestamp, updated_by=actor_text(updated_by),
        **fields,
    )
    if repository.find_supplier_by_entry_id(profile.entry_id) is not None:
        saved, _ = repository.create_supplier(profile)
        return saved
    _validate_supplier_contact_uniqueness(repository, profile)
    saved, _ = repository.create_supplier(profile)
    return saved


def update_supplier_master(
    *, repository: MasterDataRepository, supplier_id: str, updated_by: str,
    occurred_at: datetime | None = None, **fields,
) -> SupplierMasterProfile:
    current = repository.get_supplier(supplier_id)
    if current is None:
        raise KeyError(supplier_id)
    timestamp = aware_utc(occurred_at)
    payload = current.model_dump()
    payload.update(fields)
    payload.update({"supplier_id": current.supplier_id, "entry_id": current.entry_id,
                    "created_at": current.created_at, "updated_at": timestamp,
                    "updated_by": actor_text(updated_by)})
    updated = SupplierMasterProfile.model_validate(payload)
    _validate_supplier_contact_uniqueness(repository, updated, excluding_supplier_id=supplier_id)
    return repository.save_supplier(updated)


def customer_from_legacy(
    profile: CustomerMemoryProfile, *, updated_by: str, timestamp: datetime,
) -> CustomerMasterProfile:
    return CustomerMasterProfile(
        entry_id=f"legacy-customer:{normalize_master_text(profile.customer_name)}",
        customer_name=profile.customer_name, active=profile.active, aliases=profile.aliases,
        trusted_sender_addresses=profile.trusted_sender_addresses,
        trusted_sender_domains=profile.trusted_sender_domains,
        default_commodity=profile.default_commodity,
        default_equipment_type=profile.default_equipment_type,
        default_pickup_city=profile.default_pickup_city,
        default_pickup_area=profile.default_pickup_area,
        default_pickup_country=profile.default_pickup_country,
        default_delivery_city=profile.default_delivery_city,
        default_delivery_country=profile.default_delivery_country,
        price_sensitivity=profile.price_sensitivity,
        time_sensitivity=profile.time_sensitivity,
        pricing_policy=profile.pricing_policy,
        operational_notes=profile.operational_notes,
        source="legacy_json", created_at=timestamp, updated_at=timestamp,
        updated_by=updated_by,
    )


def _priority_destination_names(priority_routes: list[str]) -> set[str]:
    destinations = set()
    for route in priority_routes:
        if "-" not in route:
            continue
        destinations.add(normalize_country(route.rsplit("-", 1)[1]))
    return destinations


def supplier_from_legacy(
    raw: dict, *, updated_by: str, timestamp: datetime,
) -> SupplierMasterProfile:
    priority_routes = list(raw.get("priority_routes") or [])
    priority_destinations = _priority_destination_names(priority_routes)
    geographies = []
    for country in raw.get("countries") or []:
        canonical = normalize_country(str(country))
        geographies.append(SupplierGeographyCapability(
            scope_type="country", scope_name=str(country),
            strength="main_market" if canonical in priority_destinations else "works",
            source="legacy_json",
        ))
    contacts = []
    for item in raw.get("contacts") or []:
        role = str(item.get("role") or "other").strip().casefold()
        contact_role = role if role in {"pricing", "operations", "finance", "management"} else "other"
        contacts.append(MasterContact(
            contact_name=item.get("contact_name"), email=item.get("email"),
            roles=[contact_role], is_primary=bool(item.get("is_primary", False)),
            active=bool(item.get("active", True)),
        ))
    return SupplierMasterProfile(
        entry_id=f"legacy-supplier:{normalize_master_text(str(raw['supplier_name']))}",
        supplier_name=str(raw["supplier_name"]), active=bool(raw.get("active", True)),
        role=raw.get("role", "backup"), contacts=contacts, geographies=geographies,
        service_types=list(raw.get("service_types") or []),
        equipment_types=list(raw.get("equipment_types") or []),
        special_capabilities=list(raw.get("special_capabilities") or []),
        priority_routes=priority_routes,
        legacy_region_tags=list(raw.get("route_regions") or []),
        reliability_score=float(raw.get("reliability_score", 0.5)),
        price_score=float(raw.get("price_score", 0.5)),
        speed_score=float(raw.get("speed_score", 0.5)),
        notes=str(raw.get("notes") or "Legacy supplier profile."),
        source="legacy_json", created_at=timestamp, updated_at=timestamp,
        updated_by=updated_by,
    )


def _semantic_master_payload(profile) -> dict:
    return profile.model_dump(
        mode="json",
        exclude={"customer_id", "supplier_id", "created_at", "updated_at", "updated_by"},
    )


def bootstrap_legacy_master_data(
    *, repository: MasterDataRepository, customer_profiles: list[CustomerMemoryProfile],
    supplier_profiles: list[dict], updated_by: str, occurred_at: datetime | None = None,
) -> dict:
    timestamp = aware_utc(occurred_at)
    actor = actor_text(updated_by)
    customer_added = supplier_added = 0
    customer_existing = supplier_existing = 0
    for legacy in customer_profiles:
        profile = customer_from_legacy(legacy, updated_by=actor, timestamp=timestamp)
        existing = repository.find_customer_by_entry_id(profile.entry_id)
        if existing:
            if _semantic_master_payload(existing) != _semantic_master_payload(profile):
                raise MasterDataConflictError(
                    f"Legacy customer master drift detected: {profile.customer_name}"
                )
            customer_existing += 1
            continue
        _validate_customer_identity_uniqueness(repository, profile)
        repository.create_customer(profile); customer_added += 1
    for raw in supplier_profiles:
        profile = supplier_from_legacy(raw, updated_by=actor, timestamp=timestamp)
        existing = repository.find_supplier_by_entry_id(profile.entry_id)
        if existing:
            if _semantic_master_payload(existing) != _semantic_master_payload(profile):
                raise MasterDataConflictError(
                    f"Legacy supplier master drift detected: {profile.supplier_name}"
                )
            supplier_existing += 1
            continue
        _validate_supplier_contact_uniqueness(repository, profile)
        repository.create_supplier(profile); supplier_added += 1
    return {
        "customer_added": customer_added, "customer_existing": customer_existing,
        "supplier_added": supplier_added, "supplier_existing": supplier_existing,
    }


def customer_to_legacy_memory(profile: CustomerMasterProfile) -> CustomerMemoryProfile:
    return CustomerMemoryProfile(
        customer_name=profile.customer_name, active=profile.active, aliases=profile.aliases,
        trusted_sender_addresses=profile.trusted_sender_addresses,
        trusted_sender_domains=profile.trusted_sender_domains,
        default_commodity=profile.default_commodity,
        default_equipment_type=profile.default_equipment_type,
        price_sensitivity=profile.price_sensitivity, time_sensitivity=profile.time_sensitivity,
        pricing_policy=profile.pricing_policy,
        default_pickup_city=profile.default_pickup_city, default_pickup_area=profile.default_pickup_area,
        default_pickup_country=profile.default_pickup_country,
        default_delivery_city=profile.default_delivery_city,
        default_delivery_country=profile.default_delivery_country,
        operational_notes=profile.operational_notes,
        created_at=profile.created_at.isoformat(), last_updated_at=profile.updated_at.isoformat(),
        last_updated_by=profile.updated_by, change_note="Projected from master data.",
    )


def supplier_to_legacy_capability(profile: SupplierMasterProfile) -> dict:
    countries = [geo.scope_name for geo in profile.geographies if geo.scope_type == "country"]
    route_regions = list(profile.legacy_region_tags)
    route_regions.extend(
        geo.scope_name for geo in profile.geographies
        if geo.scope_type == "region" and geo.scope_name not in route_regions
    )
    if not route_regions and countries:
        route_regions = ["explicit_country_scope"]
    contacts = [
        {"contact_name": c.contact_name, "email": c.email,
         "role": c.roles[0] if c.roles else "pricing",
         "is_primary": c.is_primary, "active": c.active}
        for c in profile.contacts if c.email
    ]
    return {
        "supplier_name": profile.supplier_name, "active": profile.active,
        "role": profile.role, "route_regions": route_regions, "countries": countries,
        "service_types": profile.service_types, "equipment_types": profile.equipment_types,
        "special_capabilities": profile.special_capabilities,
        "priority_routes": profile.priority_routes,
        "reliability_score": profile.reliability_score, "price_score": profile.price_score,
        "speed_score": profile.speed_score, "notes": profile.notes, "contacts": contacts,
    }


def supplier_geography_view(profile: SupplierMasterProfile, destination_country: str) -> dict:
    return match_supplier_geography(profile, destination_country).model_dump()
