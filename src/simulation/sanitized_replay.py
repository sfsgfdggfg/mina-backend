"""Offline-safe harness for pre-sanitized historical inquiry replay.

This module deliberately contains no provider integration.  An authorized caller may
inject the current extraction boundary through ``run_replay``; the command line only
validates the external replay contract until that authorization and adapter exist.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, TextIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "1.0"
DISPOSITIONS = {
    "extraction_confirmation_required",
    "clarification_required",
    "pilot_scope_excluded",
    "supplier_rfq_approval_required",
    "data_provenance_blocked",
}
SAFETY_FIELDS = {
    "is_adr", "is_temperature_controlled", "is_high_value", "transport_mode",
    "is_oversize_or_project",
}
SCORED_FIELDS = {
    "customer_name", "pickup_country", "pickup_city", "pickup_postcode",
    "delivery_country", "delivery_city", "delivery_postcode", "commodity",
    "gross_weight_kg", "packages", "service_type", "equipment_type",
    "transport_mode", "cargo_ready_date", "required_delivery_date", "is_adr",
    "is_temperature_controlled", "temperature_requirement", "is_high_value",
    "is_oversize_or_project",
}

_EMAIL = re.compile(r"(?i)(?<![\w.-])[\w.+-]+@([\w.-]+\.[a-z]{2,})(?![\w.-])")
_PHONE = re.compile(r"(?<!\w)(?:\+?\d[\s().-]*){10,15}(?!\w)")
_TR_IBAN = re.compile(r"(?i)\bTR\s*\d{2}(?:[\s-]*\d){22}\b")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")


class ReplayValidationError(ValueError):
    """Validation failure whose message never contains replay values."""

    def __init__(self, category: str, *, case_id: str = "unavailable", field: str | None = None):
        self.category, self.case_id, self.field = category, case_id, field
        suffix = f" field={field}" if field else ""
        super().__init__(f"case={case_id} category={category}{suffix}")


class ExpectedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["known", "unknown", "not_applicable"]
    value: Any = None

    @field_validator("value")
    @classmethod
    def value_matches_state(cls, value: Any, info):
        state = info.data.get("state")
        if state == "known" and value is None:
            raise ValueError("known facts require a value")
        if state != "known" and value is not None:
            raise ValueError("unknown/not_applicable facts cannot carry a value")
        return value


class ReplayExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    facts: dict[str, ExpectedFact]
    disposition: Literal[
        "extraction_confirmation_required", "clarification_required",
        "pilot_scope_excluded", "supplier_rfq_approval_required",
        "data_provenance_blocked",
    ]
    equipment: str | None = None
    supplier_progression_expected: bool | None = None

    @field_validator("facts")
    @classmethod
    def supported_facts(cls, facts: dict[str, ExpectedFact]):
        unsupported = set(facts) - SCORED_FIELDS
        if unsupported:
            raise ValueError("unsupported expected fact")
        return facts


class ReplayCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"]
    case_id: str
    sender_address: str
    sender_domain: str | None = None
    subject: str
    body_text: str
    expected: ReplayExpectations
    operator_notes: str | None = None
    tags: list[str] = Field(default_factory=list)

    @field_validator("case_id")
    @classmethod
    def pseudonymous_id(cls, value: str):
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("case_id must be a safe pseudonymous identifier")
        return value


@dataclass(frozen=True)
class ReplayActual:
    facts: Mapping[str, Any]
    disposition: str
    equipment: str | None = None
    supplier_progressed: bool = False


@dataclass(frozen=True)
class ReplayFieldResult:
    field: str
    expected: Any
    actual: Any
    outcome: Literal[
        "correct", "incorrect", "expected_unknown", "correctly_unknown",
        "missing", "unexpected_inference", "not_applicable",
    ]


@dataclass
class ReplayCaseResult:
    case_id: str
    passed_safety: bool
    fields: list[ReplayFieldResult]
    expected_disposition: str
    actual_disposition: str
    mismatches: list[str] = field(default_factory=list)
    corrections_required: list[str] = field(default_factory=list)
    scope_correct: bool = False
    clarification_correct: bool = False
    equipment_correct: bool | None = None
    supplier_progression_correct: bool | None = None
    safety_critical_mismatches: list[str] = field(default_factory=list)


@dataclass
class ReplayAggregateResult:
    cases: list[ReplayCaseResult]
    outcome_counts: Counter[str]
    grouped_mismatches: Counter[str]
    ground_truth_fields: int
    correct_fields: int
    clarification_correct: int
    clarification_evaluated: int
    scope_correct: int
    scope_evaluated: int
    equipment_correct: int
    equipment_evaluated: int
    supplier_progression_correct: int
    supplier_progression_evaluated: int
    safety_critical_mismatches: int

    @property
    def passed(self) -> bool:
        return self.safety_critical_mismatches == 0


ExtractionCallable = Callable[[ReplayCase], ReplayActual]


def _inside_repository(path: Path) -> bool:
    try:
        path.relative_to(REPOSITORY_ROOT)
        return True
    except ValueError:
        return False


def validate_external_path(path: Path) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ReplayValidationError("input_path_unavailable") from None
    if _inside_repository(resolved):
        raise ReplayValidationError("repository_input_forbidden")
    if not resolved.is_file():
        raise ReplayValidationError("input_must_be_jsonl_file")
    return resolved


def _validate_sanitized_text(case_id: str, field_name: str, value: str) -> None:
    for match in _EMAIL.finditer(value):
        if not match.group(1).lower().endswith(".invalid"):
            raise ReplayValidationError("suspicious_email", case_id=case_id, field=field_name)
    if _TR_IBAN.search(value):
        raise ReplayValidationError("suspicious_iban", case_id=case_id, field=field_name)
    if _PHONE.search(value):
        raise ReplayValidationError("suspicious_phone", case_id=case_id, field=field_name)


def _validate_sanitized_value(case_id: str, field_name: str, value: Any) -> None:
    """Scan replay metadata values without exposing their contents on failure."""

    if isinstance(value, str):
        _validate_sanitized_text(case_id, field_name, value)
    elif isinstance(value, Mapping):
        for nested_value in value.values():
            _validate_sanitized_value(case_id, field_name, nested_value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for nested_value in value:
            _validate_sanitized_value(case_id, field_name, nested_value)


def validate_sanitization(case: ReplayCase) -> None:
    if not case.sender_address.lower().endswith(".invalid"):
        raise ReplayValidationError("sender_not_sanitized", case_id=case.case_id, field="sender_address")
    if case.sender_domain and not case.sender_domain.lower().endswith(".invalid"):
        raise ReplayValidationError("domain_not_sanitized", case_id=case.case_id, field="sender_domain")
    for name, value in (
        ("sender_address", case.sender_address), ("sender_domain", case.sender_domain or ""),
        ("subject", case.subject),
        ("body_text", case.body_text), ("operator_notes", case.operator_notes or ""),
    ):
        _validate_sanitized_text(case.case_id, name, value)
    for name, fact in case.expected.facts.items():
        _validate_sanitized_value(case.case_id, f"expected.facts.{name}", fact.value)
    _validate_sanitized_value(case.case_id, "expected.equipment", case.expected.equipment)
    _validate_sanitized_value(case.case_id, "tags", case.tags)
    customer = case.expected.facts.get("customer_name")
    if customer and customer.state == "known":
        normalized = str(customer.value).lower()
        if not normalized.startswith(("synthetic", "pseudonymous", "customer-", "customer_")):
            raise ReplayValidationError("customer_identifier_not_pseudonymous", case_id=case.case_id, field="customer_name")


def load_cases(path: Path) -> list[ReplayCase]:
    resolved = validate_external_path(path)
    cases: list[ReplayCase] = []
    seen: set[str] = set()
    try:
        with resolved.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    raw = json.loads(line)
                    case = ReplayCase.model_validate(raw)
                except (json.JSONDecodeError, ValidationError):
                    raise ReplayValidationError("malformed_schema", case_id=f"line-{line_number}") from None
                if case.case_id in seen:
                    raise ReplayValidationError("duplicate_case_id", case_id=case.case_id)
                validate_sanitization(case)
                seen.add(case.case_id)
                cases.append(case)
    except UnicodeError:
        raise ReplayValidationError("invalid_encoding") from None
    if not cases:
        raise ReplayValidationError("empty_input")
    return cases


def _score_field(name: str, expected: ExpectedFact | None, actual: Any) -> ReplayFieldResult:
    if expected is None:
        outcome = "unexpected_inference" if actual is not None else "expected_unknown"
        return ReplayFieldResult(name, None, actual, outcome)
    if expected.state == "not_applicable":
        return ReplayFieldResult(name, None, actual, "not_applicable")
    if expected.state == "unknown":
        outcome = "correctly_unknown" if actual is None else "unexpected_inference"
        return ReplayFieldResult(name, None, actual, outcome)
    if actual is None:
        outcome = "missing"
    else:
        outcome = "correct" if actual == expected.value else "incorrect"
    return ReplayFieldResult(name, expected.value, actual, outcome)


def _safety_mismatches(case: ReplayCase, actual: ReplayActual, fields: list[ReplayFieldResult]) -> list[str]:
    critical: list[str] = []
    by_name = {item.field: item for item in fields}
    for name in SAFETY_FIELDS:
        expected = case.expected.facts.get(name)
        item = by_name.get(name)
        if expected and expected.state == "known" and item and item.outcome != "correct":
            if name == "transport_mode" or expected.value is True:
                critical.append(f"safety_field:{name}")
    if case.expected.disposition == "pilot_scope_excluded" and actual.disposition != "pilot_scope_excluded":
        critical.append("scope_exclusion_lost")
    if case.expected.disposition in {"clarification_required", "pilot_scope_excluded", "data_provenance_blocked"} and actual.supplier_progressed:
        critical.append("incorrect_supplier_progression")
    return critical


def run_replay(cases: Iterable[ReplayCase], extractor: ExtractionCallable) -> ReplayAggregateResult:
    results: list[ReplayCaseResult] = []
    counts: Counter[str] = Counter()
    grouped: Counter[str] = Counter()
    for case in cases:
        validate_sanitization(case)
        actual = extractor(case)
        if actual.disposition not in DISPOSITIONS:
            raise ReplayValidationError("unsupported_actual_disposition", case_id=case.case_id)
        names = sorted(set(case.expected.facts) | set(actual.facts))
        fields = [_score_field(name, case.expected.facts.get(name), actual.facts.get(name)) for name in names]
        for item in fields:
            counts[item.outcome] += 1
            if item.outcome in {"incorrect", "missing", "unexpected_inference"}:
                grouped[f"field:{item.field}"] += 1
        disposition_correct = actual.disposition == case.expected.disposition
        if not disposition_correct:
            grouped["disposition"] += 1
        equipment_correct = None if case.expected.equipment is None else actual.equipment == case.expected.equipment
        progression_correct = None if case.expected.supplier_progression_expected is None else actual.supplier_progressed == case.expected.supplier_progression_expected
        safety = _safety_mismatches(case, actual, fields)
        mismatches = [item.field for item in fields if item.outcome in {"incorrect", "missing", "unexpected_inference"}]
        if not disposition_correct:
            mismatches.append("disposition")
        results.append(ReplayCaseResult(
            case_id=case.case_id, passed_safety=not safety, fields=fields,
            expected_disposition=case.expected.disposition, actual_disposition=actual.disposition,
            mismatches=mismatches, corrections_required=list(mismatches),
            scope_correct=(case.expected.disposition == "pilot_scope_excluded") == (actual.disposition == "pilot_scope_excluded"),
            clarification_correct=(case.expected.disposition == "clarification_required") == (actual.disposition == "clarification_required"),
            equipment_correct=equipment_correct, supplier_progression_correct=progression_correct,
            safety_critical_mismatches=safety,
        ))
    def metric(attribute: str) -> tuple[int, int]:
        values = [getattr(item, attribute) for item in results if getattr(item, attribute) is not None]
        return sum(value is True for value in values), len(values)
    clarification = metric("clarification_correct")
    scope = metric("scope_correct")
    equipment = metric("equipment_correct")
    progression = metric("supplier_progression_correct")
    return ReplayAggregateResult(
        cases=results, outcome_counts=counts, grouped_mismatches=grouped,
        ground_truth_fields=counts["correct"] + counts["incorrect"] + counts["missing"],
        correct_fields=counts["correct"], clarification_correct=clarification[0],
        clarification_evaluated=clarification[1], scope_correct=scope[0], scope_evaluated=scope[1],
        equipment_correct=equipment[0], equipment_evaluated=equipment[1],
        supplier_progression_correct=progression[0], supplier_progression_evaluated=progression[1],
        safety_critical_mismatches=sum(len(item.safety_critical_mismatches) for item in results),
    )


def print_summary(
    result: ReplayAggregateResult,
    stream: TextIO | None = None,
) -> None:
    stream = stream or sys.stdout
    c = result.outcome_counts
    print("Sanitized replay summary", file=stream)
    print(f"Cases: {len(result.cases)}", file=stream)
    print(f"Extraction fields evaluated: {result.ground_truth_fields}", file=stream)
    print(f"Correct: {c['correct']}", file=stream)
    print(f"Incorrect: {c['incorrect']}", file=stream)
    print(f"Missing: {c['missing']}", file=stream)
    print(f"Unexpected inference: {c['unexpected_inference']}", file=stream)
    print(f"Clarification decisions: {result.clarification_correct}/{result.clarification_evaluated} correct", file=stream)
    print(f"Scope decisions: {result.scope_correct}/{result.scope_evaluated} correct", file=stream)
    print(f"Safety-critical mismatches: {result.safety_critical_mismatches}", file=stream)
    for case in result.cases:
        for category in case.mismatches:
            print(f"Mismatch: case={case.case_id} category={category}", file=stream)
    print(f"\nSanitized historical replay: {'PASS' if result.passed else 'FAIL'}", file=stream)


def replay_exit_code(result: ReplayAggregateResult) -> int:
    """Return failure only for safety-critical replay evidence."""

    return 0 if result.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate pre-sanitized external historical replay JSONL")
    parser.add_argument("--input", type=Path, required=True, help="external pre-sanitized JSONL path")
    args = parser.parse_args(argv)
    try:
        cases = load_cases(args.input)
    except ReplayValidationError as exc:
        print(f"Sanitized replay rejected: {exc}", file=sys.stderr)
        return 2
    print(f"Sanitized replay input accepted: {len(cases)} case(s)")
    print("Execution unavailable: no authorized extraction adapter is configured.")
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
