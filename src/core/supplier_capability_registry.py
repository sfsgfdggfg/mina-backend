from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Set


REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "supplier_capability_registry.json"
)


def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(
            f"Supplier capability registry not found: {REGISTRY_PATH}"
        )

    raw = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError("Supplier capability registry root must be an object.")

    return raw


_REGISTRY = _load_registry()

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


def get_required_adr_class_capability(
    adr_class: str | None,
) -> str | None:
    if adr_class is None:
        return None

    return ADR_CLASS_CAPABILITY_MAP.get(str(adr_class).strip())
