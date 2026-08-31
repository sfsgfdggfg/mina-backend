from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from src.paths import data_path
from src.core.pricing_policy import PricingFormula

CUSTOMER_MEMORY_PATH = data_path("customer_memory.json")

ALLOWED_SENSITIVITY_VALUES = {"low", "medium", "high"}
ALLOWED_EQUIPMENT_TYPES = {
    "Tenteli / Curtainsider",
    "Kapalı Kasa / Box Trailer",
    "Mega Trailer",
    "Reefer",
    "Special ADR Equipment",
}


_DOMAIN_PATTERN = (
    r"(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+"
    r"[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?"
)

_TRUSTED_EMAIL_RE = re.compile(
    rf"^[^@\s]+@(?P<domain>{_DOMAIN_PATTERN})$",
    flags=re.IGNORECASE,
)
_TRUSTED_DOMAIN_RE = re.compile(
    rf"^{_DOMAIN_PATTERN}$",
    flags=re.IGNORECASE,
)


def _normalize(value: str) -> str:
    return str(value).strip().lower()


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_optional_string(
    *,
    value: Any,
    field_name: str,
    customer: str,
    errors: List[str],
) -> None:
    if value is None:
        return

    if not isinstance(value, str):
        errors.append(f"{customer}: {field_name} must be a string or null.")


def _validate_string_list(
    *,
    value: Any,
    field_name: str,
    customer: str,
    errors: List[str],
    required: bool = False,
) -> List[str]:
    if value is None:
        if required:
            errors.append(f"{customer}: {field_name} is required.")
        return []

    if not isinstance(value, list):
        errors.append(f"{customer}: {field_name} must be a list.")
        return []

    if required and not value:
        errors.append(f"{customer}: {field_name} cannot be empty.")

    cleaned_values = []

    for index, item in enumerate(value):
        if not _is_non_empty_string(item):
            errors.append(f"{customer}: {field_name}[{index}] must be a non-empty string.")
            continue

        cleaned_values.append(str(item).strip())

    return cleaned_values


