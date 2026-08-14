import json
import shutil
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional, List
from src.core.models import Shipment
from src.core.extraction_confirmation import require_operational_shipment
from src.core.data_provenance import (
    DataProvenanceBlockedError,
    require_pilot_operational_dataset,
)
from datetime import datetime, timezone
from src.paths import data_path


CUSTOMER_MEMORY_FILE = data_path("customer_memory.json")
CUSTOMER_MEMORY_BACKUP_DIR = data_path("backups")


class CustomerMemoryProfile(BaseModel):
    customer_name: str
    active: bool = True
    aliases: List[str] = Field(default_factory=list)
    trusted_sender_addresses: List[str] = Field(default_factory=list)
    trusted_sender_domains: List[str] = Field(default_factory=list)

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
    candidate_profile: Optional[CustomerMemoryProfile] = None
    notes_applied: List[str] = Field(default_factory=list)
    source: str = "customer_memory"
    matched_by: Optional[str] = None
    identity_status: str = "unmatched"

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
    """
    Deprecated unsafe matcher.

    Raw customer email text is not identity evidence. Kept only as a compatibility
    shim for callers/tests; it deliberately never returns a profile.
    """
    return None


def normalize_sender_address(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    return normalized or None


def sender_matches_profile(
    profile: CustomerMemoryProfile,
    sender_address: Optional[str],
) -> bool:
    normalized_sender = normalize_sender_address(sender_address)
    if not normalized_sender or "@" not in normalized_sender:
        return False

    trusted_addresses = {
        address.strip().lower()
        for address in profile.trusted_sender_addresses
        if address and address.strip()
    }
    if normalized_sender in trusted_addresses:
        return True

    sender_domain = normalized_sender.rsplit("@", 1)[1]
    trusted_domains = {
        domain.strip().lower().lstrip("@")
        for domain in profile.trusted_sender_domains
        if domain and domain.strip()
    }
    return sender_domain in trusted_domains


def enrich_shipment_with_customer_memory(
    shipment: Shipment,
    email_text: Optional[str] = None,
    sender_address: Optional[str] = None,
) -> CustomerMemoryResult:
    """
    Customer Memory identity-safe matching.

    Raw message text is never identity evidence. The candidate customer is based
    on the human-confirmed Shipment customer_name. Automatic enrichment requires
    that the inbound sender matches an explicitly trusted address/domain on the
    customer profile.

    `email_text` remains accepted only for backward call compatibility and is
    intentionally ignored for identity matching.
    """

    require_operational_shipment(shipment)

    try:
        require_pilot_operational_dataset("customer_memory")
    except DataProvenanceBlockedError:
        return CustomerMemoryResult(
            matched=False,
            profile=None,
            candidate_profile=None,
            notes_applied=[],
            source="customer_memory_provenance_blocked",
            matched_by=None,
            identity_status="provenance_unverified",
        )

    profile = find_customer_profile(shipment.customer_name)

    if not profile:
        return CustomerMemoryResult(
            matched=False,
            profile=None,
            candidate_profile=None,
            notes_applied=[],
            source="customer_memory",
            matched_by=None,
            identity_status="unmatched",
        )

    if not sender_matches_profile(profile, sender_address):
        return CustomerMemoryResult(
            matched=False,
            profile=None,
            candidate_profile=profile,
            notes_applied=[],
            source="customer_memory",
            matched_by=None,
            identity_status="sender_verification_required",
        )

    matched_by = "trusted_sender"
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
        candidate_profile=profile,
        notes_applied=notes_applied,
        source="customer_memory",
        matched_by=matched_by,
        identity_status="trusted_sender",
    )

RESERVED_CUSTOMER_MEMORY_TERMS = {
    "test",
    "demo",
    "deneme",
    "sample",
    "example",
    "dummy",
    "sandbox",
    "unknown",
    "unknown customer",
    "müşteri",
    "firma",
    "company",
    "customer",
    "client",
}

def normalize_alias(value: str) -> str:
    return value.strip().lower()

def validate_customer_memory_terms(profile: CustomerMemoryProfile) -> None:
    """
    Prevents unsafe generic customer names or aliases.

    Generic terms like Test, Demo, Deneme can confuse AI parser and customer memory matching.
    """

    customer_name = normalize_alias(profile.customer_name)

    if customer_name in RESERVED_CUSTOMER_MEMORY_TERMS:
        raise ValueError(
            f"Reserved customer name cannot be used: {profile.customer_name}"
        )

    for alias in profile.aliases:
        normalized_alias = normalize_alias(alias)

        if normalized_alias in RESERVED_CUSTOMER_MEMORY_TERMS:
            raise ValueError(
                f"Reserved alias cannot be used: {alias}"
            )

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
    validate_customer_memory_terms(profile)

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
    validate_customer_memory_terms(updated_profile)

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

def create_customer_memory_backup() -> str:
    """
    Creates a timestamped backup of data/customer_memory.json before import.
    """

    backup_dir = CUSTOMER_MEMORY_BACKUP_DIR
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = now_iso().replace(":", "-").replace("+", "_")
    backup_path = backup_dir / f"customer_memory_backup_{timestamp}.json"

    shutil.copyfile(CUSTOMER_MEMORY_FILE, backup_path)

    return str(backup_path)


