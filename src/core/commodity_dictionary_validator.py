from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List


COMMODITY_DICTIONARY_PATH = Path("data/commodity_dictionary.json")


def _normalize_keyword(value: str) -> str:
    return str(value).strip().lower()


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_string_list(
    *,
    value: Any,
    field_name: str,
    commodity: str,
    errors: List[str],
    required: bool = False,
) -> List[str]:
    if value is None:
        if required:
            errors.append(f"{commodity}: {field_name} is required.")
        return []

    if not isinstance(value, list):
        errors.append(f"{commodity}: {field_name} must be a list.")
        return []

    if required and not value:
        errors.append(f"{commodity}: {field_name} cannot be empty.")

    cleaned_values = []

    for index, item in enumerate(value):
        if not _is_non_empty_string(item):
            errors.append(f"{commodity}: {field_name}[{index}] must be a non-empty string.")
            continue

        cleaned_values.append(str(item).strip())

    return cleaned_values


def validate_commodity_dictionary_file(
    path: Path = COMMODITY_DICTIONARY_PATH,
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []

    if not path.exists():
        return {
            "valid": False,
            "errors": [f"Commodity dictionary file not found: {path}"],
            "warnings": [],
            "commodity_count": 0,
        }

    try:
        raw_data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "errors": [f"Invalid JSON in {path}: {exc}"],
            "warnings": [],
            "commodity_count": 0,
        }

    if not isinstance(raw_data, list):
        return {
            "valid": False,
            "errors": ["Commodity dictionary root must be a list."],
            "warnings": [],
            "commodity_count": 0,
        }

    seen_commodities: set[str] = set()
    keyword_owner: dict[str, str] = {}

    for index, item in enumerate(raw_data):
        if not isinstance(item, dict):
            errors.append(f"Item {index}: each commodity entry must be an object.")
            continue

        commodity = item.get("canonical_commodity")

        if not _is_non_empty_string(commodity):
            errors.append(f"Item {index}: canonical_commodity is required.")
            commodity = f"<item {index}>"
        else:
            commodity = str(commodity).strip()

            if commodity in seen_commodities:
                errors.append(f"{commodity}: duplicate canonical_commodity.")
            seen_commodities.add(commodity)

        keywords = _validate_string_list(
            value=item.get("keywords"),
            field_name="keywords",
            commodity=commodity,
            errors=errors,
            required=True,
        )

        normalized_keywords = [_normalize_keyword(keyword) for keyword in keywords]

        if len(normalized_keywords) != len(set(normalized_keywords)):
            errors.append(f"{commodity}: duplicate keyword inside same commodity.")

        for keyword in normalized_keywords:
            previous_owner = keyword_owner.get(keyword)
            if previous_owner and previous_owner != commodity:
                warnings.append(
                    f"Keyword '{keyword}' appears in both '{previous_owner}' and '{commodity}'."
                )
            else:
                keyword_owner[keyword] = commodity

        if "notes" in item:
            _validate_string_list(
                value=item.get("notes"),
                field_name="notes",
                commodity=commodity,
                errors=errors,
                required=False,
            )

        profile = item.get("operational_profile")

        if profile is None:
            continue

        if not isinstance(profile, dict):
            errors.append(f"{commodity}: operational_profile must be an object.")
            continue

        for list_field in [
            "operational_notes",
            "missing_info_fields",
            "critical_missing_info_fields",
            "action_checklist",
        ]:
            if list_field in profile:
                _validate_string_list(
                    value=profile.get(list_field),
                    field_name=f"operational_profile.{list_field}",
                    commodity=commodity,
                    errors=errors,
                    required=False,
                )

        missing_info_fields = profile.get("missing_info_fields", [])
        critical_missing_info_fields = profile.get("critical_missing_info_fields", [])

        if isinstance(missing_info_fields, list) and isinstance(critical_missing_info_fields, list):
            missing_info_set = {
                str(field).strip()
                for field in missing_info_fields
                if _is_non_empty_string(field)
            }

            for field in critical_missing_info_fields:
                if not _is_non_empty_string(field):
                    continue

                if str(field).strip() not in missing_info_set:
                    errors.append(
                        f"{commodity}: critical_missing_info_field '{field}' must also exist in missing_info_fields."
                    )

        for boolean_field in [
            "requires_human_review",
            "requires_temperature_control",
            "requires_reefer",
            "requires_adr_check",
            "requires_temperature_check",
            "high_value_candidate",
        ]:
            if boolean_field in profile and not isinstance(profile.get(boolean_field), bool):
                errors.append(
                    f"{commodity}: operational_profile.{boolean_field} must be boolean."
                )

        for string_field in [
            "default_equipment",
            "default_temperature_requirement",
            "risk_reason",
            "missing_info_reason",
        ]:
            if string_field in profile and not _is_non_empty_string(profile.get(string_field)):
                errors.append(
                    f"{commodity}: operational_profile.{string_field} must be a non-empty string."
                )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "commodity_count": len(raw_data),
        "unique_keyword_count": len(keyword_owner),
        "source": str(path),
    }


def assert_commodity_dictionary_valid(
    path: Path = COMMODITY_DICTIONARY_PATH,
) -> Dict[str, Any]:
    result = validate_commodity_dictionary_file(path)

    if not result.get("valid"):
        error_text = "\n".join(result.get("errors", []))
        raise ValueError(f"Commodity dictionary validation failed:\n{error_text}")

    return result
