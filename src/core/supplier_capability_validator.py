from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.core.supplier_capability_registry import (
    ADR_CAPABILITY,
    ADR_CLASS_1_CAPABILITY,
    ADR_CLASS_7_CAPABILITY,
    ALLOWED_SPECIAL_CAPABILITIES,
)


SUPPLIER_CAPABILITIES_PATH = Path("data/supplier_capabilities.json")

ALLOWED_ROLES = {"primary", "backup", "specialist"}
ALLOWED_SERVICE_TYPES = {"FTL", "LTL"}
SCORE_FIELDS = ["reliability_score", "price_score", "speed_score"]

REQUIRED_LIST_FIELDS = [
    "route_regions",
    "countries",
    "service_types",
    "equipment_types",
    "special_capabilities",
    "priority_routes",
]


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_string_list(
    *,
    value: Any,
    field_name: str,
    supplier: str,
    errors: List[str],
    required: bool = False,
) -> List[str]:
    if value is None:
        if required:
            errors.append(f"{supplier}: {field_name} is required.")
        return []

    if not isinstance(value, list):
        errors.append(f"{supplier}: {field_name} must be a list.")
        return []

    if required and not value:
        errors.append(f"{supplier}: {field_name} cannot be empty.")

    cleaned_values = []

    for index, item in enumerate(value):
        if not _is_non_empty_string(item):
            errors.append(f"{supplier}: {field_name}[{index}] must be a non-empty string.")
            continue

        cleaned_values.append(str(item).strip())

    return cleaned_values


def _validate_score(
    *,
    value: Any,
    field_name: str,
    supplier: str,
    errors: List[str],
) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"{supplier}: {field_name} must be a number.")
        return

    if value < 0 or value > 1:
        errors.append(f"{supplier}: {field_name} must be between 0 and 1.")


