"""Offline and one-call live regressions for OpenAI Structured Outputs."""

from __future__ import annotations

import argparse
from typing import Any
from unittest.mock import patch

from openai.lib._pydantic import to_strict_json_schema

from src.ai.email_parser import _build_openai_client
from src.ai.extraction_models import OpenAIShipmentExtraction
from src.config import OPENAI_MODEL
from src.core.clarification_requirements import ClarificationRequirement


SYNTHETIC_INQUIRY = """Adana'dan Hamburg 20095'e 33 EUR palet tekstil yükümüz var.
Palet ölçüleri 120x80x150 cm, toplam 20 ton.
Tenteli komple araç fiyatı rica ederiz.
Yükleme 24.08.2026, teslim en geç 31.08.2026."""


def _object_contract_failures(schema: Any, path: str = "$") -> list[str]:
    failures: list[str] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            properties = schema.get("properties", {})
            if schema.get("additionalProperties") is not False:
                failures.append(f"{path} permits additional properties")
            if set(schema.get("required", [])) != set(properties):
                failures.append(f"{path} does not require every property")
        for key, value in schema.items():
            failures.extend(_object_contract_failures(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            failures.extend(_object_contract_failures(value, f"{path}[{index}]"))
    return failures


def evaluate_openai_structured_output_regressions() -> dict[str, object]:
    failures = _object_contract_failures(
        to_strict_json_schema(OpenAIShipmentExtraction)
    )
    schema = to_strict_json_schema(OpenAIShipmentExtraction)
    attributes = schema["properties"]["commodity_attributes"]
    if attributes.get("type") != "array" or "items" not in attributes:
        failures.append("wire commodity attributes are not an array")
    if "additionalProperties" in attributes:
        failures.append("wire commodity attributes use arbitrary keys")

    requirements = {
        key: ClarificationRequirement(
            key=key,
            value_type=value_type,
            question="Synthetic regression requirement",
            critical=False,
            commodity="Synthetic",
        )
        for key, value_type in (
            ("adr status", "boolean"),
            ("machine unit weight kg", "number"),
            ("machine model", "text"),
        )
    }
    with patch(
        "src.core.clarification_requirements."
        "get_all_clarification_requirements",
        return_value=requirements,
    ):
        internal = OpenAIShipmentExtraction.model_validate(
            {
                "commodity_attributes": [
                    {"key": "adr status", "value": False},
                    {"key": "machine unit weight kg", "value": 1250.5},
                    {"key": "machine model", "value": "MX-7"},
                ]
            }
        ).to_internal()
    values = internal.commodity_attributes
    if (
        values.get("adr status") is not False
        or type(values.get("machine unit weight kg")) is not float
        or values.get("machine model") != "MX-7"
    ):
        failures.append("wire conversion did not preserve value types")
    if OpenAIShipmentExtraction().to_internal().commodity_attributes != {}:
        failures.append("empty wire attributes were not preserved")

    try:
        OpenAIShipmentExtraction.model_validate(
            {
                "commodity_attributes": [
                    {"key": "adr status", "value": True},
                    {"key": " adr status ", "value": False},
                ]
            }
        ).to_internal()
    except ValueError:
        pass
    else:
        failures.append("duplicate wire attribute keys were accepted")

    return {"passed": not failures, "failures": failures}


def _run_live() -> int:
    try:
        response = _build_openai_client().beta.chat.completions.parse(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract only explicit shipment facts. Represent "
                        "commodity_attributes as canonical key/value entries; "
                        "do not invent missing attributes."
                    ),
                },
                {"role": "user", "content": SYNTHETIC_INQUIRY},
            ],
            response_format=OpenAIShipmentExtraction,
        )
        parsed = response.choices[0].message.parsed
        if parsed is None:
            raise ValueError("no parsed result")
        parsed.to_internal()
    except Exception as exc:
        print(f"FAIL OpenAI structured output: {type(exc).__name__}")
        return 1
    print("PASS OpenAI structured output")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.live:
        return _run_live()
    result = evaluate_openai_structured_output_regressions()
    print("PASS" if result["passed"] else "FAIL")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
