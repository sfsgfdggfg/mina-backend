"""Guided customer and supplier intake for external pilot data packs."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from src.core.customer_memory_validator import validate_customer_memory_file
from src.core.supplier_capability_validator import (
    validate_supplier_capabilities_file,
)


MAX_ACTIVE_PILOT_CUSTOMERS = 3
MAX_ACTIVE_PILOT_SUPPLIERS = 5


class PilotDataPackIntakeError(ValueError):
    """A guided intake mutation is unsafe or structurally invalid."""


def _read_list(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PilotDataPackIntakeError(
            f"{label} dataset could not be read as JSON."
        ) from exc

    if not isinstance(value, list):
        raise PilotDataPackIntakeError(
            f"{label} dataset root must be a list."
        )

    if not all(isinstance(item, dict) for item in value):
        raise PilotDataPackIntakeError(
            f"{label} dataset contains a non-object entry."
        )

    return [dict(item) for item in value]


def _atomic_write_json(path: Path, value: Any) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_candidate(
    path: Path,
    value: list[dict[str, Any]],
    validator: Callable[[Path], dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.candidate.",
        suffix=".json",
        dir=path.parent,
        text=True,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                value,
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(temporary, 0o600)
        result = validator(temporary)
    finally:
        if temporary.exists():
            temporary.unlink()

    if result.get("valid") is not True:
        errors = result.get("errors") or []
        summary = "; ".join(str(item) for item in errors[:5])
        if len(errors) > 5:
            summary += f"; plus {len(errors) - 5} more error(s)"
        raise PilotDataPackIntakeError(
            f"{label} intake validation failed: {summary}"
        )

    return result


def _ensure_editable(provenance_registry: Path) -> None:
    if provenance_registry.exists() or provenance_registry.is_symlink():
        raise PilotDataPackIntakeError(
            "Pilot data pack is frozen after verification. "
            "Create a new pack version for further edits."
        )


def _clean_many(values: list[str] | None) -> list[str]:
    return [
        value.strip()
        for value in (values or [])
        if isinstance(value, str) and value.strip()
    ]


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def add_customer_profile(
    *,
    customer_memory_path: Path,
    provenance_registry_path: Path,
    customer_name: str,
    active: bool = True,
    aliases: list[str] | None = None,
    trusted_sender_addresses: list[str] | None = None,
    trusted_sender_domains: list[str] | None = None,
    default_commodity: str | None = None,
    default_equipment_type: str | None = None,
    price_sensitivity: str | None = None,
    time_sensitivity: str | None = None,
    default_pickup_city: str | None = None,
    default_pickup_area: str | None = None,
    default_pickup_country: str | None = None,
    default_delivery_city: str | None = None,
    default_delivery_country: str | None = None,
    operational_notes: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_editable(provenance_registry_path)

    normalized_name = customer_name.strip()
    if not normalized_name:
        raise PilotDataPackIntakeError(
            "Customer name must not be empty."
        )

    trusted_addresses = _clean_many(trusted_sender_addresses)
    trusted_domains = _clean_many(trusted_sender_domains)
    if active and not (trusted_addresses or trusted_domains):
        raise PilotDataPackIntakeError(
            "An active pilot customer requires at least one trusted "
            "sender address or domain."
        )

    profiles = _read_list(customer_memory_path, "Customer memory")
    active_count = sum(
        1 for item in profiles if item.get("active") is True
    )
    if active and active_count >= MAX_ACTIVE_PILOT_CUSTOMERS:
        raise PilotDataPackIntakeError(
            "Pilot pack already has the maximum 3 active customers."
        )

    profile = {
        "customer_name": normalized_name,
        "active": bool(active),
        "aliases": _clean_many(aliases),
        "trusted_sender_addresses": trusted_addresses,
        "trusted_sender_domains": trusted_domains,
        "default_commodity": _clean_optional(default_commodity),
        "default_equipment_type": _clean_optional(
            default_equipment_type
        ),
        "price_sensitivity": _clean_optional(price_sensitivity),
        "time_sensitivity": _clean_optional(time_sensitivity),
        "default_pickup_city": _clean_optional(default_pickup_city),
        "default_pickup_area": _clean_optional(default_pickup_area),
        "default_pickup_country": _clean_optional(
            default_pickup_country
        ),
        "default_delivery_city": _clean_optional(
            default_delivery_city
        ),
        "default_delivery_country": _clean_optional(
            default_delivery_country
        ),
        "operational_notes": _clean_many(operational_notes),
    }

    candidate = [*profiles, profile]
    validation = _validate_candidate(
        customer_memory_path,
        candidate,
        validate_customer_memory_file,
        "Customer",
    )
    _atomic_write_json(customer_memory_path, candidate)

    return {
        "added": True,
        "dataset": "customer_memory",
        "customer_name": normalized_name,
        "active": bool(active),
        "profile_count": len(candidate),
        "active_profile_count": int(
            validation.get("active_profile_count") or 0
        ),
        "trusted_rule_count": (
            len(trusted_addresses) + len(trusted_domains)
        ),
        "verified": False,
        "warnings": validation.get("warnings") or [],
    }


def add_supplier_profile(
    *,
    supplier_capabilities_path: Path,
    provenance_registry_path: Path,
    supplier_name: str,
    role: str,
    route_regions: list[str],
    countries: list[str],
    service_types: list[str],
    equipment_types: list[str],
    reliability_score: float,
    price_score: float,
    speed_score: float,
    notes: str,
    primary_contact_email: str,
    active: bool = True,
    special_capabilities: list[str] | None = None,
    priority_routes: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_editable(provenance_registry_path)

    normalized_name = supplier_name.strip()
    normalized_notes = notes.strip()
    normalized_contact = primary_contact_email.strip()

    if not normalized_name:
        raise PilotDataPackIntakeError(
            "Supplier name must not be empty."
        )
    if not normalized_notes:
        raise PilotDataPackIntakeError(
            "Supplier notes must not be empty."
        )
    if not normalized_contact:
        raise PilotDataPackIntakeError(
            "Supplier primary contact email is required."
        )

    suppliers = _read_list(
        supplier_capabilities_path,
        "Supplier capabilities",
    )
    active_count = sum(
        1 for item in suppliers if item.get("active") is True
    )
    if active and active_count >= MAX_ACTIVE_PILOT_SUPPLIERS:
        raise PilotDataPackIntakeError(
            "Pilot pack already has the maximum 5 active suppliers."
        )

    supplier = {
        "supplier_name": normalized_name,
        "active": bool(active),
        "role": role.strip(),
        "route_regions": _clean_many(route_regions),
        "countries": _clean_many(countries),
        "service_types": _clean_many(service_types),
        "equipment_types": _clean_many(equipment_types),
        "special_capabilities": _clean_many(
            special_capabilities
        ),
        "priority_routes": _clean_many(priority_routes),
        "reliability_score": reliability_score,
        "price_score": price_score,
        "speed_score": speed_score,
        "notes": normalized_notes,
        "contacts": [
            {
                "email": normalized_contact,
                "active": True,
                "is_primary": True,
            }
        ],
    }

    candidate = [*suppliers, supplier]
    validation = _validate_candidate(
        supplier_capabilities_path,
        candidate,
        validate_supplier_capabilities_file,
        "Supplier",
    )
    _atomic_write_json(supplier_capabilities_path, candidate)

    return {
        "added": True,
        "dataset": "supplier_capabilities",
        "supplier_name": normalized_name,
        "active": bool(active),
        "supplier_count": len(candidate),
        "active_supplier_count": int(
            validation.get("active_supplier_count") or 0
        ),
        "primary_contact_configured": True,
        "verified": False,
        "warnings": validation.get("warnings") or [],
    }


def list_customer_profiles(
    customer_memory_path: Path,
) -> dict[str, Any]:
    profiles = _read_list(customer_memory_path, "Customer memory")
    items = []
    for profile in profiles:
        items.append(
            {
                "customer_name": profile.get("customer_name"),
                "active": profile.get("active"),
                "alias_count": len(profile.get("aliases") or []),
                "trusted_sender_address_count": len(
                    profile.get("trusted_sender_addresses") or []
                ),
                "trusted_sender_domain_count": len(
                    profile.get("trusted_sender_domains") or []
                ),
            }
        )
    return {
        "dataset": "customer_memory",
        "profile_count": len(items),
        "profiles": items,
    }


def list_supplier_profiles(
    supplier_capabilities_path: Path,
) -> dict[str, Any]:
    suppliers = _read_list(
        supplier_capabilities_path,
        "Supplier capabilities",
    )
    items = []
    for supplier in suppliers:
        contacts = supplier.get("contacts") or []
        primary_count = sum(
            1
            for contact in contacts
            if isinstance(contact, dict)
            and contact.get("active", True) is True
            and contact.get("is_primary") is True
        )
        items.append(
            {
                "supplier_name": supplier.get("supplier_name"),
                "active": supplier.get("active"),
                "role": supplier.get("role"),
                "countries": list(supplier.get("countries") or []),
                "service_types": list(
                    supplier.get("service_types") or []
                ),
                "equipment_types": list(
                    supplier.get("equipment_types") or []
                ),
                "active_primary_contact_count": primary_count,
            }
        )
    return {
        "dataset": "supplier_capabilities",
        "supplier_count": len(items),
        "suppliers": items,
    }
