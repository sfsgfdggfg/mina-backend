from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from src.paths import data_path

HS_COMMODITY_MAP_PATH = data_path("hs_commodity_map.json")
COMMODITY_DICTIONARY_PATH = data_path("commodity_dictionary.json")

VALID_HS_CODE_LENGTHS = {2, 4, 6}


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _normalize(value: str) -> str:
    return str(value).strip().lower()


def _load_json_with_duplicate_key_detection(path: Path) -> Tuple[Any, List[str]]:
    duplicate_keys: List[str] = []

    def object_pairs_hook(pairs):
        result = {}
        seen = set()

        for key, value in pairs:
            if key in seen:
                duplicate_keys.append(str(key))
            seen.add(key)
            result[key] = value

        return result

    raw_data = json.loads(
        path.read_text(),
        object_pairs_hook=object_pairs_hook,
    )

    return raw_data, duplicate_keys


def _load_canonical_commodities(path: Path = COMMODITY_DICTIONARY_PATH) -> set[str]:
    if not path.exists():
        return set()

    try:
        raw_data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return set()

    if not isinstance(raw_data, list):
        return set()

    canonical_values = set()

    for item in raw_data:
        if not isinstance(item, dict):
            continue

        canonical_commodity = item.get("canonical_commodity")
        if _is_non_empty_string(canonical_commodity):
            canonical_values.add(_normalize(canonical_commodity))

    return canonical_values


def _validate_notes(
    *,
    value: Any,
    hs_code: str,
    errors: List[str],
) -> None:
    if value is None:
        return

    if not isinstance(value, list):
        errors.append(f"{hs_code}: notes must be a list.")
        return

    for index, item in enumerate(value):
        if not _is_non_empty_string(item):
            errors.append(f"{hs_code}: notes[{index}] must be a non-empty string.")


def validate_hs_commodity_map_file(
    path: Path = HS_COMMODITY_MAP_PATH,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not path.exists():
        return {
            "valid": False,
            "errors": [f"HS commodity map file not found: {path}"],
            "warnings": [],
            "mapping_count": 0,
        }

    try:
        raw_data, duplicate_keys = _load_json_with_duplicate_key_detection(path)
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "errors": [f"Invalid JSON in {path}: {exc}"],
            "warnings": [],
            "mapping_count": 0,
        }

    for duplicate_key in duplicate_keys:
        errors.append(f"{duplicate_key}: duplicate HS code key.")

    if not isinstance(raw_data, dict):
        return {
            "valid": False,
            "errors": ["HS commodity map root must be an object/dict."],
            "warnings": warnings,
            "mapping_count": 0,
        }

    if not raw_data:
        errors.append("HS commodity map must contain at least one mapping.")

    canonical_commodities = _load_canonical_commodities()
    hs_codes = set(raw_data.keys())

    chapter_count = 0
    heading_count = 0
    subheading_count = 0

    for hs_code, item in raw_data.items():
        if not _is_non_empty_string(hs_code):
            errors.append("HS code key cannot be empty.")
            continue

        hs_code_text = str(hs_code).strip()

        if not hs_code_text.isdigit():
            errors.append(f"{hs_code_text}: HS code must contain only digits.")
            continue

        if len(hs_code_text) not in VALID_HS_CODE_LENGTHS:
            errors.append(
                f"{hs_code_text}: HS code length must be one of {sorted(VALID_HS_CODE_LENGTHS)}."
            )

        if len(hs_code_text) == 2:
            chapter_count += 1
        elif len(hs_code_text) == 4:
            heading_count += 1
            parent_chapter = hs_code_text[:2]
            if parent_chapter not in hs_codes:
                warnings.append(
                    f"{hs_code_text}: parent HS chapter {parent_chapter} is not mapped."
                )
        elif len(hs_code_text) == 6:
            subheading_count += 1
            parent_heading = hs_code_text[:4]
            parent_chapter = hs_code_text[:2]

            if parent_heading not in hs_codes:
                warnings.append(
                    f"{hs_code_text}: parent HS heading {parent_heading} is not mapped."
                )

            if parent_chapter not in hs_codes:
                warnings.append(
                    f"{hs_code_text}: parent HS chapter {parent_chapter} is not mapped."
                )

        if not isinstance(item, dict):
            errors.append(f"{hs_code_text}: mapping value must be an object/dict.")
            continue

        commodity_group = item.get("commodity_group")

        if not _is_non_empty_string(commodity_group):
            errors.append(f"{hs_code_text}: commodity_group is required.")
        else:
            normalized_commodity_group = _normalize(commodity_group)

            if canonical_commodities and normalized_commodity_group not in canonical_commodities:
                warnings.append(
                    f"{hs_code_text}: commodity_group '{commodity_group}' is not an exact canonical commodity."
                )

        _validate_notes(
            value=item.get("notes"),
            hs_code=hs_code_text,
            errors=errors,
        )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "mapping_count": len(raw_data),
        "chapter_count": chapter_count,
        "heading_count": heading_count,
        "subheading_count": subheading_count,
        "canonical_commodity_count": len(canonical_commodities),
        "source": str(path),
    }


def assert_hs_commodity_map_valid(
    path: Path = HS_COMMODITY_MAP_PATH,
) -> Dict[str, Any]:
    result = validate_hs_commodity_map_file(path)

    if not result.get("valid"):
        error_text = "\n".join(result.get("errors", []))
        raise ValueError(f"HS commodity map validation failed:\n{error_text}")

    return result
