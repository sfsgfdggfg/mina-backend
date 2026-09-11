from __future__ import annotations

import re
import unicodedata
from typing import Any


def _slug(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or None


def shipment_context_keys(shipment: Any, equipment_decision: Any | None = None) -> list[str]:
    mode = _slug(getattr(shipment, "transport_mode", None))
    pickup = _slug(getattr(shipment, "pickup_country", None))
    delivery = _slug(getattr(shipment, "delivery_country", None))
    if not mode or not pickup or not delivery:
        return []
    lane_key = f"mode={mode}|lane={pickup}>{delivery}"
    equipment = None
    if equipment_decision is not None:
        equipment = _slug(
            equipment_decision.get("selected_equipment")
            if isinstance(equipment_decision, dict)
            else getattr(equipment_decision, "selected_equipment", None)
        )
    equipment = equipment or _slug(getattr(shipment, "equipment_type", None))
    keys = []
    if equipment:
        keys.append(f"{lane_key}|equipment={equipment}")
    keys.append(lane_key)
    return keys


def context_label(context_key: str) -> str:
    return context_key.replace("mode=", "").replace("|lane=", " · ").replace("|equipment=", " · ")
