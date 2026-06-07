import json
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, List
from src.core.models import Shipment
from datetime import datetime, timezone


CUSTOMER_MEMORY_FILE = Path("data/customer_memory.json")


class CustomerMemoryProfile(BaseModel):
    customer_name: str
    active: bool = True
    aliases: List[str] = Field(default_factory=list)

    default_commodity: Optional[str] = None
    default_equipment_type: Optional[str] = None

    price_sensitivity: Optional[str] = None
    time_sensitivity: Optional[str] = None

    default_pickup_city: Optional[str] = None
    default_pickup_area: Optional[str] = None
    default_pickup_country: Optional[str] = None

    default_delivery_city: Optional[str] = None
    default_delivery_country: Optional[str] = None

    created_at: Optional[str] = None
    last_updated_at: Optional[str] = None
    last_updated_by: Optional[str] = None
    change_note: Optional[str] = None

    operational_notes: List[str] = Field(default_factory=list)


class CustomerMemoryResult(BaseModel):
    matched: bool = False
    profile: Optional[CustomerMemoryProfile] = None
    notes_applied: List[str] = Field(default_factory=list)
    source: str = "customer_memory"
    matched_by: Optional[str] = None

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def load_customer_memory() -> List[CustomerMemoryProfile]:
    """
    Loads customer memory profiles from data/customer_memory.json.
    """

    if not CUSTOMER_MEMORY_FILE.exists():
        return []

    with CUSTOMER_MEMORY_FILE.open("r", encoding="utf-8") as file:
        raw_profiles = json.load(file)

    return [
        CustomerMemoryProfile(**profile)
        for profile in raw_profiles
    ]


def normalize_lookup_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    cleaned = value.strip().lower()

    invalid_lookup_values = {
        "",
        "-",
        "/",
        ".",
        ",",
        "unknown customer",
        "unknown",
        "none",
        "null",
        "müşteri",
        "firma",
        "şirket",
        "customer",
        "company",
        "client",
        "sender",
        "gönderen",
        "test",
    }

    if cleaned in invalid_lookup_values:
        return None

    return cleaned


def find_customer_profile(customer_name: Optional[str]) -> Optional[CustomerMemoryProfile]:
    normalized_name = normalize_lookup_text(customer_name)

    if not normalized_name:
        return None

    customer_memory = load_customer_memory()

    for profile in customer_memory:
        if not profile.active:
            continue

        names_to_check = [
            normalize_lookup_text(profile.customer_name),
            *[
                normalize_lookup_text(alias)
                for alias in profile.aliases
            ],
        ]

        names_to_check = [
            name for name in names_to_check
            if name
        ]

        if normalized_name in names_to_check:
            return profile

    return None


def find_customer_profile_in_text(text: Optional[str]) -> Optional[CustomerMemoryProfile]:
    if not text:
        return None

    normalized_text = text.lower()
    customer_memory = load_customer_memory()

    for profile in customer_memory:
        names_to_check = [
            normalize_lookup_text(profile.customer_name),
            *[
                normalize_lookup_text(alias)
                for alias in profile.aliases
            ],
        ]

        names_to_check = [
            name for name in names_to_check
            if name
        ]

        for name in names_to_check:
            if name in normalized_text:
                return profile

    return None


def enrich_shipment_with_customer_memory(
    shipment: Shipment,
    email_text: Optional[str] = None,
) -> CustomerMemoryResult:
    """
    Customer Memory v1.

    Matching order:
    1. shipment.customer_name
    2. raw email text aliases

    Customer profiles are loaded from data/customer_memory.json.
    """

    matched_by = None

    profile = find_customer_profile(shipment.customer_name)

    if profile:
        matched_by = "shipment.customer_name"

    if not profile and email_text:
        profile = find_customer_profile_in_text(email_text)
        if profile:
            matched_by = "email_text"

    if not profile:
        return CustomerMemoryResult(
            matched=False,
            profile=None,
            notes_applied=[],
            source="customer_memory",
            matched_by=None,
        )

    notes_applied = []

    shipment.customer_name = profile.customer_name

    if not shipment.commodity and profile.default_commodity:
        shipment.commodity = profile.default_commodity
        notes_applied.append(
            f"Ürün müşteri hafızasından tamamlandı: {profile.default_commodity}"
        )

    if not shipment.equipment_type and profile.default_equipment_type:
        shipment.equipment_type = profile.default_equipment_type
        notes_applied.append(
            f"Varsayılan ekipman müşteri hafızasından geldi: {profile.default_equipment_type}"
        )

    if not shipment.pickup_city and profile.default_pickup_city:
        shipment.pickup_city = profile.default_pickup_city
        notes_applied.append(
            f"Yükleme şehri müşteri hafızasından tamamlandı: {profile.default_pickup_city}"
        )

    if not shipment.pickup_area and profile.default_pickup_area:
        shipment.pickup_area = profile.default_pickup_area
        notes_applied.append(
            f"Yükleme bölgesi müşteri hafızasından tamamlandı: {profile.default_pickup_area}"
        )

    if not shipment.pickup_country and profile.default_pickup_country:
        shipment.pickup_country = profile.default_pickup_country
        notes_applied.append(
            f"Yükleme ülkesi müşteri hafızasından tamamlandı: {profile.default_pickup_country}"
        )

    if not shipment.delivery_city and profile.default_delivery_city:
        shipment.delivery_city = profile.default_delivery_city
        notes_applied.append(
            f"Teslim şehri müşteri hafızasından tamamlandı: {profile.default_delivery_city}"
        )

    if not shipment.delivery_country and profile.default_delivery_country:
        shipment.delivery_country = profile.default_delivery_country
        notes_applied.append(
            f"Teslim ülkesi müşteri hafızasından tamamlandı: {profile.default_delivery_country}"
        )

    notes_applied.extend(profile.operational_notes)

    return CustomerMemoryResult(
        matched=True,
        profile=profile,
        notes_applied=notes_applied,
        source="customer_memory",
        matched_by=matched_by,
    )

