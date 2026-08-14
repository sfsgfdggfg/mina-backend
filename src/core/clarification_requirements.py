from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, TYPE_CHECKING

from src.paths import data_path
if TYPE_CHECKING:
    from src.core.models import Shipment


ClarificationValueType = Literal["text", "boolean", "number"]
ClarificationAnswerValue = bool | float | str

CLARIFICATION_VALUE_TYPES = {"text", "boolean", "number"}
COMMODITY_DICTIONARY_PATH = data_path("commodity_dictionary.json")


class ClarificationRequirementError(ValueError):
    pass


class UnknownClarificationKeyError(ClarificationRequirementError):
    pass


@dataclass(frozen=True)
class ClarificationCompliancePolicy:
    policy_type: Literal["regulatory_document"]
    document_label: str
    required_before_quote: bool
    customer_promise_requires_human_review: bool


@dataclass(frozen=True)
class ClarificationRequirement:
    key: str
    value_type: ClarificationValueType
    question: str
    critical: bool
    commodity: str
    compliance_policy: ClarificationCompliancePolicy | None = None


def _load_dictionary() -> list[dict[str, Any]]:
    raw_data = json.loads(
        COMMODITY_DICTIONARY_PATH.read_text(encoding="utf-8")
    )

    if not isinstance(raw_data, list):
        raise ClarificationRequirementError(
            "Commodity dictionary root must be a list."
        )

    return [item for item in raw_data if isinstance(item, dict)]


def _requirement_from_data(
    raw_requirement: Mapping[str, Any],
    commodity: str,
) -> ClarificationRequirement:
    raw_policy = raw_requirement.get("compliance_policy")
    compliance_policy = None

    if isinstance(raw_policy, Mapping):
        compliance_policy = ClarificationCompliancePolicy(
            policy_type=str(raw_policy["policy_type"]).strip(),
            document_label=str(raw_policy["document_label"]).strip(),
            required_before_quote=raw_policy["required_before_quote"],
            customer_promise_requires_human_review=raw_policy[
                "customer_promise_requires_human_review"
            ],
        )

    return ClarificationRequirement(
        key=str(raw_requirement["key"]).strip(),
        value_type=str(raw_requirement["value_type"]).strip(),
        question=str(raw_requirement["question"]).strip(),
        critical=raw_requirement["critical"],
        commodity=commodity,
        compliance_policy=compliance_policy,
    )


def get_all_clarification_requirements() -> dict[
    str, ClarificationRequirement
]:
    requirements: dict[str, ClarificationRequirement] = {}

    for item in _load_dictionary():
        commodity = str(item.get("canonical_commodity") or "").strip()
        profile = item.get("operational_profile") or {}

        if not isinstance(profile, dict):
            continue

        raw_requirements = profile.get("clarification_requirements") or []

        if not isinstance(raw_requirements, list):
            continue

        for raw_requirement in raw_requirements:
            if not isinstance(raw_requirement, dict):
                continue

            requirement = _requirement_from_data(
                raw_requirement,
                commodity,
            )

            if requirement.key in requirements:
                raise ClarificationRequirementError(
                    "Duplicate clarification requirement key: "
                    f"{requirement.key}"
                )

            requirements[requirement.key] = requirement

    return requirements


def get_commodity_clarification_requirements(
    commodity: str | None,
) -> list[ClarificationRequirement]:
    if not commodity:
        return []

    normalized_commodity = str(commodity).strip().casefold()

    return [
        requirement
        for requirement in get_all_clarification_requirements().values()
        if requirement.commodity.casefold() == normalized_commodity
    ]


def get_clarification_question(key: str) -> str | None:
    requirement = get_all_clarification_requirements().get(key)
    return requirement.question if requirement else None


def normalize_clarification_answers(
    answers: Mapping[str, Any],
) -> dict[str, ClarificationAnswerValue]:
    requirements = get_all_clarification_requirements()
    normalized: dict[str, ClarificationAnswerValue] = {}

    for raw_key, value in answers.items():
        key = str(raw_key).strip()
        requirement = requirements.get(key)

        if requirement is None:
            raise UnknownClarificationKeyError(
                f"Unknown clarification key: {key}"
            )

        if requirement.value_type == "boolean":
            if not isinstance(value, bool):
                raise ClarificationRequirementError(
                    f"Clarification answer '{key}' must be boolean."
                )
            normalized[key] = value

        elif requirement.value_type == "number":
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
            ):
                raise ClarificationRequirementError(
                    f"Clarification answer '{key}' must be a number."
                )
            normalized[key] = float(value)

        else:
            if not isinstance(value, str) or not value.strip():
                raise ClarificationRequirementError(
                    f"Clarification answer '{key}' must be non-empty text."
                )
            normalized[key] = value.strip()

    return normalized


def is_clarification_requirement_answered(
    shipment: "Shipment",
    requirement: ClarificationRequirement,
) -> bool:
    if requirement.key not in shipment.commodity_attributes:
        return False

    try:
        normalize_clarification_answers(
            {
                requirement.key: shipment.commodity_attributes[
                    requirement.key
                ]
            }
        )
    except ClarificationRequirementError:
        return False

    return True


def apply_clarification_answers(
    shipment: "Shipment",
    answers: Mapping[str, Any],
) -> "Shipment":
    """Apply validated structured answers atomically to a shipment copy."""

    normalized_answers = normalize_clarification_answers(answers)
    allowed_keys = {
        requirement.key
        for requirement in get_commodity_clarification_requirements(
            shipment.commodity
        )
    }

    invalid_for_commodity = set(normalized_answers) - allowed_keys
    if invalid_for_commodity:
        invalid_key = sorted(invalid_for_commodity)[0]
        raise UnknownClarificationKeyError(
            f"Clarification key '{invalid_key}' is not valid for "
            f"commodity '{shipment.commodity}'."
        )

    updated_attributes = dict(shipment.commodity_attributes)
    updated_attributes.update(normalized_answers)

    updated_shipment = shipment.model_copy(deep=True)
    updated_shipment.commodity_attributes = updated_attributes

    for key, value in normalized_answers.items():
        if value is True:
            updated_shipment.regulatory_exception_reviews.pop(key, None)

    if "adr status" in normalized_answers:
        updated_shipment.is_adr = bool(
            normalized_answers["adr status"]
        )
        if not updated_shipment.is_adr:
            updated_shipment.adr_class = None

    if "medical temperature sensitivity" in normalized_answers:
        updated_shipment.is_temperature_controlled = bool(
            normalized_answers["medical temperature sensitivity"]
        )
        if not updated_shipment.is_temperature_controlled:
            updated_shipment.temperature_requirement = None

    return shipment.__class__.model_validate(
        updated_shipment.model_dump()
    )
