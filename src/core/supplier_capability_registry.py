from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Set


REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "supplier_capability_registry.json"
)


class SupplierCapabilityRegistryError(RuntimeError):
    pass


def load_supplier_capability_registry(
    path: Path = REGISTRY_PATH,
) -> dict:
    if not path.exists():
        raise SupplierCapabilityRegistryError(
            f"Supplier capability registry not found: {path}"
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SupplierCapabilityRegistryError(
            f"Invalid JSON in supplier capability registry: {exc}"
        ) from exc

    if not isinstance(raw, dict):
        raise SupplierCapabilityRegistryError(
            "Supplier capability registry root must be an object."
        )

    return raw


_REGISTRY = load_supplier_capability_registry()

ALLOWED_SPECIAL_CAPABILITIES: Set[str] = set(
    _REGISTRY.get("allowed_special_capabilities", [])
)

ADR_CLASS_CAPABILITY_MAP: Dict[str, str] = {
    str(key): str(value)
    for key, value in (
        _REGISTRY.get("adr_class_capability_map", {}) or {}
    ).items()
}

ADR_CAPABILITY = "adr"
ADR_CLASS_1_CAPABILITY = ADR_CLASS_CAPABILITY_MAP.get("1", "class_1")
ADR_CLASS_7_CAPABILITY = ADR_CLASS_CAPABILITY_MAP.get("7", "class_7")


def get_supplier_capability_registry_metadata() -> dict:
    return {
        "source": str(REGISTRY_PATH),
        "loaded": True,
        "allowed_capability_count": len(ALLOWED_SPECIAL_CAPABILITIES),
        "adr_class_mapping_count": len(ADR_CLASS_CAPABILITY_MAP),
    }


def get_required_adr_class_capability(
    adr_class: str | None,
) -> str | None:
    if adr_class is None:
        return None

    return ADR_CLASS_CAPABILITY_MAP.get(str(adr_class).strip())