def normalize_alias(value: str) -> str:
    return value.strip().lower()

def save_customer_profile(profile: CustomerMemoryProfile) -> CustomerMemoryProfile:
    """
    Adds a new customer profile to data/customer_memory.json.

    Protection rules:
    - customer_name cannot already exist
    - aliases cannot duplicate within the same profile
    - aliases cannot already belong to another customer
    """

    customer_memory = load_customer_memory()

    new_customer_name = normalize_alias(profile.customer_name)

    if not new_customer_name:
        raise ValueError("Customer name is required.")

    existing_customer_names = [
        normalize_alias(existing_profile.customer_name)
        for existing_profile in customer_memory
    ]

    if new_customer_name in existing_customer_names:
        raise ValueError(f"Customer already exists: {profile.customer_name}")

    normalized_new_aliases = [
        normalize_alias(alias)
        for alias in profile.aliases
        if normalize_alias(alias)
    ]

    if len(normalized_new_aliases) != len(set(normalized_new_aliases)):
        raise ValueError("Duplicate aliases found in the new customer profile.")

    existing_alias_map = {}

    for existing_profile in customer_memory:
        existing_names_and_aliases = [
            existing_profile.customer_name,
            *existing_profile.aliases,
        ]

        for alias in existing_names_and_aliases:
            normalized_existing_alias = normalize_alias(alias)

            if normalized_existing_alias:
                existing_alias_map[normalized_existing_alias] = existing_profile.customer_name

    for alias in normalized_new_aliases:
        if alias in existing_alias_map:
            existing_customer = existing_alias_map[alias]
            raise ValueError(
                f"Alias '{alias}' already belongs to customer: {existing_customer}"
            )

    timestamp = now_iso()

    profile.created_at = profile.created_at or timestamp
    profile.last_updated_at = timestamp
    profile.last_updated_by = profile.last_updated_by or "ui"
    profile.change_note = profile.change_note or "Customer profile created."

    customer_memory.append(profile)

    raw_profiles = [
        existing_profile.model_dump()
        for existing_profile in customer_memory
    ]

    with CUSTOMER_MEMORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            raw_profiles,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return profile

def set_customer_profile_active_status(
    customer_name: str,
    active: bool,
) -> CustomerMemoryProfile:
    """
    Updates active/passive status for a customer profile.
    """

    customer_memory = load_customer_memory()
    normalized_target = normalize_alias(customer_name)

    updated_profile = None

    for profile in customer_memory:
        if normalize_alias(profile.customer_name) == normalized_target:
            profile.active = active
            profile.last_updated_at = now_iso()
            profile.last_updated_by = "ui"
            profile.change_note = (
                "Customer profile activated."
                if active
                else "Customer profile set to passive."
            )
            updated_profile = profile
            break

    if not updated_profile:
        raise ValueError(f"Customer not found: {customer_name}")

    raw_profiles = [
        profile.model_dump()
        for profile in customer_memory
    ]

    with CUSTOMER_MEMORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            raw_profiles,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return updated_profile

def update_customer_profile(
    customer_name: str,
    updated_profile: CustomerMemoryProfile,
) -> CustomerMemoryProfile:
    """
    Updates an existing customer profile in data/customer_memory.json.

    Matching is done by original customer_name.
    Customer name can also be changed, but duplicate names and aliases are protected.
    """

    customer_memory = load_customer_memory()
    normalized_target = normalize_alias(customer_name)

    profile_index = None

    for index, existing_profile in enumerate(customer_memory):
        if normalize_alias(existing_profile.customer_name) == normalized_target:
            profile_index = index
            break

    if profile_index is None:
        raise ValueError(f"Customer not found: {customer_name}")

    new_customer_name = normalize_alias(updated_profile.customer_name)

    if not new_customer_name:
        raise ValueError("Customer name is required.")

    normalized_new_aliases = [
        normalize_alias(alias)
        for alias in updated_profile.aliases
        if normalize_alias(alias)
    ]

    if len(normalized_new_aliases) != len(set(normalized_new_aliases)):
        raise ValueError("Duplicate aliases found in the customer profile.")

    existing_alias_map = {}

    for index, existing_profile in enumerate(customer_memory):
        if index == profile_index:
            continue

        existing_names_and_aliases = [
            existing_profile.customer_name,
            *existing_profile.aliases,
        ]

        for alias in existing_names_and_aliases:
            normalized_existing_alias = normalize_alias(alias)

            if normalized_existing_alias:
                existing_alias_map[normalized_existing_alias] = existing_profile.customer_name

    if new_customer_name in existing_alias_map:
        existing_customer = existing_alias_map[new_customer_name]
        raise ValueError(
            f"Customer name '{updated_profile.customer_name}' conflicts with existing customer or alias: {existing_customer}"
        )

    for alias in normalized_new_aliases:
        if alias in existing_alias_map:
            existing_customer = existing_alias_map[alias]
            raise ValueError(
                f"Alias '{alias}' already belongs to customer: {existing_customer}"
            )

    existing_profile = customer_memory[profile_index]

    updated_profile.created_at = existing_profile.created_at or now_iso()
    updated_profile.last_updated_at = now_iso()
    updated_profile.last_updated_by = updated_profile.last_updated_by or "ui"
    updated_profile.change_note = updated_profile.change_note or "Customer profile updated."

    customer_memory[profile_index] = updated_profile

    raw_profiles = [
        profile.model_dump()
        for profile in customer_memory
    ]

    with CUSTOMER_MEMORY_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            raw_profiles,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return updated_profile