def validate_customer_memory_file(
    path: Path = CUSTOMER_MEMORY_PATH,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not path.exists():
        return {
            "valid": False,
            "errors": [f"Customer memory file not found: {path}"],
            "warnings": [],
            "profile_count": 0,
            "active_profile_count": 0,
        }

    try:
        raw_data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "errors": [f"Invalid JSON in {path}: {exc}"],
            "warnings": [],
            "profile_count": 0,
            "active_profile_count": 0,
        }

    if not isinstance(raw_data, list):
        return {
            "valid": False,
            "errors": ["Customer memory root must be a list."],
            "warnings": [],
            "profile_count": 0,
            "active_profile_count": 0,
        }

    seen_customer_names: dict[str, str] = {}
    seen_aliases: dict[str, str] = {}
    seen_trusted_addresses: dict[str, str] = {}
    seen_trusted_domains: dict[str, str] = {}
    seen_address_domains: dict[str, set[str]] = {}

    active_profile_count = 0
    active_trusted_profile_count = 0

    for index, item in enumerate(raw_data):
        if not isinstance(item, dict):
            errors.append(f"Item {index}: each customer memory entry must be an object.")
            continue

        customer_name = item.get("customer_name")

        if not _is_non_empty_string(customer_name):
            errors.append(f"Item {index}: customer_name is required.")
            customer = f"<item {index}>"
        else:
            customer = str(customer_name).strip()
            normalized_customer = _normalize(customer)

            previous_customer = seen_customer_names.get(normalized_customer)
            if previous_customer:
                errors.append(
                    f"{customer}: duplicate customer_name; already used by {previous_customer}."
                )
            else:
                seen_customer_names[normalized_customer] = customer

        active = item.get("active")
        if not isinstance(active, bool):
            errors.append(f"{customer}: active must be boolean.")
        elif active:
            active_profile_count += 1

        aliases = _validate_string_list(
            value=item.get("aliases"),
            field_name="aliases",
            customer=customer,
            errors=errors,
            required=False,
        )

        normalized_aliases = [_normalize(alias) for alias in aliases]

        if len(normalized_aliases) != len(set(normalized_aliases)):
            errors.append(f"{customer}: duplicate alias inside same profile.")

        for alias, normalized_alias in zip(aliases, normalized_aliases):
            if normalized_alias == _normalize(customer):
                warnings.append(
                    f"{customer}: alias '{alias}' is same as customer_name."
                )

            previous_owner = seen_aliases.get(normalized_alias)
            if previous_owner and previous_owner != customer:
                errors.append(
                    f"{customer}: alias '{alias}' is already used by {previous_owner}."
                )
            else:
                seen_aliases[normalized_alias] = customer

        for alias, normalized_alias in zip(aliases, normalized_aliases):
            existing_customer = seen_customer_names.get(normalized_alias)
            if existing_customer and existing_customer != customer:
                errors.append(
                    f"{customer}: alias '{alias}' conflicts with customer_name {existing_customer}."
                )

        trusted_addresses = _validate_string_list(
            value=item.get("trusted_sender_addresses"),
            field_name="trusted_sender_addresses",
            customer=customer,
            errors=errors,
            required=False,
        )
        trusted_domains = _validate_string_list(
            value=item.get("trusted_sender_domains"),
            field_name="trusted_sender_domains",
            customer=customer,
            errors=errors,
            required=False,
        )

        valid_trusted_addresses: list[str] = []
        valid_trusted_domains: list[str] = []
        profile_address_domains: set[str] = set()

        normalized_addresses = [
            address.strip().lower()
            for address in trusted_addresses
        ]

        if len(normalized_addresses) != len(
            set(normalized_addresses)
        ):
            errors.append(
                f"{customer}: duplicate trusted sender address "
                "inside same profile."
            )

        for address in normalized_addresses:
            match = _TRUSTED_EMAIL_RE.fullmatch(address)

            if match is None:
                errors.append(
                    f"{customer}: trusted sender address "
                    f"'{address}' is not a valid email address."
                )
                continue

            domain = match.group("domain").lower()
            valid_trusted_addresses.append(address)
            profile_address_domains.add(domain)

            previous_owner = seen_trusted_addresses.get(
                address
            )
            if (
                previous_owner
                and previous_owner != customer
            ):
                errors.append(
                    f"{customer}: trusted sender address "
                    f"'{address}' is already trusted by "
                    f"{previous_owner}."
                )
            else:
                seen_trusted_addresses[address] = customer

            domain_owner = seen_trusted_domains.get(domain)
            if (
                domain_owner
                and domain_owner != customer
            ):
                errors.append(
                    f"{customer}: sender address '{address}' "
                    "conflicts with trusted sender domain "
                    f"'{domain}' owned by {domain_owner}."
                )

            seen_address_domains.setdefault(
                domain,
                set(),
            ).add(customer)

        normalized_domains = [
            domain.strip().lower()
            for domain in trusted_domains
        ]

        if len(normalized_domains) != len(
            set(normalized_domains)
        ):
            errors.append(
                f"{customer}: duplicate trusted sender domain "
                "inside same profile."
            )

        for domain in normalized_domains:
            if (
                domain.startswith("@")
                or _TRUSTED_DOMAIN_RE.fullmatch(domain)
                is None
            ):
                errors.append(
                    f"{customer}: trusted sender domain "
                    f"'{domain}' must be a bare valid domain."
                )
                continue

            valid_trusted_domains.append(domain)

            previous_owner = seen_trusted_domains.get(
                domain
            )
            if (
                previous_owner
                and previous_owner != customer
            ):
                errors.append(
                    f"{customer}: trusted sender domain "
                    f"'{domain}' is already trusted by "
                    f"{previous_owner}."
                )
            else:
                seen_trusted_domains[domain] = customer

            conflicting_address_owners = (
                seen_address_domains.get(
                    domain,
                    set(),
                )
                - {customer}
            )
            if conflicting_address_owners:
                errors.append(
                    f"{customer}: trusted sender domain "
                    f"'{domain}' conflicts with sender addresses "
                    "trusted by another customer."
                )

            if domain in profile_address_domains:
                warnings.append(
                    f"{customer}: trusted domain '{domain}' "
                    "duplicates an address-level trust rule."
                )

        if (
            active is True
            and (
                valid_trusted_addresses
                or valid_trusted_domains
            )
        ):
            active_trusted_profile_count += 1
        elif active is True:
            warnings.append(
                f"{customer}: active profile has no valid "
                "trusted sender address or domain."
            )

        default_equipment_type = item.get("default_equipment_type")
        if default_equipment_type:
            if not isinstance(default_equipment_type, str):
                errors.append(f"{customer}: default_equipment_type must be a string or null.")
            elif default_equipment_type not in ALLOWED_EQUIPMENT_TYPES:
                warnings.append(
                    f"{customer}: default_equipment_type '{default_equipment_type}' is not in known equipment list."
                )

        raw_pricing_policy = item.get("pricing_policy")
        if raw_pricing_policy is not None:
            try:
                PricingFormula.model_validate(raw_pricing_policy)
            except (ValueError, TypeError) as exc:
                errors.append(
                    f"{customer}: pricing_policy is invalid: {exc}"
                )

        for sensitivity_field in ["price_sensitivity", "time_sensitivity"]:
            value = item.get(sensitivity_field)

            if value in (None, ""):
                continue

            if not isinstance(value, str):
                errors.append(f"{customer}: {sensitivity_field} must be a string or null.")
                continue

            if value not in ALLOWED_SENSITIVITY_VALUES:
                errors.append(
                    f"{customer}: {sensitivity_field} must be one of {sorted(ALLOWED_SENSITIVITY_VALUES)}, got {value}."
                )

        for optional_string_field in [
            "default_commodity",
            "default_pickup_city",
            "default_pickup_area",
            "default_pickup_country",
            "default_delivery_city",
            "default_delivery_country",
            "last_updated_by",
            "change_note",
        ]:
            _validate_optional_string(
                value=item.get(optional_string_field),
                field_name=optional_string_field,
                customer=customer,
                errors=errors,
            )

        _validate_string_list(
            value=item.get("operational_notes"),
            field_name="operational_notes",
            customer=customer,
            errors=errors,
            required=False,
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "profile_count": len(raw_data),
        "active_profile_count": active_profile_count,
        "active_trusted_profile_count": (
            active_trusted_profile_count
        ),
        "alias_count": len(seen_aliases),
        "source": str(path),
    }


def assert_customer_memory_valid(
    path: Path = CUSTOMER_MEMORY_PATH,
) -> Dict[str, Any]:
    result = validate_customer_memory_file(path)

    if not result.get("valid"):
        error_text = "\n".join(result.get("errors", []))
        raise ValueError(f"Customer memory validation failed:\n{error_text}")

    return result