def validate_supplier_capabilities_file(
    path: Path = SUPPLIER_CAPABILITIES_PATH,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not path.exists():
        return {
            "valid": False,
            "errors": [f"Supplier capability file not found: {path}"],
            "warnings": [],
            "supplier_count": 0,
            "active_supplier_count": 0,
        }

    try:
        raw_data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "errors": [f"Invalid JSON in {path}: {exc}"],
            "warnings": [],
            "supplier_count": 0,
            "active_supplier_count": 0,
        }

    if not isinstance(raw_data, list):
        return {
            "valid": False,
            "errors": ["Supplier capability root must be a list."],
            "warnings": [],
            "supplier_count": 0,
            "active_supplier_count": 0,
        }

    seen_suppliers: set[str] = set()
    active_supplier_count = 0
    active_ftl_count = 0
    active_ltl_count = 0
    active_reefer_count = 0
    active_adr_count = 0

    for index, item in enumerate(raw_data):
        if not isinstance(item, dict):
            errors.append(f"Item {index}: each supplier entry must be an object.")
            continue

        supplier_name = item.get("supplier_name")

        if not _is_non_empty_string(supplier_name):
            errors.append(f"Item {index}: supplier_name is required.")
            supplier = f"<item {index}>"
        else:
            supplier = str(supplier_name).strip()

            if supplier in seen_suppliers:
                errors.append(f"{supplier}: duplicate supplier_name.")
            seen_suppliers.add(supplier)

        active = item.get("active")
        if not isinstance(active, bool):
            errors.append(f"{supplier}: active must be boolean.")
            active = False

        if active:
            active_supplier_count += 1

        role = item.get("role")
        if not _is_non_empty_string(role):
            errors.append(f"{supplier}: role is required.")
        elif role not in ALLOWED_ROLES:
            errors.append(
                f"{supplier}: role must be one of {sorted(ALLOWED_ROLES)}, got {role}."
            )

        for field_name in REQUIRED_LIST_FIELDS:
            required = field_name not in {"special_capabilities", "priority_routes"}
            _validate_string_list(
                value=item.get(field_name),
                field_name=field_name,
                supplier=supplier,
                errors=errors,
                required=required,
            )

        service_types = item.get("service_types") or []
        if isinstance(service_types, list):
            for service_type in service_types:
                if _is_non_empty_string(service_type) and service_type not in ALLOWED_SERVICE_TYPES:
                    errors.append(
                        f"{supplier}: unsupported service_type '{service_type}'. Allowed: {sorted(ALLOWED_SERVICE_TYPES)}."
                    )

            if active and "FTL" in service_types:
                active_ftl_count += 1

            if active and "LTL" in service_types:
                active_ltl_count += 1

        equipment_types = item.get("equipment_types") or []
        if isinstance(equipment_types, list):
            normalized_equipment = [
                str(equipment).strip().lower()
                for equipment in equipment_types
                if _is_non_empty_string(equipment)
            ]

            if active and any("reefer" in equipment for equipment in normalized_equipment):
                active_reefer_count += 1

        special_capabilities = item.get("special_capabilities") or []
        if isinstance(special_capabilities, list):
            normalized_capabilities = [
                str(capability).strip().lower()
                for capability in special_capabilities
                if _is_non_empty_string(capability)
            ]

            seen_capabilities: set[str] = set()

            for capability in normalized_capabilities:
                if capability in seen_capabilities:
                    errors.append(
                        f"{supplier}: duplicate special_capability '{capability}'."
                    )
                seen_capabilities.add(capability)

                if capability not in ALLOWED_SPECIAL_CAPABILITIES:
                    errors.append(
                        f"{supplier}: unsupported special_capability "
                        f"'{capability}'."
                    )

            if active and ADR_CAPABILITY in normalized_capabilities:
                active_adr_count += 1

            if (
                any(
                    capability in normalized_capabilities
                    for capability in [
                        ADR_CLASS_1_CAPABILITY,
                        ADR_CLASS_7_CAPABILITY,
                    ]
                )
                and ADR_CAPABILITY not in normalized_capabilities
            ):
                errors.append(
                    f"{supplier}: class_1 or class_7 capability requires "
                    "general 'adr' capability."
                )

            normalized_equipment = [
                str(equipment).strip().lower()
                for equipment in equipment_types
                if _is_non_empty_string(equipment)
            ]

            if (
                any(
                    equipment in normalized_equipment
                    for equipment in [
                        "special adr equipment",
                        "adr-capable equipment",
                    ]
                )
                and ADR_CAPABILITY not in normalized_capabilities
            ):
                errors.append(
                    f"{supplier}: ADR equipment requires general "
                    "'adr' capability."
                )

        for score_field in SCORE_FIELDS:
            if score_field not in item:
                errors.append(f"{supplier}: {score_field} is required.")
            else:
                _validate_score(
                    value=item.get(score_field),
                    field_name=score_field,
                    supplier=supplier,
                    errors=errors,
                )

        notes = item.get("notes")
        if not _is_non_empty_string(notes):
            errors.append(f"{supplier}: notes must be a non-empty string.")

        priority_routes = item.get("priority_routes") or []
        if isinstance(priority_routes, list):
            for route in priority_routes:
                if not _is_non_empty_string(route):
                    continue

                if "-" not in str(route):
                    warnings.append(
                        f"{supplier}: priority route '{route}' does not include '-' route separator."
                    )

        if role == "specialist" and not special_capabilities:
            warnings.append(
                f"{supplier}: specialist supplier has no special_capabilities."
            )

    if active_supplier_count == 0:
        errors.append("At least one supplier must be active.")

    if active_ftl_count == 0:
        errors.append("At least one active supplier must support FTL.")

    if active_ltl_count == 0:
        warnings.append("No active supplier supports LTL.")

    if active_reefer_count == 0:
        warnings.append("No active supplier has Reefer equipment.")

    if active_adr_count == 0:
        warnings.append("No active supplier has ADR capability.")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "supplier_count": len(raw_data),
        "active_supplier_count": active_supplier_count,
        "active_ftl_count": active_ftl_count,
        "active_ltl_count": active_ltl_count,
        "active_reefer_count": active_reefer_count,
        "active_adr_count": active_adr_count,
        "source": str(path),
    }


def assert_supplier_capabilities_valid(
    path: Path = SUPPLIER_CAPABILITIES_PATH,
) -> Dict[str, Any]:
    result = validate_supplier_capabilities_file(path)

    if not result.get("valid"):
        error_text = "\n".join(result.get("errors", []))
        raise ValueError(f"Supplier capability validation failed:\n{error_text}")

    return result
