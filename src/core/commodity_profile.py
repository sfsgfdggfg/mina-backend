from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


COMMODITY_DICTIONARY_PATH = Path("data/commodity_dictionary.json")


def _normalize(value: Optional[str]) -> str:
    if value is None:
        return ""

    return (
        str(value)
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("İ", "i")
        .replace("ü", "u")
        .replace("Ü", "u")
        .replace("ö", "o")
        .replace("Ö", "o")
        .replace("ğ", "g")
        .replace("Ğ", "g")
        .replace("ş", "s")
        .replace("Ş", "s")
        .replace("ç", "c")
        .replace("Ç", "c")
    )


def load_commodity_dictionary() -> list[dict]:
    if not COMMODITY_DICTIONARY_PATH.exists():
        return []

    try:
        raw_data = json.loads(COMMODITY_DICTIONARY_PATH.read_text())
    except json.JSONDecodeError:
        return []

    if not isinstance(raw_data, list):
        return []

    return [item for item in raw_data if isinstance(item, dict)]


def get_commodity_record(commodity: Optional[str]) -> Optional[Dict[str, Any]]:
    normalized_commodity = _normalize(commodity)

    if not normalized_commodity:
        return None

    for item in load_commodity_dictionary():
        if _normalize(item.get("canonical_commodity")) == normalized_commodity:
            return item

    return None


def get_commodity_operational_profile(commodity: Optional[str]) -> Dict[str, Any]:
    record = get_commodity_record(commodity)

    if not record:
        return {}

    profile = record.get("operational_profile", {})

    if isinstance(profile, dict):
        return profile

    return {}


def _append_special_note(shipment, note: str):
    if not note:
        return shipment

    existing_notes = getattr(shipment, "special_notes", None)

    null_like_notes = {
        "",
        "none",
        "null",
        "/null/",
        "n/a",
        "na",
        "-",
    }

    if isinstance(existing_notes, str) and existing_notes.strip().lower() in null_like_notes:
        existing_notes = None

    if existing_notes:
        if note not in existing_notes:
            shipment.special_notes = existing_notes + "\n" + note
    else:
        shipment.special_notes = note

    return shipment
def apply_commodity_profile_to_shipment(shipment: Any):
    record = get_commodity_record(getattr(shipment, "commodity", None))

    if not record:
        return shipment

    profile = get_commodity_operational_profile(getattr(shipment, "commodity", None))

    notes = []
    record_notes = record.get("notes", [])
    profile_notes = profile.get("operational_notes", [])

    if isinstance(record_notes, list):
        notes.extend(str(note) for note in record_notes)

    if isinstance(profile_notes, list):
        notes.extend(str(note) for note in profile_notes)

    if notes:
        note_text = "[COMMODITY PROFILE] " + " ".join(notes)
        shipment = _append_special_note(shipment, note_text)

    if profile.get("requires_temperature_control"):
        shipment.is_temperature_controlled = True

        if not getattr(shipment, "temperature_requirement", None):
            default_temperature = profile.get("default_temperature_requirement")
            if default_temperature:
                shipment.temperature_requirement = default_temperature

    if profile.get("high_value_candidate"):
        shipment.is_high_value = True

    return shipment