def apply_customer_memory_import(import_data: dict, updated_by: str = "import") -> dict:
    """
    Applies validated customer memory import data.

    Existing profiles are updated by customer_name.
    New profiles are added.
    A backup is created before writing.
    """

    profiles_data = import_data.get("profiles")

    if not isinstance(profiles_data, list):
        raise ValueError("Invalid import data: profiles must be a list.")

    current_profiles = load_customer_memory()
    backup_path = create_customer_memory_backup()

    current_by_name = {
        normalize_alias(profile.customer_name): profile
        for profile in current_profiles
        if normalize_alias(profile.customer_name)
    }

    imported_profiles = []
    added = []
    updated = []

    for profile_data in profiles_data:
        profile = CustomerMemoryProfile(**profile_data)
        validate_customer_memory_terms(profile)

        normalized_name = normalize_alias(profile.customer_name)

        profile.last_updated_at = now_iso()
        profile.last_updated_by = updated_by
        profile.change_note = "Imported from customer memory JSON."

        if normalized_name in current_by_name:
            existing_profile = current_by_name[normalized_name]

            if not profile.created_at:
                profile.created_at = existing_profile.created_at

            updated.append(profile.customer_name)
        else:
            if not profile.created_at:
                profile.created_at = now_iso()

            added.append(profile.customer_name)

        imported_profiles.append(profile)

    imported_names = {
        normalize_alias(profile.customer_name)
        for profile in imported_profiles
    }

    untouched_profiles = [
        profile
        for profile in current_profiles
        if normalize_alias(profile.customer_name) not in imported_names
    ]

    final_profiles = untouched_profiles + imported_profiles

    CUSTOMER_MEMORY_FILE.write_text(
        json.dumps(
            [profile.model_dump() for profile in final_profiles],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "success": True,
        "backup_path": backup_path,
        "added_count": len(added),
        "updated_count": len(updated),
        "total_profile_count": len(final_profiles),
        "added": added,
        "updated": updated,
    }

def list_customer_memory_backups() -> list[dict]:
    """
    Lists customer memory backup files.
    """

    backup_dir = CUSTOMER_MEMORY_BACKUP_DIR

    if not backup_dir.exists():
        return []

    backup_files = sorted(
        backup_dir.glob("customer_memory_backup_*.json"),
        reverse=True,
    )

    backups = []

    for backup_file in backup_files:
        stat = backup_file.stat()

        backups.append(
            {
                "file_name": backup_file.name,
                "path": str(backup_file),
                "size_bytes": stat.st_size,
                "modified_at": stat.st_mtime,
            }
        )

    return backups


def read_customer_memory_backup(file_name: str) -> dict:
    """
    Reads a backup file from data/backups safely.
    """

    backup_dir = CUSTOMER_MEMORY_BACKUP_DIR
    backup_path = backup_dir / file_name

    if not backup_path.exists():
        raise ValueError(f"Backup file not found: {file_name}")

    if backup_path.parent.resolve() != backup_dir.resolve():
        raise ValueError("Invalid backup file path.")

    raw_content = backup_path.read_text(encoding="utf-8")
    profiles = json.loads(raw_content)

    return {
        "export_type": "customer_memory_backup",
        "file_name": file_name,
        "profile_count": len(profiles) if isinstance(profiles, list) else 0,
        "profiles": profiles,
    }

def restore_customer_memory_from_backup(
    file_name: str,
    updated_by: str = "restore",
) -> dict:
    """
    Restores customer memory from a selected backup file.

    A new backup of the current customer_memory.json is created before restore.
    """

    backup_data = read_customer_memory_backup(file_name)

    profiles_data = backup_data.get("profiles")

    if not isinstance(profiles_data, list):
        raise ValueError("Invalid backup data: profiles must be a list.")

    # Backup current live file before restore
    pre_restore_backup_path = create_customer_memory_backup()

    restored_profiles = []

    for profile_data in profiles_data:
        profile = CustomerMemoryProfile(**profile_data)
        validate_customer_memory_terms(profile)

        profile.last_updated_at = now_iso()
        profile.last_updated_by = updated_by
        profile.change_note = f"Restored from backup: {file_name}"

        if not profile.created_at:
            profile.created_at = now_iso()

        restored_profiles.append(profile)

    CUSTOMER_MEMORY_FILE.write_text(
        json.dumps(
            [profile.model_dump() for profile in restored_profiles],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "success": True,
        "restored_from": file_name,
        "pre_restore_backup_path": pre_restore_backup_path,
        "restored_profile_count": len(restored_profiles),
        "restored_profiles": [
            profile.customer_name
            for profile in restored_profiles
        ],
    }

def build_customer_memory_backup_cleanup_preview(
    keep_latest: int = 10,
) -> dict:
    """
    Builds a cleanup preview for customer memory backup files.

    No files are deleted in this function.
    """

    backups = list_customer_memory_backups()

    if keep_latest < 1:
        keep_latest = 1

    backups_to_keep = backups[:keep_latest]
    cleanup_candidates = backups[keep_latest:]

    return {
        "total_backup_count": len(backups),
        "keep_latest": keep_latest,
        "keep_count": len(backups_to_keep),
        "cleanup_candidate_count": len(cleanup_candidates),
        "backups_to_keep": backups_to_keep,
        "cleanup_candidates": cleanup_candidates,
        "cleanup_enabled": False,
        "message": "Cleanup preview only. No backup files were deleted.",
    }
