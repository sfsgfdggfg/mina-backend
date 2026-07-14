from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from src.core.supplier_capability_registry import REGISTRY_PATH


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_supplier_capability_registry_file(
    path: Path = REGISTRY_PATH,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not path.exists():
        return {
            "valid": False,
            "errors": [f"Supplier capability registry not found: {path}"],
            "warnings": [],
            "source": str(path),
        }

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "errors": [f"Invalid JSON in {path}: {exc}"],
            "warnings": [],
            "source": str(path),
        }

    if not isinstance(raw, dict):
        errors.append("Supplier capability registry root must be an object.")
        raw = {}

    allowed = raw.get("allowed_special_capabilities")
    class_map = raw.get("adr_class_capability_map")

    if not isinstance(allowed, list):
        errors.append("allowed_special_capabilities must be a list.")
        allowed = []

    normalized_allowed = []

    for index, capability in enumerate(allowed):
        if not _is_non_empty_string(capability):
            errors.append(
                f"allowed_special_capabilities[{index}] must be a non-empty string."
            )
            continue

        normalized = capability.strip()

        if normalized in normalized_allowed:
            errors.append(
                f"duplicate allowed_special_capability '{normalized}'."
            )

        normalized_allowed.append(normalized)

    if "adr" not in normalized_allowed:
        errors.append("allowed_special_capabilities must include 'adr'.")

    if not isinstance(class_map, dict):
        errors.append("adr_class_capability_map must be an object.")
        class_map = {}

    for adr_class, capability in class_map.items():
        if not _is_non_empty_string(str(adr_class)):
            errors.append("ADR class mapping key must be non-empty.")
            continue

        if not _is_non_empty_string(capability):
            errors.append(
                f"ADR Class {adr_class} capability mapping must be a non-empty string."
            )
            continue

        if capability not in normalized_allowed:
            errors.append(
                f"ADR Class {adr_class} maps to unsupported capability "
                f"'{capability}'."
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "allowed_capability_count": len(normalized_allowed),
        "adr_class_mapping_count": len(class_map),
        "source": str(path),
    }
